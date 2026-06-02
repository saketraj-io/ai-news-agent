"""
services/categorizer.py
───────────────────────
Gemini-powered article categorisation and sentiment analysis.

For each article this service produces:
  - topic       : Refined topic label (matches TOPICS list in settings)
  - sentiment   : Positive | Neutral | Negative
  - tags        : 3-5 keyword tags (suitable for filtering/search)
  - confidence  : 0.0–1.0 float (model self-reported reliability)

Two-layer strategy:
  Layer 1 (Gemini) — structured JSON prompt → parse result
  Layer 2 (Keyword fallback) — regex/keyword matching when Gemini
                                is unavailable or returns bad JSON

The GeminiClient is imported directly from summarizer.py so we
share one rate-limiter instance and avoid duplicate client state.

Public surface:
  cat = ArticleCategorizer()
  result = cat.categorize(article)          # single article
  results = cat.categorize_batch(articles)  # batch with rate-limit spacing
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings, TOPICS, SENTIMENT_LABELS, GNEWS_CATEGORY_MAP
from utils.helpers import TTLCache, truncate_text
from utils.logger import log

# Reuse GeminiClient from summarizer — shares rate limiter logic
from services.summarizer import GeminiClient


# ─────────────────────────────────────────────────────────────────────
# Result Model
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CategoryResult:
    """
    Normalised output from one categorisation pass.
    Callers check `.ok` before relying on topic/sentiment/tags.
    """
    article_id: str
    url: str
    topic: str               # One of TOPICS (e.g. "Artificial Intelligence")
    sentiment: str           # "Positive" | "Neutral" | "Negative"
    tags: list[str]          # 3-5 keyword tags
    confidence: float        # 0.0–1.0
    method: str              # "gemini" | "keyword_fallback"
    ok: bool
    error: Optional[str] = None

    # ── Convenience properties ─────────────────────────────────────────
    @property
    def sentiment_emoji(self) -> str:
        return {"Positive": "🟢", "Neutral": "🟡", "Negative": "🔴"}.get(
            self.sentiment, "⚪"
        )

    @property
    def tags_display(self) -> str:
        """Comma-separated tags ready for UI display."""
        return ", ".join(f"#{t}" for t in self.tags)

    def to_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "url": self.url,
            "topic": self.topic,
            "sentiment": self.sentiment,
            "tags": self.tags,
            "confidence": self.confidence,
            "method": self.method,
            "ok": self.ok,
            "error": self.error,
        }


# ─────────────────────────────────────────────────────────────────────
# Gemini Prompt
# ─────────────────────────────────────────────────────────────────────

# Gemini is instructed to return strict JSON — no markdown, no prose.
_CATEGORISE_PROMPT = """\
You are a news intelligence system. Analyse the article below and return ONLY \
a valid JSON object — no markdown, no explanation, no extra text.

The JSON must have exactly these four fields:
  "topic"      : one of {topics}
  "sentiment"  : one of ["Positive", "Neutral", "Negative"]
  "tags"       : array of 3-5 lowercase single-word or hyphenated keyword tags
  "confidence" : float between 0.0 and 1.0 reflecting your certainty

Rules:
- Choose the MOST SPECIFIC topic that fits. If the article is about AI research,
  pick "Artificial Intelligence" not "Technology".
- Sentiment reflects the article's overall tone, not your opinion of the news.
- Tags should be specific nouns or noun-phrases (e.g. "openai", "climate-change",
  "federal-reserve", "vaccine"). Avoid generic tags like "news" or "article".
- Output ONLY the JSON object. Nothing before or after it.

Article Title: {title}

Article Text (first 2000 chars):
{text}

JSON:"""


# ─────────────────────────────────────────────────────────────────────
# Keyword Fallback Engine
# ─────────────────────────────────────────────────────────────────────

# Maps topic labels → keyword signals (checked against title + description)
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Artificial Intelligence": [
        "artificial intelligence", "machine learning", "deep learning",
        "neural network", "large language model", "llm", "gpt", "gemini",
        "openai", "anthropic", "ai model", "generative ai", "chatbot",
    ],
    "Technology": [
        "software", "hardware", "startup", "silicon valley", "app",
        "smartphone", "cybersecurity", "data breach", "cloud computing",
        "semiconductor", "chip", "processor", "quantum", "robotics",
    ],
    "Business & Finance": [
        "stock", "market", "economy", "inflation", "interest rate",
        "federal reserve", "gdp", "earnings", "revenue", "ipo", "merger",
        "acquisition", "wall street", "nasdaq", "dow jones", "crypto",
        "bitcoin", "investment", "venture capital",
    ],
    "Science": [
        "research", "study", "scientist", "discovery", "experiment",
        "nasa", "space", "astronomy", "physics", "biology", "chemistry",
        "gene", "dna", "protein", "particle", "quantum", "telescope",
    ],
    "Health": [
        "health", "medical", "disease", "vaccine", "drug", "fda",
        "hospital", "patient", "cancer", "diabetes", "mental health",
        "pandemic", "covid", "virus", "treatment", "therapy", "surgery",
    ],
    "Politics": [
        "president", "congress", "senate", "election", "vote", "democrat",
        "republican", "government", "policy", "legislation", "white house",
        "parliament", "minister", "diplomat", "sanction", "treaty",
    ],
    "Sports": [
        "nba", "nfl", "soccer", "football", "basketball", "baseball",
        "tennis", "golf", "olympic", "world cup", "championship",
        "athlete", "coach", "player", "team", "tournament", "match",
    ],
    "Climate & Environment": [
        "climate", "environment", "carbon", "emission", "renewable",
        "solar", "wind energy", "deforestation", "biodiversity",
        "ocean", "polar", "wildfire", "flood", "drought", "epa",
        "green energy", "net zero", "sustainability",
    ],
    "Entertainment": [
        "movie", "film", "music", "album", "celebrity", "actor",
        "actress", "singer", "award", "oscar", "grammy", "netflix",
        "streaming", "box office", "concert", "tour", "hollywood",
    ],
    "World": [
        "war", "conflict", "military", "un", "united nations",
        "humanitarian", "refugee", "nato", "g20", "foreign", "bilateral",
        "diplomacy", "ambassador", "sanction",
    ],
    "General": [],
}

# Sentiment keyword signals
_POSITIVE_SIGNALS: list[str] = [
    "breakthrough", "success", "growth", "win", "achieve", "record",
    "improve", "launch", "approve", "soar", "gain", "rise", "rally",
    "positive", "hope", "promising", "celebrate", "milestone", "advance",
    "recovery", "surge", "profit", "boom", "innovation",
]
_NEGATIVE_SIGNALS: list[str] = [
    "crisis", "crash", "fall", "drop", "decline", "fail", "loss",
    "death", "disaster", "attack", "war", "risk", "warn", "cut",
    "layoff", "bankrupt", "scandal", "fraud", "arrest", "sentence",
    "plunge", "collapse", "threat", "concern", "controversy", "resign",
]


def _keyword_categorise(title: str, description: str) -> CategoryResult:
    """
    Keyword-based fallback categoriser.
    Scores topics by keyword hits in title + description.
    Sentiment scored by presence of positive/negative signals.
    Returns a CategoryResult with method='keyword_fallback'.
    """
    combined = f"{title} {description}".lower()

    # ── Topic scoring ─────────────────────────────────────────────────
    scores: dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        # Title matches count double
        title_score = sum(2 for kw in keywords if kw in title.lower())
        scores[topic] = score + title_score

    best_topic = max(scores, key=scores.get)
    # Fall back to General if no keywords matched
    if scores[best_topic] == 0:
        best_topic = "General"
    confidence = min(scores[best_topic] / 10.0, 0.75)  # cap at 0.75 for fallback

    # ── Sentiment scoring ─────────────────────────────────────────────
    pos = sum(1 for w in _POSITIVE_SIGNALS if w in combined)
    neg = sum(1 for w in _NEGATIVE_SIGNALS if w in combined)
    if pos > neg:
        sentiment = "Positive"
    elif neg > pos:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    # ── Tags: top-N matched keywords from winning topic ───────────────
    matched = [
        kw.replace(" ", "-")
        for kw in _TOPIC_KEYWORDS.get(best_topic, [])
        if kw in combined
    ][:5]
    # Supplement with single words from title if we have fewer than 3
    if len(matched) < 3:
        title_words = [w for w in re.findall(r"\b[a-z]{4,}\b", title.lower())
                       if w not in {"that", "this", "with", "from", "have",
                                    "been", "they", "their", "which"}]
        matched += title_words[:3 - len(matched)]
    tags = list(dict.fromkeys(matched))[:5]  # deduplicate, limit to 5

    return CategoryResult(
        article_id="",
        url="",
        topic=best_topic,
        sentiment=sentiment,
        tags=tags or ["news"],
        confidence=round(confidence, 2),
        method="keyword_fallback",
        ok=True,
    )


# ─────────────────────────────────────────────────────────────────────
# JSON Parser
# ─────────────────────────────────────────────────────────────────────

def _parse_gemini_json(raw: str) -> dict | None:
    """
    Extracts and validates the JSON object from Gemini's response.
    Handles common model quirks:
      - JSON wrapped in ```json ... ``` code fences
      - Trailing commas
      - Extra whitespace / newlines
    Returns parsed dict or None if parsing fails.
    """
    if not raw:
        return None

    # Strip markdown code fences if present
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Find the first complete {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)

    # Remove trailing commas before } or ] (common model mistake)
    text = re.sub(r",\s*([}\]])", r"\1", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.debug("JSON parse error: {} | raw snippet: {}", exc, text[:200])
        return None

    # Validate required fields
    required = {"topic", "sentiment", "tags", "confidence"}
    if not required.issubset(data.keys()):
        log.debug("JSON missing required fields: {}", required - set(data.keys()))
        return None

    return data


def _validate_and_coerce(data: dict) -> dict:
    """
    Coerces/validates parsed JSON values to expected types.
    - topic: must be in TOPICS list (or closest match)
    - sentiment: must be in SENTIMENT_LABELS
    - tags: list of strings, max 5
    - confidence: clamped to [0.0, 1.0]
    """
    # Validate topic — find closest match if not exact
    topic = data.get("topic", "General")
    if topic not in TOPICS:
        # Try case-insensitive match
        topic_lower = topic.lower()
        match = next(
            (t for t in TOPICS if t.lower() == topic_lower),
            None,
        )
        if not match:
            # Try partial match
            match = next(
                (t for t in TOPICS if topic_lower in t.lower() or t.lower() in topic_lower),
                "General",
            )
        topic = match

    # Validate sentiment
    sentiment = data.get("sentiment", "Neutral")
    if sentiment not in SENTIMENT_LABELS:
        sentiment = "Neutral"

    # Validate tags
    raw_tags = data.get("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = [str(raw_tags)]
    tags = [
        str(t).lower().strip().replace(" ", "-")
        for t in raw_tags
        if t
    ][:5]
    if not tags:
        tags = ["news"]

    # Validate confidence
    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "topic": topic,
        "sentiment": sentiment,
        "tags": tags,
        "confidence": round(confidence, 2),
    }


# ─────────────────────────────────────────────────────────────────────
# ArticleCategorizer — Public Orchestrator
# ─────────────────────────────────────────────────────────────────────

class ArticleCategorizer:
    """
    Classifies articles by topic + sentiment using Gemini,
    with automatic keyword fallback when Gemini is unavailable.

    Usage:
        cat = ArticleCategorizer()
        result = cat.categorize(article)
        print(result.topic, result.sentiment, result.tags)

        results = cat.categorize_batch(articles)
    """

    def __init__(self) -> None:
        self._gemini = GeminiClient()
        self._cache  = TTLCache(ttl_seconds=settings.cache_ttl_seconds)
        log.info(
            "ArticleCategorizer ready | Gemini={} | fallback=keyword",
            "gemini" if self._gemini.available else "unavailable (using keyword fallback)",
        )

    # ── Public: single article ────────────────────────────────────────

    def categorize(
        self,
        article,                     # Article dataclass from news_fetcher
        force_refresh: bool = False,
    ) -> CategoryResult:
        """
        Categorises a single Article.
        Tries Gemini first; falls back to keyword matching silently.
        """
        cache_key = f"cat:{article.id}"
        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Categorise cache hit: {}", article.title[:40])
                return cached

        result = self._run(article)
        # Stamp the article ID and URL onto the result
        result.article_id = article.id
        result.url = article.url

        self._cache.set(cache_key, result)
        return result

    def categorize_text(
        self,
        title: str,
        text: str = "",
        article_id: str = "",
        url: str = "",
    ) -> CategoryResult:
        """
        Categorise raw title + text without an Article object.
        Useful for search results or ad-hoc text.
        """
        # Create a lightweight stub that _run() can accept
        class _Stub:
            pass
        stub = _Stub()
        stub.id = article_id or "adhoc"
        stub.url = url
        stub.title = title
        stub.description = text[:500]
        stub.content = text

        result = self._run(stub)
        result.article_id = article_id
        result.url = url
        return result

    def categorize_batch(
        self,
        articles: list,
        force_refresh: bool = False,
        delay_s: float | None = None,
    ) -> list[CategoryResult]:
        """
        Categorises a list of articles sequentially with rate-limit spacing.
        Cached results skip the API call and the delay.

        Args:
            articles:     List of Article objects
            force_refresh: Bypass cache for all articles
            delay_s:      Seconds between API calls (default: settings.batch_request_delay_s)

        Returns:
            List of CategoryResult in same order as input.
        """
        delay = delay_s if delay_s is not None else settings.batch_request_delay_s
        total = len(articles)
        results: list[CategoryResult] = []

        log.info("Batch categorise: {} articles", total)

        for i, article in enumerate(articles, start=1):
            cache_key = f"cat:{article.id}"
            cached = self._cache.get(cache_key) if not force_refresh else None

            if cached is not None:
                log.debug("[{}/{}] Cache hit: {}", i, total, article.title[:40])
                results.append(cached)
            else:
                log.info("[{}/{}] Categorising: {}", i, total, article.title[:40])
                result = self.categorize(article, force_refresh=force_refresh)
                results.append(result)

                # Only sleep when Gemini was actually called
                if i < total and self._gemini.available:
                    time.sleep(delay)

        ok_count = sum(1 for r in results if r.ok)
        gemini_count = sum(1 for r in results if r.method == "gemini")
        log.info(
            "Batch categorise done: {}/{} ok | {} via Gemini | {} via keyword",
            ok_count, total, gemini_count, ok_count - gemini_count,
        )
        return results

    # ── Internal ──────────────────────────────────────────────────────

    def _run(self, article) -> CategoryResult:
        """
        Runs the full categorisation pipeline for one article.
        Returns keyword_fallback result if Gemini is unavailable or fails.
        """
        # ── Input text: prefer content > description > title ──────────
        text = (
            getattr(article, "content", "")
            or getattr(article, "description", "")
            or ""
        )
        title = getattr(article, "title", "") or ""

        # ── Gemini path ───────────────────────────────────────────────
        if self._gemini.available:
            result = self._gemini_categorise(title, text)
            if result is not None:
                return result
            log.warning("Gemini categorise failed for '{}' — using keyword fallback", title[:50])

        # ── Keyword fallback ──────────────────────────────────────────
        description = getattr(article, "description", text[:200])
        return _keyword_categorise(title, description)

    def _gemini_categorise(self, title: str, text: str) -> CategoryResult | None:
        """
        Calls Gemini with a structured JSON prompt.
        Returns CategoryResult on success, None on any failure.
        """
        # Build prompt — truncate text to keep within context limits
        truncated_text = truncate_text(text, 2000)
        topics_str = json.dumps(TOPICS)
        prompt = _CATEGORISE_PROMPT.format(
            topics=topics_str,
            title=title or "Untitled",
            text=truncated_text or title,
        )

        raw = self._gemini.generate(prompt)
        if raw is None:
            return None

        data = _parse_gemini_json(raw)
        if data is None:
            log.warning("Could not parse Gemini JSON for: {}", title[:50])
            return None

        coerced = _validate_and_coerce(data)
        log.debug(
            "Gemini categorise OK | topic={} | sentiment={} | conf={} | title={}",
            coerced["topic"], coerced["sentiment"],
            coerced["confidence"], title[:40],
        )
        return CategoryResult(
            article_id="",      # stamped by caller
            url="",             # stamped by caller
            topic=coerced["topic"],
            sentiment=coerced["sentiment"],
            tags=coerced["tags"],
            confidence=coerced["confidence"],
            method="gemini",
            ok=True,
        )

    # ── Cache control ─────────────────────────────────────────────────

    def clear_cache(self) -> None:
        self._cache.clear()
        log.info("Categoriser cache cleared.")
