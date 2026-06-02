"""
config/settings.py
──────────────────
Central configuration for the AI News Agent.
All constants, defaults, and environment variable loading live here.
Import this module anywhere in the project via:
    from config.settings import settings
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env file (works locally; on Streamlit Cloud use Secrets) ──
load_dotenv()

# ── Project root (two levels up from this file) ─────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)  # ensure data/ folder exists


# ── GNews API ────────────────────────────────────────────────────────
GNEWS_BASE_URL: str = "https://gnews.io/api/v4"

# Maps our friendly topic names → GNews category slugs
# GNews valid categories: general | world | nation | business |
#   technology | entertainment | sports | science | health
GNEWS_CATEGORY_MAP: dict[str, str] = {
    "Artificial Intelligence": "technology",
    "Technology":              "technology",
    "Business & Finance":      "business",
    "Science":                 "science",
    "Health":                  "health",
    "Politics":                "nation",
    "Sports":                  "sports",
    "Climate & Environment":   "science",
    "Entertainment":           "entertainment",
    "World":                   "world",
    "General":                 "general",
}

# ── RSS Feed Sources (no API key needed) ─────────────────────────────
RSS_FEEDS: dict[str, str] = {
    # General
    "BBC News":          "http://feeds.bbci.co.uk/news/rss.xml",
    "Reuters":           "https://feeds.reuters.com/reuters/topNews",

    # Technology & AI
    "TechCrunch":        "https://techcrunch.com/feed/",
    "Wired":             "https://www.wired.com/feed/rss",
    "Ars Technica":      "https://feeds.arstechnica.com/arstechnica/index",
    "The Verge":         "https://www.theverge.com/rss/index.xml",
    "NASA":              "https://www.nasa.gov/rss/dyn/breaking_news.rss",
    "MIT Tech Review":   "https://www.technologyreview.com/feed/",

    # Sports
    "BBC Sport":         "http://feeds.bbci.co.uk/sport/rss.xml",
    "ESPN Cricket":      "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
    "Sky Sports":        "https://www.skysports.com/rss/12040",

    # Finance & Business
    "Economic Times":    "https://economictimes.indiatimes.com/rssfeedsdefault.cms",
    "Moneycontrol":      "https://www.moneycontrol.com/rss/MCtopnews.xml",

    # India & World
    "Al Jazeera":        "https://www.aljazeera.com/xml/rss/all.xml",
    "The Hindu":         "https://www.thehindu.com/feeder/default.rss",

    # Entertainment
    "Entertainment Weekly": "https://feeds.feedburner.com/ew/news",
}

# ── UI-facing topic list ──────────────────────────────────────────────
TOPICS: list[str] = list(GNEWS_CATEGORY_MAP.keys())

# ── Sentiment labels ──────────────────────────────────────────────────
SENTIMENT_LABELS: list[str] = ["Positive", "Neutral", "Negative"]


@dataclass
class Settings:
    """
    Typed settings object — all values fall back to safe defaults
    so the app never crashes on a missing env var.
    """

    # ── API Keys ─────────────────────────────────────────────────────
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    gnews_api_key: str = field(
        default_factory=lambda: os.getenv("GNEWS_API_KEY", "")
    )

    # ── Gemini Model ──────────────────────────────────────────────────
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    )

    # ── Fetch limits ──────────────────────────────────────────────────
    max_articles_per_topic: int = field(
        default_factory=lambda: int(os.getenv("MAX_ARTICLES_PER_TOPIC", "10"))
    )

    # ── Database ──────────────────────────────────────────────────────
    db_path: Path = field(
        default_factory=lambda: ROOT_DIR / os.getenv("DB_PATH", "data/news_agent.db")
    )

    # ── Logging ───────────────────────────────────────────────────────
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    # ── Summarization ─────────────────────────────────────────────────
    # Max characters of article text to send to Gemini per request
    max_input_chars: int = 12_000          # ~3 000 tokens — stays well within context window
    # Target summary length (words) for the standard mode
    summary_max_words: int = 80
    # Gemini generation parameters
    gemini_temperature: float = 0.3        # Low = factual, consistent output
    gemini_max_output_tokens: int = 512    # Enough for all 4 summary modes
    # Rate limiting — Gemini free tier: 15 RPM
    gemini_rpm_limit: int = 15             # Requests Per Minute ceiling
    batch_request_delay_s: float = 4.5    # Min seconds between batch API calls

    # ── UI Defaults ───────────────────────────────────────────────────
    default_topics: list[str] = field(
        default_factory=lambda: ["Artificial Intelligence", "Technology"]
    )
    articles_per_page: int = 12

    # ── Retry policy (for API calls) ──────────────────────────────────
    api_max_retries: int = 3
    api_retry_wait_seconds: int = 2

    # ── Cache ─────────────────────────────────────────────────────────
    # How long (seconds) to keep fetched articles in memory cache
    cache_ttl_seconds: int = 300  # 5 minutes

    def validate(self) -> list[str]:
        """
        Returns a list of warning strings for any missing critical config.
        Call this at app startup and surface warnings in the UI.
        """
        warnings: list[str] = []
        if not self.gemini_api_key:
            warnings.append("⚠️  GEMINI_API_KEY is not set. Summarization will be disabled.")
        if not self.gnews_api_key:
            warnings.append("⚠️  GNEWS_API_KEY is not set. Only RSS feeds will be available.")
        return warnings


# ── Singleton instance — import this everywhere ───────────────────────
settings = Settings()
