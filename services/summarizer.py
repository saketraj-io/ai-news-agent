"""
services/summarizer.py
──────────────────────
Gemini-powered article summarisation service.

Summary modes:
  STANDARD  — 2-3 sentence factual summary (default)
  ANCHOR    — broadcast-script narration, first-person news anchor voice
  BULLET    — 4-5 key facts as bullet points
  HEADLINE  — ultra-compact: one punchy headline + one supporting sentence

Design principles:
  - New google-genai SDK (google-generativeai is deprecated as of 2025)
  - Token-bucket rate limiter: stays within 15 RPM free-tier ceiling
  - Tenacity retry with jitter on 429 / 503 responses
  - Input truncation: never exceeds settings.max_input_chars
  - Batch summarisation with configurable delay between calls
  - Full graceful degradation: returns SummaryResult(ok=False) on any error
  - No global state: GeminiClient is fully re-entrant

Public surface:
  summarizer = ArticleSummarizer()

  # Single article (Article dataclass from news_fetcher)
  result = summarizer.summarize(article, mode=SummaryMode.ANCHOR)

  # Raw text (e.g. from scraper)
  result = summarizer.summarize_text(text, title="...", mode=SummaryMode.BULLET)

  # Batch (list of Article objects)
  results = summarizer.summarize_batch(articles, mode=SummaryMode.STANDARD)
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
    wait_combine,
    before_sleep_log,
)

from config.settings import settings
from utils.helpers import TTLCache, truncate_text, estimate_tokens
from utils.logger import log

import logging
_std_log = logging.getLogger(__name__)

# ── Google Gen AI SDK (new unified SDK) ──────────────────────────────
try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    log.warning("google-genai not installed. Run: pip install google-genai")


# ─────────────────────────────────────────────────────────────────────
# Summary Modes
# ─────────────────────────────────────────────────────────────────────

class SummaryMode(str, Enum):
    """
    Controls the tone and format of the generated summary.
    The string value doubles as a display label in the UI.
    """
    STANDARD = "standard"   # Concise factual 2-3 sentence summary
    ANCHOR   = "anchor"     # Professional TV news anchor broadcast script
    BULLET   = "bullet"     # 4-5 key facts as bullet points
    HEADLINE = "headline"   # One punchy headline + one supporting sentence


# ─────────────────────────────────────────────────────────────────────
# Prompt Templates
# ─────────────────────────────────────────────────────────────────────

_PROMPTS: dict[SummaryMode, str] = {

    SummaryMode.STANDARD: """\
You are a professional news editor. Read the article below and write a concise, \
factual summary in exactly 2-3 sentences. Capture the who, what, when, where, \
and why. Use plain English. Do NOT use phrases like "The article states" or \
"According to the article". Write in third person. Do NOT add commentary or opinion.

Article Title: {title}

Article Text:
{text}

Summary:""",

    SummaryMode.ANCHOR: """\
You are a professional television news anchor delivering a live broadcast segment. \
Read the article below and write a compelling broadcast script (3-4 sentences) as \
if you are presenting it on air right now. Use clear, confident, broadcast-quality \
language. Start directly with the news — no "Good evening" opener needed. \
Keep it engaging but factual. End with a brief forward-looking sentence where applicable.

Article Title: {title}

Article Text:
{text}

Broadcast Script:""",

    SummaryMode.BULLET: """\
You are a news editor creating a quick-read digest. Read the article below and \
extract the 4-5 most important facts. Format your response as a clean bullet list \
using "•" as the bullet character. Each bullet should be one sentence, factual, \
and self-contained. Do not number the bullets. No intro line needed — start \
directly with the first bullet.

Article Title: {title}

Article Text:
{text}

Key Facts:""",

    SummaryMode.HEADLINE: """\
You are a senior headline writer for a major newspaper. Read the article below \
and produce two lines:
Line 1: A punchy, informative headline (max 12 words, Title Case, no full stop)
Line 2: A single supporting sentence (max 25 words) that adds essential context.

Output ONLY these two lines. No labels, no extra text.

Article Title: {title}

Article Text:
{text}

Output:""",
}


# ─────────────────────────────────────────────────────────────────────
# Result Model
# ─────────────────────────────────────────────────────────────────────

@dataclass
class SummaryResult:
    """
    Normalised output from any summarisation attempt.
    Callers check `.ok` before using `.summary`.
    """
    article_id: str          # Matches Article.id from news_fetcher
    url: str
    title: str
    summary: str             # The generated text (empty string if ok=False)
    mode: SummaryMode
    model_used: str          # e.g. "gemini-2.0-flash"
    ok: bool
    input_chars: int = 0     # Length of text fed to the model
    error: Optional[str] = None

    @property
    def is_bullet(self) -> bool:
        return self.mode == SummaryMode.BULLET

    @property
    def is_anchor(self) -> bool:
        return self.mode == SummaryMode.ANCHOR

    def display_text(self) -> str:
        """Returns summary ready for Streamlit rendering."""
        return self.summary if self.ok else f"_(Summary unavailable: {self.error})_"


# ─────────────────────────────────────────────────────────────────────
# Token-Bucket Rate Limiter
# ─────────────────────────────────────────────────────────────────────

class _RateLimiter:
    """
    Thread-safe token-bucket rate limiter.
    Ensures we never exceed `rpm` calls per 60 seconds.

    Usage:
        limiter = _RateLimiter(rpm=15)
        limiter.acquire()   # blocks until a call slot is available
    """

    def __init__(self, rpm: int) -> None:
        self._interval = 60.0 / rpm     # seconds per token
        self._lock = threading.Lock()
        self._last_called: float = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_called
            wait = self._interval - elapsed
            if wait > 0:
                log.debug("Rate limiter: sleeping {:.2f}s to respect {} RPM", wait, round(60 / self._interval))
                time.sleep(wait)
            self._last_called = time.monotonic()


# ─────────────────────────────────────────────────────────────────────
# Gemini Client
# ─────────────────────────────────────────────────────────────────────

class GeminiClient:
    """
    Thin wrapper around the google-genai SDK.
    Handles:
      - Client initialisation + API key validation
      - Safety settings (permissive for news content)
      - Generation config (temperature, max tokens)
      - Retry with exponential backoff + jitter on 429/503
      - Rate limiting via token bucket
    """

    def __init__(self) -> None:
        # Read key fresh from environment so Streamlit cache ordering never
        # causes an empty key.  os.environ is populated by load_dotenv()
        # at the very top of app.py before any project module is imported.
        import os as _os
        self._api_key = (
            _os.environ.get("GEMINI_API_KEY")
            or settings.gemini_api_key
            or ""
        )
        self._model   = settings.gemini_model
        self._limiter = _RateLimiter(rpm=settings.gemini_rpm_limit)
        self._client: Optional[object] = None

        if not GENAI_AVAILABLE:
            log.error("google-genai SDK not installed. pip install google-genai")
            return
        if not self._api_key:
            log.warning("GEMINI_API_KEY not set — summarisation disabled.")
            return

        try:
            self._client = genai.Client(api_key=self._api_key)
            log.info("GeminiClient ready | model={}", self._model)
        except Exception as exc:
            log.error("Failed to initialise Gemini client: {}", exc)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None and GENAI_AVAILABLE

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(settings.api_max_retries),
        wait=wait_combine(
            wait_exponential(multiplier=2, min=2, max=30),
            wait_random(min=0, max=2),           # jitter prevents thundering herd
        ),
        before_sleep=before_sleep_log(_std_log, logging.WARNING),
        reraise=True,
    )
    def _call_api(self, prompt: str) -> str:
        """
        Core API call with retry. Raises on all failures (tenacity catches them).
        Caller wraps this in a try/except for the final error surface.
        """
        self._limiter.acquire()

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=settings.gemini_temperature,
                max_output_tokens=settings.gemini_max_output_tokens,
                safety_settings=[
                    # News content can mention violence/politics — use low blocking
                    genai_types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_ONLY_HIGH",
                    ),
                    genai_types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_MEDIUM_AND_ABOVE",
                    ),
                    genai_types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_ONLY_HIGH",
                    ),
                    genai_types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_ONLY_HIGH",
                    ),
                ],
            ),
        )

        # Surface any safety blocks as a clear error
        if not response.text:
            finish = getattr(response, "prompt_feedback", None)
            raise ValueError(f"Gemini returned empty response. Feedback: {finish}")

        return response.text.strip()

    def generate(self, prompt: str) -> str | None:
        """
        Public generate method. Returns text or None on unrecoverable failure.
        """
        if not self.available:
            return None
        try:
            return self._call_api(prompt)
        except Exception as exc:
            # Categorise common errors for better log messages
            err_str = str(exc).lower()
            if "429" in err_str or "quota" in err_str:
                log.error("Gemini rate limit / quota exceeded: {}", exc)
            elif "api_key" in err_str or "auth" in err_str:
                log.error("Gemini authentication error — check GEMINI_API_KEY: {}", exc)
            elif "safety" in err_str or "block" in err_str:
                log.warning("Gemini safety block for prompt: {}", exc)
            else:
                log.error("Gemini API error: {}", exc)
            return None


# ─────────────────────────────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────────────────────────────

def _build_prompt(title: str, text: str, mode: SummaryMode) -> tuple[str, int]:
    """
    Fills the prompt template for the given mode.
    Truncates article text to settings.max_input_chars.
    Returns (filled_prompt, chars_used).
    """
    # Truncate input to avoid overwhelming the model
    truncated = text[:settings.max_input_chars]
    prompt = _PROMPTS[mode].format(
        title=title or "Untitled",
        text=truncated,
    )
    return prompt, len(truncated)


# ─────────────────────────────────────────────────────────────────────
# Post-processors (mode-specific cleanup)
# ─────────────────────────────────────────────────────────────────────

def _postprocess(raw: str, mode: SummaryMode) -> str:
    """
    Cleans model output per mode:
    - Strips leading labels the model sometimes emits
    - Normalises bullet characters
    - Enforces length limits
    """
    text = raw.strip()

    # Strip common model preambles
    PREAMBLES = [
        "summary:", "broadcast script:", "key facts:", "output:",
        "here is the summary:", "here are the key facts:",
        "here's the summary:", "here's the broadcast script:",
    ]
    lower = text.lower()
    for p in PREAMBLES:
        if lower.startswith(p):
            text = text[len(p):].strip()
            lower = text.lower()
            break

    if mode == SummaryMode.BULLET:
        # Normalise various bullet chars to "•"
        import re
        text = re.sub(r"^(\s*[-*–—])\s+", "• ", text, flags=re.MULTILINE)
        # Ensure every line that doesn't start with • gets one
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("•"):
                line = f"• {line}"
            if line:
                lines.append(line)
        text = "\n".join(lines)

    elif mode == SummaryMode.STANDARD:
        # Cap to settings.summary_max_words
        words = text.split()
        if len(words) > settings.summary_max_words + 20:   # 20-word grace margin
            text = " ".join(words[:settings.summary_max_words]) + "…"

    elif mode == SummaryMode.HEADLINE:
        # Ensure exactly 2 lines
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 2:
            text = f"{lines[0]}\n{lines[1]}"
        elif len(lines) == 1:
            text = lines[0]

    return text.strip()


# ─────────────────────────────────────────────────────────────────────
# ArticleSummarizer — Public Orchestrator
# ─────────────────────────────────────────────────────────────────────

class ArticleSummarizer:
    """
    Orchestrates Gemini-powered summarisation for single articles
    or batches, in any of the four SummaryMode variants.

    Usage:
        from services.summarizer import ArticleSummarizer, SummaryMode
        from services.news_fetcher import Article

        summarizer = ArticleSummarizer()

        # Single article (uses Article dataclass)
        result = summarizer.summarize(article, mode=SummaryMode.ANCHOR)

        # Raw text
        result = summarizer.summarize_text(
            text="Full article text here...",
            title="OpenAI launches GPT-5",
            mode=SummaryMode.BULLET,
        )

        # Batch
        results = summarizer.summarize_batch(articles, mode=SummaryMode.STANDARD)
    """

    def __init__(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """
        Args:
            on_progress: Optional callback(done, total) called after each
                         batch item completes — useful for Streamlit progress bars.
        """
        self._gemini    = GeminiClient()
        self._cache     = TTLCache(ttl_seconds=settings.cache_ttl_seconds)
        self._on_progress = on_progress
        log.info(
            "ArticleSummarizer ready | Gemini available={} | model={}",
            self._gemini.available,
            settings.gemini_model,
        )

    # ── Public: single article ────────────────────────────────────────

    def summarize(
        self,
        article,                               # Article dataclass from news_fetcher
        mode: SummaryMode = SummaryMode.STANDARD,
        force_refresh: bool = False,
        use_scraped_text: bool = True,
    ) -> SummaryResult:
        """
        Summarises an Article object.

        Priority for input text:
          1. article.content (full body — best quality)
          2. article.description (GNews blurb — fallback)

        Args:
            article:          Article dataclass (from NewsFetcher)
            mode:             Which summary style to use
            force_refresh:    Bypass cache and re-summarise
            use_scraped_text: If article has 'scraped_text' attr, prefer it
        """
        # Prefer scraped full text if available
        text = ""
        if use_scraped_text and hasattr(article, "scraped_text") and article.scraped_text:
            text = article.scraped_text
        if not text:
            text = article.content or article.description or ""

        return self.summarize_text(
            text=text,
            title=article.title,
            article_id=article.id,
            url=article.url,
            mode=mode,
            force_refresh=force_refresh,
        )

    def summarize_text(
        self,
        text: str,
        title: str = "",
        article_id: str = "",
        url: str = "",
        mode: SummaryMode = SummaryMode.STANDARD,
        force_refresh: bool = False,
    ) -> SummaryResult:
        """
        Summarises raw text. Can be used independently of Article objects.
        Returns SummaryResult(ok=False) if Gemini is unavailable or fails.
        """
        if not text.strip():
            return SummaryResult(
                article_id=article_id, url=url, title=title,
                summary="", mode=mode,
                model_used=settings.gemini_model,
                ok=False, error="Empty input text",
            )

        # ── Cache lookup ──────────────────────────────────────────────
        cache_key = f"summary:{article_id or hash(text[:200])}:{mode.value}"
        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Summary cache hit: {} mode={}", title[:40], mode.value)
                return cached

        # ── Gemini unavailable → return descriptive failure ────────────
        if not self._gemini.available:
            result = SummaryResult(
                article_id=article_id, url=url, title=title,
                summary="", mode=mode,
                model_used=settings.gemini_model,
                ok=False,
                error="Gemini unavailable — check GEMINI_API_KEY",
            )
            return result

        # ── Build prompt + call Gemini ────────────────────────────────
        prompt, input_chars = _build_prompt(title, text, mode)
        log.debug(
            "Calling Gemini | title={} | mode={} | input_chars={}",
            title[:40], mode.value, input_chars,
        )

        raw_output = self._gemini.generate(prompt)

        if raw_output is None:
            result = SummaryResult(
                article_id=article_id, url=url, title=title,
                summary="", mode=mode,
                model_used=settings.gemini_model,
                ok=False, input_chars=input_chars,
                error="Gemini returned no output",
            )
            self._cache.set(cache_key, result)
            return result

        # ── Post-process + return ─────────────────────────────────────
        summary = _postprocess(raw_output, mode)
        log.info(
            "Summary OK | mode={} | words={} | title={}",
            mode.value, len(summary.split()), title[:40],
        )

        result = SummaryResult(
            article_id=article_id, url=url, title=title,
            summary=summary, mode=mode,
            model_used=settings.gemini_model,
            ok=True, input_chars=input_chars,
        )
        self._cache.set(cache_key, result)
        return result

    # ── Public: batch ─────────────────────────────────────────────────

    def summarize_batch(
        self,
        articles: list,
        mode: SummaryMode = SummaryMode.STANDARD,
        max_articles: Optional[int] = None,
        force_refresh: bool = False,
    ) -> list[SummaryResult]:
        """
        Summarises a list of Article objects sequentially with rate-limit spacing.

        Sequential (not parallel) to respect Gemini's 15 RPM free-tier limit.
        Cached articles skip the API call entirely.

        Args:
            articles:     List of Article dataclass objects
            mode:         Summary mode applied to all articles
            max_articles: Limit how many to process (None = all)
            force_refresh: Bypass cache for all articles

        Returns:
            List of SummaryResult in the same order as input articles.
        """
        targets = articles[:max_articles] if max_articles else articles
        total = len(targets)
        results: list[SummaryResult] = []

        log.info("Batch summarise: {} articles | mode={}", total, mode.value)

        for i, article in enumerate(targets, start=1):
            # Check cache first to avoid unnecessary delays
            cache_key = f"summary:{article.id}:{mode.value}"
            cached = self._cache.get(cache_key) if not force_refresh else None

            if cached is not None:
                log.debug("[{}/{}] Cache hit: {}", i, total, article.title[:40])
                results.append(cached)
            else:
                log.info("[{}/{}] Summarising: {}", i, total, article.title[:40])
                result = self.summarize(article, mode=mode, force_refresh=force_refresh)
                results.append(result)

                # Rate-limit spacing only when we actually hit the API
                if i < total and result.ok:
                    time.sleep(settings.batch_request_delay_s)

            # Fire progress callback if provided
            if self._on_progress:
                try:
                    self._on_progress(i, total)
                except Exception:
                    pass  # never let UI callbacks crash the pipeline

        ok_count = sum(1 for r in results if r.ok)
        log.info(
            "Batch complete: {}/{} summarised successfully in mode={}",
            ok_count, total, mode.value,
        )
        return results

    # ── Convenience: re-summarise in a different mode ─────────────────

    def change_mode(
        self,
        existing: SummaryResult,
        new_mode: SummaryMode,
        original_text: str,
    ) -> SummaryResult:
        """
        Re-summarises the same article text in a different mode.
        Useful for UI mode-switcher without re-fetching the article.
        """
        return self.summarize_text(
            text=original_text,
            title=existing.title,
            article_id=existing.article_id,
            url=existing.url,
            mode=new_mode,
            force_refresh=True,   # always call Gemini; modes produce different outputs
        )

    # ── Cache control ─────────────────────────────────────────────────

    def clear_cache(self) -> None:
        self._cache.clear()
        log.info("Summary cache cleared.")

    def set_progress_callback(self, cb: Callable[[int, int], None]) -> None:
        """Attach or replace the batch progress callback at runtime."""
        self._on_progress = cb


# ─────────────────────────────────────────────────────────────────────
# Standalone helper — useful for quick one-off calls from the UI
# ─────────────────────────────────────────────────────────────────────

def quick_summarize(text: str, title: str = "", mode: SummaryMode = SummaryMode.STANDARD) -> str:
    """
    Module-level convenience function.
    Returns the summary string directly, or an empty string on failure.
    Creates a fresh ArticleSummarizer on each call (no cache sharing).

    Intended for one-off calls from Streamlit callbacks.
    """
    s = ArticleSummarizer()
    result = s.summarize_text(text=text, title=title, mode=mode)
    return result.summary if result.ok else ""
