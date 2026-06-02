"""
utils/helpers.py
────────────────
Common utility functions used across the project.
Covers: date parsing, text truncation, URL deduplication,
        token estimation, and simple TTL cache.
"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Any
from dateutil import parser as dateutil_parser


# ─────────────────────────────────────────────────────────────────────
# Date / Time
# ─────────────────────────────────────────────────────────────────────

def parse_date(raw: str | None) -> datetime | None:
    """
    Robustly parse an ISO-8601, RFC-2822, or free-text date string.
    Returns a timezone-aware UTC datetime, or None on failure.
    """
    if not raw:
        return None
    try:
        dt = dateutil_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def format_relative_time(dt: datetime | None) -> str:
    """
    Returns a human-friendly relative time string.
    e.g. "3 hours ago", "just now", "2 days ago"
    """
    if dt is None:
        return "Unknown date"

    now = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta_seconds = int((now - dt).total_seconds())

    if delta_seconds < 60:
        return "just now"
    if delta_seconds < 3600:
        mins = delta_seconds // 60
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if delta_seconds < 86400:
        hours = delta_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = delta_seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def format_timestamp(dt: datetime | None, fmt: str = "%b %d, %Y %H:%M UTC") -> str:
    """Formats a datetime to a readable string."""
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime(fmt)


# ─────────────────────────────────────────────────────────────────────
# Text
# ─────────────────────────────────────────────────────────────────────

def truncate_text(text: str | None, max_chars: int = 500) -> str:
    """
    Truncates text to max_chars, appending '…' if cut.
    Safe against None inputs.
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def estimate_tokens(text: str) -> int:
    """
    Fast token count estimate without loading a tokeniser.
    Approximation: 1 token ≈ 4 characters (works well for English).
    """
    return len(text) // 4


def clean_html(text: str | None) -> str:
    """
    Strips basic HTML tags from a string using a simple approach
    (no external dependency). Good enough for RSS descriptions.
    """
    import re
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────
# URL / Deduplication
# ─────────────────────────────────────────────────────────────────────

def url_hash(url: str) -> str:
    """Returns a short MD5 hex digest of a URL — used as a unique article ID."""
    return hashlib.md5(url.encode()).hexdigest()


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """
    Removes duplicate articles based on URL hash.
    Preserves the first occurrence, discards later duplicates.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for article in articles:
        url = article.get("url", "")
        h = url_hash(url)
        if h not in seen and url:
            seen.add(h)
            unique.append(article)
    return unique


# ─────────────────────────────────────────────────────────────────────
# TTL In-Memory Cache
# ─────────────────────────────────────────────────────────────────────

class TTLCache:
    """
    Simple dict-based cache with per-entry TTL (time-to-live).

    Usage:
        cache = TTLCache(ttl_seconds=300)
        cache.set("key", value)
        result = cache.get("key")   # None if expired or missing
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        """Returns cached value or None if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Stores a value with an expiry timestamp."""
        self._store[key] = (value, time.monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        """Manually remove a key."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Flush the entire cache."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
