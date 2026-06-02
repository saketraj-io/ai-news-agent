"""
services/scraper.py
───────────────────
Production-grade article full-text scraper.

Extraction pipeline (tried in order until one succeeds):
  1. newspaper4k  — fast, purpose-built article extractor
  2. BeautifulSoup — manual DOM traversal fallback
  3. cloudscraper  — Cloudflare / bot-detection bypass

Design principles:
  - Strict timeout on every HTTP request (never hangs the UI)
  - Randomised User-Agent rotation to avoid trivial 403 blocks
  - Content cleaning: strips ads, nav, scripts, cookie banners
  - Paywall detection — surfaces a clear signal instead of crashing
  - TTL cache: same URL never scraped twice in the same session
  - All errors are caught and returned as a ScrapeResult with ok=False

Public surface:
  scraper = ArticleScraper()
  result  = scraper.scrape(url)
  if result.ok:
      full_text = result.text
"""

from __future__ import annotations

import re
import random
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests
import cloudscraper
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings
from utils.helpers import TTLCache, clean_html, truncate_text
from utils.logger import log

# ── newspaper4k import (graceful if not installed) ────────────────────
try:
    from newspaper import Article as NewspaperArticle
    from newspaper import Config as NewspaperConfig
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False
    log.warning("newspaper4k not installed — will use BS4-only scraping.")


# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────

REQUEST_TIMEOUT: int = 12          # seconds
MIN_ARTICLE_CHARS: int = 200       # below this → consider scrape failed
MAX_CONTENT_CHARS: int = 15_000    # hard cap sent to LLM

# Patterns that suggest a paywall or login wall
PAYWALL_SIGNALS: list[str] = [
    "subscribe to read",
    "subscription required",
    "sign in to read",
    "create a free account",
    "this article is for subscribers",
    "unlock this article",
    "premium content",
    "members only",
]

# CSS selectors for junk elements to strip (ads, nav, social, etc.)
JUNK_SELECTORS: list[str] = [
    "script", "style", "noscript",
    "nav", "header", "footer", "aside",
    "figure > figcaption",              # keep figcaption only inside article
    "[class*='advertisement']",
    "[class*='ad-']", "[id*='ad-']",
    "[class*='-ad']", "[id*='-ad']",
    "[class*='ads']", "[id*='ads']",
    "[class*='sidebar']",
    "[class*='popup']", "[class*='modal']",
    "[class*='cookie']", "[class*='consent']",
    "[class*='newsletter']",
    "[class*='social']", "[class*='share']",
    "[class*='related']", "[class*='recommended']",
    "[class*='promo']", "[class*='banner']",
    "[class*='widget']",
    "[role='complementary']",
    "[role='navigation']",
    "[role='banner']",
    "[aria-label='advertisement']",
]

# Candidate selectors for the main article body (tried in priority order)
ARTICLE_BODY_SELECTORS: list[str] = [
    "article",
    "[role='main']",
    "main",
    ".article-body",
    ".article-content",
    ".article__body",
    ".post-content",
    ".post-body",
    ".entry-content",
    ".story-body",
    ".story-content",
    ".content-body",
    ".news-article",
    ".article-text",
    "#article-body",
    "#main-content",
    "#content",
    ".content",
]

# ─────────────────────────────────────────────────────────────────────
# User-Agent pool (rotated per request)
# ─────────────────────────────────────────────────────────────────────

_USER_AGENTS: list[str] = [
    # Chrome / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Chrome / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Chrome / Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _random_headers() -> dict[str, str]:
    """Returns a realistic browser-like header set with a rotated User-Agent."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }


# ─────────────────────────────────────────────────────────────────────
# Result Model
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    """
    Normalised output from any scrape attempt.
    Callers check `.ok` before using `.text`.
    """
    url: str
    ok: bool                           # True = usable content extracted
    text: str = ""                     # Cleaned article body text
    title: str = ""                    # Page title (may differ from feed title)
    authors: list[str] = field(default_factory=list)
    top_image: Optional[str] = None    # Hero image URL if found
    method: str = ""                   # Which strategy succeeded: "newspaper4k" | "bs4" | "cloudscraper+bs4"
    paywall: bool = False              # True = content locked behind paywall
    error: Optional[str] = None        # Human-readable failure reason

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def short_text(self, max_chars: int = 3000) -> str:
        """Returns text truncated to max_chars — safe to send to LLM."""
        return truncate_text(self.text, max_chars)


# ─────────────────────────────────────────────────────────────────────
# Newspaper4k Scraper
# ─────────────────────────────────────────────────────────────────────

class _Newspaper4kScraper:
    """
    Primary extraction engine using newspaper4k.
    newspaper4k handles: JS-rendered hints, author extraction,
    publish date extraction, and top-image detection automatically.
    """

    def __init__(self) -> None:
        if not NEWSPAPER_AVAILABLE:
            return
        self._config = NewspaperConfig()
        self._config.browser_user_agent = random.choice(_USER_AGENTS)
        self._config.request_timeout = REQUEST_TIMEOUT
        self._config.fetch_images = False    # faster; we already have image from GNews
        self._config.memoize_articles = False
        self._config.language = "en"

    def scrape(self, url: str) -> ScrapeResult:
        if not NEWSPAPER_AVAILABLE:
            return ScrapeResult(url=url, ok=False, error="newspaper4k not installed")
        try:
            log.debug("newspaper4k scraping: {}", url)
            # Refresh user-agent per call
            self._config.browser_user_agent = random.choice(_USER_AGENTS)
            article = NewspaperArticle(url, config=self._config)
            article.download()
            article.parse()

            text = (article.text or "").strip()
            if len(text) < MIN_ARTICLE_CHARS:
                return ScrapeResult(
                    url=url, ok=False,
                    error=f"newspaper4k: too little content ({len(text)} chars)",
                )

            cleaned = _clean_text(text)
            paywall = _detect_paywall(cleaned)

            return ScrapeResult(
                url=url,
                ok=not paywall,
                text=truncate_text(cleaned, MAX_CONTENT_CHARS),
                title=(article.title or "").strip(),
                authors=list(article.authors or []),
                top_image=article.top_image or None,
                method="newspaper4k",
                paywall=paywall,
                error="Paywall detected" if paywall else None,
            )

        except Exception as exc:
            log.warning("newspaper4k failed for {}: {}", url, exc)
            return ScrapeResult(url=url, ok=False, error=str(exc))


# ─────────────────────────────────────────────────────────────────────
# BeautifulSoup Scraper
# ─────────────────────────────────────────────────────────────────────

class _BS4Scraper:
    """
    Manual DOM-based fallback scraper.
    Strategy:
      1. Fetch HTML with requests (or cloudscraper if blocked)
      2. Remove junk elements
      3. Find main content container using priority selector list
      4. Extract and clean paragraph text
    """

    @retry(
        retry=retry_if_exception_type(requests.exceptions.Timeout),
        stop=stop_after_attempt(settings.api_max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=False,
    )
    def _fetch_html(self, url: str, use_cloudscraper: bool = False) -> str | None:
        """
        Downloads raw HTML. Returns None on unrecoverable failure.
        Tries cloudscraper if use_cloudscraper=True (handles Cloudflare).
        """
        try:
            if use_cloudscraper:
                log.debug("cloudscraper fetching: {}", url)
                scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                resp = scraper.get(url, headers=_random_headers(), timeout=REQUEST_TIMEOUT)
            else:
                log.debug("requests fetching: {}", url)
                resp = requests.get(
                    url,
                    headers=_random_headers(),
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )

            if resp.status_code == 403:
                log.warning("HTTP 403 for {} — site is blocking requests", url)
                return None
            if resp.status_code == 429:
                log.warning("HTTP 429 for {} — rate limited", url)
                return None
            resp.raise_for_status()
            return resp.text

        except requests.exceptions.Timeout:
            log.warning("Request timed out for {}", url)
            raise   # let tenacity retry
        except requests.exceptions.SSLError as exc:
            log.warning("SSL error for {}: {}", url, exc)
            return None
        except Exception as exc:
            log.warning("HTTP fetch failed for {}: {}", url, exc)
            return None

    def _parse_html(self, html: str, url: str, method_label: str) -> ScrapeResult:
        """Parses raw HTML → ScrapeResult using BS4 + junk removal."""
        try:
            soup = BeautifulSoup(html, "lxml")

            # ── Strip junk ──────────────────────────────────────────
            for selector in JUNK_SELECTORS:
                for tag in soup.select(selector):
                    tag.decompose()

            # ── Extract title ────────────────────────────────────────
            title = ""
            if soup.title:
                title = soup.title.get_text(strip=True)
            elif soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)

            # ── Find main content area ───────────────────────────────
            content_tag = None
            for selector in ARTICLE_BODY_SELECTORS:
                candidate = soup.select_one(selector)
                if candidate:
                    paragraphs = candidate.find_all("p")
                    combined = " ".join(p.get_text() for p in paragraphs)
                    if len(combined) >= MIN_ARTICLE_CHARS:
                        content_tag = candidate
                        break

            # ── Fallback: grab all <p> tags from body ────────────────
            if not content_tag:
                content_tag = soup.find("body") or soup

            # ── Extract paragraph text ───────────────────────────────
            paragraphs = content_tag.find_all("p")
            raw_text = "\n\n".join(
                p.get_text(separator=" ", strip=True)
                for p in paragraphs
                if len(p.get_text(strip=True)) > 40   # skip nav/footer snippets
            )

            cleaned = _clean_text(raw_text)

            if len(cleaned) < MIN_ARTICLE_CHARS:
                return ScrapeResult(
                    url=url, ok=False,
                    error=f"BS4: insufficient content after cleaning ({len(cleaned)} chars)",
                )

            paywall = _detect_paywall(cleaned)

            # ── Try to find top image ────────────────────────────────
            top_image: Optional[str] = None
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                top_image = og_image["content"]

            return ScrapeResult(
                url=url,
                ok=not paywall,
                text=truncate_text(cleaned, MAX_CONTENT_CHARS),
                title=title,
                top_image=top_image,
                method=method_label,
                paywall=paywall,
                error="Paywall detected" if paywall else None,
            )

        except Exception as exc:
            log.error("BS4 parse error for {}: {}", url, exc)
            return ScrapeResult(url=url, ok=False, error=f"BS4 parse error: {exc}")

    def scrape(self, url: str) -> ScrapeResult:
        """Standard requests + BS4 scrape."""
        html = self._fetch_html(url, use_cloudscraper=False)
        if not html:
            return ScrapeResult(url=url, ok=False, error="BS4: HTTP fetch returned no content")
        return self._parse_html(html, url, method_label="bs4")

    def scrape_with_cloudscraper(self, url: str) -> ScrapeResult:
        """cloudscraper (Cloudflare bypass) + BS4 scrape."""
        html = self._fetch_html(url, use_cloudscraper=True)
        if not html:
            return ScrapeResult(url=url, ok=False, error="cloudscraper: HTTP fetch returned no content")
        return self._parse_html(html, url, method_label="cloudscraper+bs4")


# ─────────────────────────────────────────────────────────────────────
# Text Cleaning Utilities
# ─────────────────────────────────────────────────────────────────────

_WHITESPACE_RE = re.compile(r"\n{3,}")          # 3+ blank lines → 2
_REPEATED_DOTS = re.compile(r"\.{4,}")          # "....." → "..."
_TRACKING_PARAMS = re.compile(r"\?utm_[^\s]+")  # strip UTM params from text


def _clean_text(raw: str) -> str:
    """
    Post-processes extracted text:
    - Normalises whitespace and blank lines
    - Removes common boilerplate phrases
    - Strips leftover HTML entities
    """
    if not raw:
        return ""

    # HTML entity cleanup (belt-and-suspenders after BS4)
    text = (
        raw
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("\xa0", " ")       # non-breaking space
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )

    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse 3+ consecutive blank lines to 2
    text = _WHITESPACE_RE.sub("\n\n", text)

    # Remove common boilerplate fragments
    boilerplate = [
        "javascript is disabled",
        "enable javascript",
        "please enable cookies",
        "read more at",
        "click here to read more",
        "advertisement",
        "this article originally appeared",
        "all rights reserved",
        "terms of service",
        "privacy policy",
    ]
    text_lower = text.lower()
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        line_lower = line.lower().strip()
        if any(bp in line_lower for bp in boilerplate):
            continue
        if len(line.strip()) < 5:   # lone punctuation / stray characters
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _detect_paywall(text: str) -> bool:
    """
    Returns True if the extracted text suggests a paywall / login wall.
    Checks the first 800 characters (paywall gates appear early).
    """
    sample = text[:800].lower()
    return any(signal in sample for signal in PAYWALL_SIGNALS)


def _is_blocked(url: str, html: str | None) -> bool:
    """
    Heuristic: returns True if the response looks like a bot-block page.
    """
    if not html:
        return True
    lower = html[:2000].lower()
    block_phrases = [
        "access denied",
        "403 forbidden",
        "cloudflare",
        "are you human",
        "please verify",
        "ddos protection",
        "browser check",
        "captcha",
    ]
    return any(p in lower for p in block_phrases)


# ─────────────────────────────────────────────────────────────────────
# ArticleScraper — Public Orchestrator
# ─────────────────────────────────────────────────────────────────────

class ArticleScraper:
    """
    Orchestrates the three-stage scraping pipeline.

    Stage 1 → newspaper4k         (best quality, handles most sites)
    Stage 2 → requests + BS4      (manual DOM, more control over cleaning)
    Stage 3 → cloudscraper + BS4  (bypasses Cloudflare / bot detection)

    Results are TTL-cached per URL to avoid redundant scrapes.

    Usage:
        scraper = ArticleScraper()
        result  = scraper.scrape("https://techcrunch.com/...")
        if result.ok:
            print(result.text)
        elif result.paywall:
            print("Article is paywalled")
    """

    def __init__(self) -> None:
        self._np4k    = _Newspaper4kScraper()
        self._bs4     = _BS4Scraper()
        self._cache   = TTLCache(ttl_seconds=settings.cache_ttl_seconds)
        log.info(
            "ArticleScraper ready | newspaper4k={} | BS4=✓ | cloudscraper=✓",
            "✓" if NEWSPAPER_AVAILABLE else "✗ (not installed)",
        )

    def scrape(self, url: str, force_refresh: bool = False) -> ScrapeResult:
        """
        Scrapes a single article URL through the 3-stage pipeline.
        Returns on first successful result.
        """
        if not url or not url.startswith("http"):
            return ScrapeResult(url=url, ok=False, error="Invalid URL")

        # ── Cache lookup ──────────────────────────────────────────────
        cache_key = f"scrape:{url}"
        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Scrape cache hit: {}", _short_url(url))
                return cached

        log.info("Scraping: {}", _short_url(url))

        # ── Stage 1: newspaper4k ──────────────────────────────────────
        result = self._np4k.scrape(url)
        if result.ok:
            log.info("✓ newspaper4k succeeded | {} words | {}", result.word_count, _short_url(url))
            self._cache.set(cache_key, result)
            return result

        # Don't go further if it's a paywall — no scraper will bypass it
        if result.paywall:
            log.warning("Paywall detected at {} — skipping further attempts", _short_url(url))
            self._cache.set(cache_key, result)
            return result

        log.debug("newspaper4k failed ({}), trying BS4…", result.error)

        # ── Stage 2: requests + BS4 ───────────────────────────────────
        result = self._bs4.scrape(url)
        if result.ok:
            log.info("✓ BS4 succeeded | {} words | {}", result.word_count, _short_url(url))
            self._cache.set(cache_key, result)
            return result

        log.debug("BS4 failed ({}), trying cloudscraper…", result.error)

        # ── Stage 3: cloudscraper + BS4 ───────────────────────────────
        result = self._bs4.scrape_with_cloudscraper(url)
        if result.ok:
            log.info("✓ cloudscraper+BS4 succeeded | {} words | {}", result.word_count, _short_url(url))
        else:
            log.warning("✗ All scraping stages failed for {}: {}", _short_url(url), result.error)

        self._cache.set(cache_key, result)
        return result

    def scrape_batch(
        self,
        urls: list[str],
        max_workers: int = 4,
    ) -> dict[str, ScrapeResult]:
        """
        Scrapes multiple URLs sequentially with a concurrency cap.
        Returns a dict of {url: ScrapeResult}.
        Uses ThreadPoolExecutor for lightweight I/O concurrency.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: dict[str, ScrapeResult] = {}
        log.info("Batch scraping {} URLs (max_workers={})", len(urls), max_workers)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(self.scrape, url): url for url in urls}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as exc:
                    log.error("Batch scrape exception for {}: {}", _short_url(url), exc)
                    results[url] = ScrapeResult(url=url, ok=False, error=str(exc))

        ok_count = sum(1 for r in results.values() if r.ok)
        log.info(
            "Batch complete: {}/{} succeeded",
            ok_count,
            len(urls),
        )
        return results

    def enrich_article(self, article_dict: dict) -> dict:
        """
        Convenience wrapper: scrapes an article dict (from news_fetcher)
        and injects `scraped_text` and `top_image` back into the dict.
        Does NOT mutate the input — returns a new dict.
        """
        url = article_dict.get("url", "")
        result = self.scrape(url)
        return {
            **article_dict,
            "scraped_text": result.text if result.ok else "",
            "scrape_ok": result.ok,
            "scrape_method": result.method,
            "paywall": result.paywall,
            # Prefer GNews image; fall back to scraped hero image
            "image_url": article_dict.get("image_url") or result.top_image,
        }

    def invalidate(self, url: str) -> None:
        """Remove a single URL from the scrape cache."""
        self._cache.invalidate(f"scrape:{url}")

    def clear_cache(self) -> None:
        """Flush the entire scrape cache."""
        self._cache.clear()


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _short_url(url: str, max_len: int = 60) -> str:
    """Returns a shortened URL for readable log lines."""
    parsed = urlparse(url)
    short = f"{parsed.netloc}{parsed.path}"
    return short[:max_len] + "…" if len(short) > max_len else short
