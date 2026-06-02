"""
services/news_fetcher.py
────────────────────────
Production-ready news fetching service.

Two data sources:
  1. GNews API  — category headlines + keyword search
  2. RSS Feeds  — always-on fallback, no API key required

Design principles:
  - Normalised Article dataclass as the single output contract
  - TTL in-memory cache (5 min default) to avoid hammering APIs
  - Tenacity retry logic for transient HTTP failures
  - Graceful degradation: GNews failure → RSS only, never a crash
  - URL-based deduplication across sources

Public surface:
  fetcher = NewsFetcher()
  articles = fetcher.get_by_category("technology")
  articles = fetcher.search("OpenAI GPT-5")
  articles = fetcher.get_top_headlines()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from config.settings import settings, GNEWS_BASE_URL, GNEWS_CATEGORY_MAP, RSS_FEEDS
from utils.helpers import (
    TTLCache,
    clean_html,
    deduplicate_articles,
    parse_date,
    truncate_text,
    url_hash,
)
from utils.logger import log

import logging
_std_log = logging.getLogger(__name__)   # for tenacity's before_sleep_log


# ─────────────────────────────────────────────────────────────────────
# Normalised Article Model
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Article:
    """
    Canonical article object.
    All fetchers (GNews, RSS) must produce this shape.
    """
    id: str                          # MD5 of URL — stable unique key
    title: str
    description: str                 # short blurb / lead paragraph
    content: str                     # full body text (may be truncated by API)
    url: str
    image_url: Optional[str]
    source_name: str
    published_at: Optional[datetime]
    category: str                    # GNews category slug (e.g. "technology")
    topic_label: str                 # Human-friendly label (e.g. "Technology")

    # Enrichment fields — filled later by the summariser/categoriser
    summary: Optional[str] = None
    sentiment: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise to plain dict for SQLite / Streamlit display."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "url": self.url,
            "image_url": self.image_url,
            "source_name": self.source_name,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "category": self.category,
            "topic_label": self.topic_label,
            "summary": self.summary,
            "sentiment": self.sentiment,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        """Deserialise from dict (e.g. loaded from SQLite)."""
        dt = None
        if data.get("published_at"):
            dt = parse_date(data["published_at"])
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            content=data.get("content", ""),
            url=data.get("url", ""),
            image_url=data.get("image_url"),
            source_name=data.get("source_name", "Unknown"),
            published_at=dt,
            category=data.get("category", "general"),
            topic_label=data.get("topic_label", "General"),
            summary=data.get("summary"),
            sentiment=data.get("sentiment"),
            tags=data.get("tags", []),
        )


# ─────────────────────────────────────────────────────────────────────
# GNews API Client
# ─────────────────────────────────────────────────────────────────────

class GNewsClient:
    """
    Thin wrapper around the GNews v4 REST API.
    Uses httpx for sync HTTP with connection pooling.
    Retries on 429 (rate-limit) and 5xx errors.
    """

    def __init__(self) -> None:
        # Read key fresh from environment at construction time so that
        # Streamlit @st.cache_resource ordering issues don't bite us.
        # os.environ is always correct by the time app.py calls load_dotenv.
        import os as _os
        self._api_key = (
            _os.environ.get("GNEWS_API_KEY")
            or settings.gnews_api_key
            or ""
        )
        self._base = GNEWS_BASE_URL
        self._client = httpx.Client(
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"User-Agent": "AINewsAgent/1.0"},
        )

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _common_params(self, max_articles: int) -> dict:
        return {
            "apikey": self._api_key,
            "lang": "en",
            "max": min(max_articles, 10),   # free tier hard cap
        }

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        stop=stop_after_attempt(settings.api_max_retries),
        wait=wait_exponential(
            multiplier=settings.api_retry_wait_seconds, min=1, max=16
        ),
        before_sleep=before_sleep_log(_std_log, logging.WARNING),
        reraise=False,
    )
    def _get(self, endpoint: str, params: dict) -> dict | None:
        """
        Core HTTP GET with retry.
        Returns parsed JSON dict or None on unrecoverable failure.
        """
        try:
            url = f"{self._base}/{endpoint}"
            log.debug("GNews GET {} params={}", endpoint, {k: v for k, v in params.items() if k != "apikey"})
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 403:
                log.error("GNews API key invalid or quota exceeded (403). Check GNEWS_API_KEY.")
                return None       # don't retry auth failures
            if code == 429:
                log.warning("GNews rate-limited (429). Will retry…")
                raise             # let tenacity retry
            log.error("GNews HTTP error {}: {}", code, exc.response.text[:200])
            return None
        except httpx.TimeoutException:
            log.warning("GNews request timed out. Retrying…")
            raise
        except Exception as exc:
            log.error("Unexpected GNews error: {}", exc)
            return None

    def fetch_top_headlines(
        self, category: str = "general", max_articles: int = 10
    ) -> list[dict]:
        """Fetch top headlines for a GNews category slug."""
        if not self.available:
            log.warning("GNews unavailable — no API key set.")
            return []
        params = {**self._common_params(max_articles), "category": category}
        data = self._get("top-headlines", params)
        return data.get("articles", []) if data else []

    def search(self, query: str, max_articles: int = 10) -> list[dict]:
        """Full-text keyword search across GNews."""
        if not self.available:
            log.warning("GNews unavailable — no API key set.")
            return []
        params = {**self._common_params(max_articles), "q": query, "in": "title,description"}
        data = self._get("search", params)
        return data.get("articles", []) if data else []

    def close(self) -> None:
        self._client.close()


# ─────────────────────────────────────────────────────────────────────
# RSS Feed Client
# ─────────────────────────────────────────────────────────────────────

class RSSClient:
    """
    Fetches and parses RSS / Atom feeds using feedparser.
    Always available — no API key required.
    Falls back gracefully if a feed URL is unreachable.
    """

    @staticmethod
    def fetch(feed_name: str, feed_url: str, max_articles: int = 10) -> list[dict]:
        """
        Returns raw article dicts in the same shape as GNews articles
        so they can be normalised by the same function.
        """
        try:
            log.debug("RSS fetch: {} ({})", feed_name, feed_url)
            parsed = feedparser.parse(feed_url)

            if parsed.bozo and not parsed.entries:
                log.warning("RSS parse warning for {}: {}", feed_name, parsed.bozo_exception)
                return []

            articles = []
            for entry in parsed.entries[:max_articles]:
                # Extract the best available image
                image_url = None
                if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get("url")
                elif hasattr(entry, "media_content") and entry.media_content:
                    image_url = entry.media_content[0].get("url")

                raw_content = getattr(entry, "summary", "") or getattr(entry, "description", "")
                articles.append({
                    "title":       getattr(entry, "title", "Untitled"),
                    "description": clean_html(raw_content),
                    "content":     clean_html(raw_content),
                    "url":         getattr(entry, "link", ""),
                    "image":       {"url": image_url} if image_url else None,
                    "source":      {"name": feed_name},
                    "publishedAt": getattr(entry, "published", None)
                                   or getattr(entry, "updated", None),
                })
            log.debug("RSS {}: {} articles fetched", feed_name, len(articles))
            return articles

        except Exception as exc:
            log.error("RSS fetch failed for {} ({}): {}", feed_name, feed_url, exc)
            return []

    @staticmethod
    def fetch_all(max_per_feed: int = 5) -> list[dict]:
        """Fetch from all configured RSS feeds concurrently (sequential fallback)."""
        all_raw: list[dict] = []
        for name, url in RSS_FEEDS.items():
            all_raw.extend(RSSClient.fetch(name, url, max_per_feed))
        return all_raw


# ─────────────────────────────────────────────────────────────────────
# Normaliser — GNews / RSS → Article
# ─────────────────────────────────────────────────────────────────────

def _normalise(
    raw: dict,
    category_slug: str = "general",
    topic_label: str = "General",
) -> Article | None:
    """
    Converts a raw GNews or RSS dict into a typed Article.
    Returns None if the article has no URL (unusable).
    """
    url = raw.get("url") or raw.get("link", "")
    if not url:
        return None

    title = raw.get("title", "Untitled").strip()
    description = truncate_text(clean_html(raw.get("description", "")), 400)
    content = truncate_text(clean_html(raw.get("content", description)), 2000)

    # GNews wraps image as {"url": "..."}, RSS may already be normalised
    image_url: Optional[str] = None
    img = raw.get("image")
    if isinstance(img, dict):
        image_url = img.get("url")
    elif isinstance(img, str):
        image_url = img

    # Source name: GNews → {"name": "..."}, RSS already normalised
    source = raw.get("source", {})
    source_name = (
        source.get("name", "Unknown") if isinstance(source, dict) else str(source)
    )

    published_at = parse_date(raw.get("publishedAt") or raw.get("published_at"))

    return Article(
        id=url_hash(url),
        title=title,
        description=description,
        content=content,
        url=url,
        image_url=image_url,
        source_name=source_name,
        published_at=published_at,
        category=category_slug,
        topic_label=topic_label,
    )


# ─────────────────────────────────────────────────────────────────────
# NewsFetcher — Public Orchestrator
# ─────────────────────────────────────────────────────────────────────

class NewsFetcher:
    """
    High-level orchestrator.
    Combines GNews + RSS, deduplicates, caches, and returns Article objects.

    Usage:
        fetcher = NewsFetcher()
        articles = fetcher.get_by_category("Technology")
        articles = fetcher.search("Large Language Models")
        articles = fetcher.get_top_headlines()
    """

    def __init__(self) -> None:
        self._gnews = GNewsClient()
        self._rss = RSSClient()
        self._cache = TTLCache(ttl_seconds=settings.cache_ttl_seconds)
        log.info(
            "NewsFetcher ready | GNews available={} | RSS feeds={}",
            self._gnews.available,
            len(RSS_FEEDS),
        )

    # ── Public API ────────────────────────────────────────────────────

    def get_by_category(
        self,
        topic_label: str,
        max_articles: int | None = None,
        force_refresh: bool = False,
    ) -> list[Article]:
        """
        Fetch articles for a human-friendly topic label (e.g. "Technology").
        Uses GNews category endpoint + optional keyword search supplement
        + category-relevant RSS feeds.
        Results are cached for settings.cache_ttl_seconds.
        """
        max_articles = max_articles or settings.max_articles_per_topic
        cache_key = f"category:{topic_label}:{max_articles}"

        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Cache hit for category '{}'", topic_label)
                return cached

        category_slug = GNEWS_CATEGORY_MAP.get(topic_label, "general")
        raw_articles: list[dict] = []

        # ── GNews category endpoint ───────────────────────────────────
        gnews_raw = self._gnews.fetch_top_headlines(category_slug, max_articles)
        log.info("GNews category '{}' → {} raw articles", category_slug, len(gnews_raw))
        raw_articles.extend(gnews_raw)

        # ── GNews keyword search supplement ───────────────────────────
        # For specific topics, also run a targeted keyword search so we
        # get fresh, relevant results beyond what the category endpoint returns.
        _supplement_queries: dict[str, str] = {
            "Sports":         "latest sports news today",
            "Politics":       "politics government latest news",
            "Entertainment":  "entertainment movies celebrity news",
            "World":          "world news international today",
            "Health":         "health medical news today",
            "Science":        "science discovery research news",
            "Finance":        "finance economy market news",
            "Business & Finance": "business economy market news",
        }
        supplement_q = _supplement_queries.get(topic_label)
        if supplement_q:
            extra = self._gnews.search(supplement_q, max_articles // 2 or 5)
            log.debug("GNews supplement search '{}' → {} articles", supplement_q, len(extra))
            raw_articles.extend(extra)

        # ── Category-specific RSS feeds ───────────────────────────────
        rss_feeds_to_use = self._select_rss_feeds(topic_label)
        for name, url in rss_feeds_to_use.items():
            rss_raw = self._rss.fetch(name, url, max_articles=6)
            raw_articles.extend(rss_raw)

        articles = self._process(raw_articles, category_slug, topic_label, max_articles)
        self._cache.set(cache_key, articles)
        return articles

    def search(
        self,
        query: str,
        max_articles: int | None = None,
        force_refresh: bool = False,
    ) -> list[Article]:
        """
        Search for articles by keyword/phrase.
        Falls back to RSS content filtering if GNews is unavailable.
        """
        max_articles = max_articles or settings.max_articles_per_topic
        cache_key = f"search:{query.lower().strip()}:{max_articles}"

        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Cache hit for search '{}'", query)
                return cached

        raw_articles: list[dict] = []

        # ── GNews search ──────────────────────────────────────────────
        gnews_raw = self._gnews.search(query, max_articles)
        log.info("GNews search '{}' → {} raw articles", query, len(gnews_raw))
        raw_articles.extend(gnews_raw)

        # ── RSS keyword filter (always runs) ──────────────────────────
        rss_matches = self._rss_keyword_search(query, max_articles)
        raw_articles.extend(rss_matches)

        articles = self._process(raw_articles, "general", "Search Results", max_articles)
        self._cache.set(cache_key, articles)
        return articles

    def get_top_headlines(
        self,
        max_articles: int | None = None,
        force_refresh: bool = False,
    ) -> list[Article]:
        """
        Fetch general top headlines — a quick overview across all categories.
        """
        max_articles = max_articles or settings.max_articles_per_topic
        cache_key = f"headlines:{max_articles}"

        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.debug("Cache hit for top headlines")
                return cached

        raw_articles: list[dict] = []

        gnews_raw = self._gnews.fetch_top_headlines("general", max_articles)
        raw_articles.extend(gnews_raw)

        # Always supplement with a couple of RSS feeds
        for name, url in list(RSS_FEEDS.items())[:3]:
            raw_articles.extend(self._rss.fetch(name, url, max_articles=4))

        articles = self._process(raw_articles, "general", "Top Headlines", max_articles)
        self._cache.set(cache_key, articles)
        return articles

    def invalidate_cache(self) -> None:
        """Force-clear all cached results."""
        self._cache.clear()
        log.info("News cache cleared.")

    # ── Internal helpers ──────────────────────────────────────────────

    def _process(
        self,
        raw_articles: list[dict],
        category_slug: str,
        topic_label: str,
        max_articles: int,
    ) -> list[Article]:
        """
        Deduplicate → Normalise → Sort by date → Trim to limit.
        """
        deduped = deduplicate_articles(raw_articles)
        articles: list[Article] = []
        for raw in deduped:
            article = _normalise(raw, category_slug, topic_label)
            if article:
                articles.append(article)

        # Sort newest-first; articles with no date go to the end
        articles.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        log.info(
            "Processed {} unique articles for '{}'",
            len(articles[:max_articles]),
            topic_label,
        )
        return articles[:max_articles]

    def _select_rss_feeds(self, topic_label: str) -> dict[str, str]:
        """
        Returns RSS feeds most relevant to the chosen topic.
        Each category gets the feeds most likely to carry matching news.
        """
        tech = {"Artificial Intelligence", "Technology", "Science"}
        sports = {"Sports", "Cricket"}
        finance = {"Finance", "Stocks", "Startups", "Business & Finance"}
        world = {"World", "India", "Politics"}
        entertainment = {"Entertainment"}

        if topic_label in tech:
            return {k: v for k, v in RSS_FEEDS.items()
                    if k in ("TechCrunch", "Wired", "Ars Technica", "The Verge", "MIT Tech Review")}
        if topic_label in sports:
            return {k: v for k, v in RSS_FEEDS.items()
                    if k in ("BBC News", "ESPN Cricket", "Sky Sports", "BBC Sport")}
        if topic_label in finance:
            return {k: v for k, v in RSS_FEEDS.items()
                    if k in ("Reuters", "BBC News", "Economic Times", "Moneycontrol")}
        if topic_label in world:
            return {k: v for k, v in RSS_FEEDS.items()
                    if k in ("BBC News", "Reuters", "Al Jazeera", "The Hindu")}
        if topic_label in entertainment:
            return {k: v for k, v in RSS_FEEDS.items()
                    if k in ("BBC News", "Entertainment Weekly")}
        # fallback: general feeds
        return {k: v for k, v in RSS_FEEDS.items()
                if k in ("BBC News", "Reuters")}

    def _rss_keyword_search(self, query: str, max_results: int = 10) -> list[dict]:
        """
        Fetches all RSS feeds and returns entries matching ANY word in the
        query (word-level, case-insensitive).  Short words (<4 chars) are
        skipped to avoid false positives on 'the', 'and', etc.
        """
        # Split query into meaningful keywords
        keywords = [
            w.lower() for w in query.replace(",", " ").split()
            if len(w) >= 4
        ]
        if not keywords:
            keywords = [query.lower().strip()]

        all_raw = self._rss.fetch_all(max_per_feed=20)
        matches = []
        for r in all_raw:
            text = (r.get("title", "") + " " + r.get("description", "")).lower()
            if any(kw in text for kw in keywords):
                matches.append(r)

        log.debug(
            "RSS keyword search '{}' (keywords={}) → {} matches",
            query, keywords[:5], len(matches)
        )
        return matches[:max_results]

    def __del__(self) -> None:
        try:
            self._gnews.close()
        except Exception:
            pass
