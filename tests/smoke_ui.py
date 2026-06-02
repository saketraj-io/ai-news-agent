"""
Smoke test for UI module imports — runs outside Streamlit context.
Verifies all Python-level imports and HTML generators work correctly.
"""
import sys
sys.path.insert(0, r"c:\Users\sksak\OneDrive\Desktop\ai_news_agent")

# ── 1. styles.py ────────────────────────────────────────────────────
from ui.styles import (
    TOPIC_GRADIENTS, TOPIC_ICONS, SENTIMENT_CONFIG, SUMMARY_MODE_LABELS
)
assert "Artificial Intelligence" in TOPIC_ICONS
assert "Positive" in SENTIMENT_CONFIG
assert SENTIMENT_CONFIG["Positive"]["cls"] == "badge-positive"
assert len(TOPIC_GRADIENTS) >= 10
print("[OK] ui.styles")

# ── 2. components.py (HTML generators only — no st.*) ────────────────
from ui.components import (
    sentiment_badge_html,
    tags_html,
    article_card_html,
    compact_card_html,
    breaking_ticker_html,
    skeleton_card_html,
    empty_state_html,
    search_results_header_html,
    history_row_html,
    api_status_html,
    section_header_html,
    _time_ago,
)
print("[OK] ui.components imports")

# Sentiment badge
b = sentiment_badge_html("Positive")
assert "badge-positive" in b and "🟢" in b
b2 = sentiment_badge_html("Negative")
assert "badge-negative" in b2
b3 = sentiment_badge_html(None)
assert b3 == ""
print("[OK] sentiment_badge_html")

# Tags
t = tags_html(["ai", "tech", "openai"])
assert "#ai" in t and "tag-pill" in t
assert tags_html([]) == ""
print("[OK] tags_html")

# Article card
article = {
    "id": "abc123",
    "title": "OpenAI releases GPT-5 with reasoning capabilities",
    "description": "OpenAI announced a major breakthrough in AI reasoning.",
    "url": "https://example.com/gpt5",
    "image_url": "https://example.com/img.jpg",
    "source_name": "TechCrunch",
    "published_at": "2026-05-27T10:00:00+00:00",
    "topic_label": "Artificial Intelligence",
    "category": "technology",
    "sentiment": "Positive",
    "tags": ["openai", "gpt", "ai"],
    "content": "Full article text here...",
}
card = article_card_html(article)
assert "a-card" in card
assert "OpenAI releases" in card
assert "TechCrunch" in card
assert "a-cat" in card
print("[OK] article_card_html")

# Article card with no image (gradient fallback)
article_no_img = dict(article, image_url=None)
card2 = article_card_html(article_no_img)
assert "a-img-fallback" in card2
assert "linear-gradient" in card2
print("[OK] article_card_html (no image fallback)")

# Compact card
cc = compact_card_html(article, 1)
assert "cc-wrap" in cc and "01" in cc
print("[OK] compact_card_html")

# Breaking ticker
ticker = breaking_ticker_html([article] * 5)
assert "ticker-wrap" in ticker
assert "BREAKING" in ticker
assert "ticker-content" in ticker
print("[OK] breaking_ticker_html")

# Skeleton
skel = skeleton_card_html()
assert "sk-card" in skel and "skeleton" in skel
print("[OK] skeleton_card_html")

# Empty state
es = empty_state_html("📭", "No articles", "Try refreshing.")
assert "empty-state" in es and "No articles" in es
print("[OK] empty_state_html")

# Search results header
sr = search_results_header_html("openai", 15)
assert "openai" in sr and "15" in sr
print("[OK] search_results_header_html")

# History row
hr = history_row_html("climate change", 8, "2026-05-27T10:00:00+00:00")
assert "hist-row" in hr and "climate change" in hr
print("[OK] history_row_html")

# API status
ok_html  = api_status_html("Gemini API", True)
err_html = api_status_html("GNews API", False)
assert "api-ok" in ok_html and "api-miss" in err_html
print("[OK] api_status_html")

# Section header
sh = section_header_html("Top Stories", 10)
assert "sec-header" in sh and "10" in sh
print("[OK] section_header_html")

# Time ago
t1 = _time_ago("2026-05-27T00:00:00+00:00")
assert isinstance(t1, str) and len(t1) > 0
t2 = _time_ago(None)
assert t2 == "Recently"
print(f"[OK] _time_ago: '{t1}'")

# ── 3. HTML escaping safety check ────────────────────────────────────
evil = dict(article, title='<script>alert("xss")</script> & "quoted"')
evil_card = article_card_html(evil)
assert "<script>" not in evil_card
assert "&lt;script&gt;" in evil_card
print("[OK] XSS escaping in article_card_html")

# ── 4. Cross-cutting: settings + DB + summarizer imports ─────────────
from config.settings import settings, TOPICS, SENTIMENT_LABELS
assert len(TOPICS) == 11
assert len(SENTIMENT_LABELS) == 3
print(f"[OK] settings: {len(TOPICS)} topics, {len(SENTIMENT_LABELS)} sentiments")

from db.database import NewsDatabase
from services.summarizer import ArticleSummarizer, SummaryMode
from services.categorizer import ArticleCategorizer
from services.news_fetcher import NewsFetcher, Article
print("[OK] all service imports")

# SummaryMode values
assert SummaryMode.STANDARD.value == "standard"
assert SummaryMode.ANCHOR.value   == "anchor"
assert SummaryMode.BULLET.value   == "bullet"
assert SummaryMode.HEADLINE.value == "headline"
print("[OK] SummaryMode enum values")

print()
print("=== ALL UI SMOKE TESTS PASSED ===")
