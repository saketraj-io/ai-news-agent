"""Smoke tests for categorizer + database."""
import sys, os
sys.path.insert(0, r'c:\Users\sksak\OneDrive\Desktop\ai_news_agent')

# ─── CATEGORIZER ────────────────────────────────────────────────────
from services.categorizer import (
    CategoryResult, _keyword_categorise,
    _parse_gemini_json, _validate_and_coerce
)
print("IMPORT OK")

# Keyword categorise
r = _keyword_categorise(
    "OpenAI releases new GPT large language model",
    "OpenAI breakthrough in artificial intelligence"
)
assert r.ok
assert r.topic in ["Artificial Intelligence", "Technology"]
print(f"KEYWORD topic={r.topic} sentiment={r.sentiment} tags={r.tags}")

# Negative sentiment
r2 = _keyword_categorise(
    "Market crash: stocks collapse in worst decline",
    "stocks crashed heavily, worst loss since 2020"
)
assert r2.sentiment == "Negative", f"Expected Negative got {r2.sentiment}"
print(f"NEGATIVE sentiment={r2.sentiment}")

# JSON parse - clean
raw = '{"topic": "Technology", "sentiment": "Positive", "tags": ["ai", "tech"], "confidence": 0.9}'
p = _parse_gemini_json(raw)
assert p is not None
assert p["topic"] == "Technology"
print("JSON_PARSE clean OK")

# JSON parse - code fence
fenced = '```json\n{"topic": "Health", "sentiment": "Neutral", "tags": ["vaccine"], "confidence": 0.7}\n```'
p2 = _parse_gemini_json(fenced)
assert p2 is not None
assert p2["topic"] == "Health"
print("JSON_PARSE fenced OK")

# JSON parse - trailing comma
tc = '{"topic": "Sports", "sentiment": "Positive", "tags": ["nba", "basketball",], "confidence": 0.8,}'
p3 = _parse_gemini_json(tc)
assert p3 is not None
print("JSON_PARSE trailing_comma OK")

# Validate and coerce - invalid values
c = _validate_and_coerce({
    "topic": "INVALID_TOPIC",
    "sentiment": "INVALID_SENTIMENT",
    "tags": [],
    "confidence": 99.0,
})
assert c["confidence"] == 1.0        # clamped
assert c["sentiment"] == "Neutral"   # invalid → Neutral
assert c["topic"] == "General"       # unknown → General
print(f"COERCE topic={c['topic']} sentiment={c['sentiment']} conf={c['confidence']}")

# CategoryResult properties
cr = CategoryResult(
    article_id="x", url="u", topic="Technology",
    sentiment="Positive", tags=["ai", "tech"],
    confidence=0.9, method="gemini", ok=True
)
assert cr.ok
assert "#ai" in cr.tags_display
print(f"CategoryResult OK tags_display={cr.tags_display}")

# ─── DATABASE ───────────────────────────────────────────────────────
import tempfile
from db.database import NewsDatabase
print("\nDB TESTS:")

tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_path = tmp_file.name
tmp_file.close()

db = NewsDatabase(db_path=tmp_path)
print("DB_INIT OK")

article = {
    "id": "a1",
    "title": "Test Article Title",
    "description": "Test description text",
    "content": "Full article content here.",
    "url": "https://example.com/article-1",
    "image_url": None,
    "source_name": "TestSource",
    "published_at": "2026-05-27T10:00:00+00:00",
    "category": "technology",
    "topic_label": "Technology",
    "summary": None,
    "sentiment": None,
    "tags": ["ai", "tech"],
}
assert db.upsert_article(article)
print("UPSERT OK")

fetched = db.get_article("a1")
assert fetched is not None
assert fetched["title"] == "Test Article Title"
assert fetched["tags"] == ["ai", "tech"]
print("GET_ARTICLE OK")

fetched2 = db.get_article_by_url("https://example.com/article-1")
assert fetched2 is not None
print("GET_BY_URL OK")

ok = db.update_article_enrichment(
    "a1", summary="AI is growing.", sentiment="Positive", tags=["ai", "growth"]
)
assert ok
enriched = db.get_article("a1")
assert enriched["summary"] == "AI is growing."
assert enriched["sentiment"] == "Positive"
assert "ai" in enriched["tags"]
print("ENRICHMENT OK")

db.save_summary("a1", "standard", "A concise summary.", "gemini-1.5-flash")
s = db.get_summary("a1", "standard")
assert s == "A concise summary."
print("SAVE_SUMMARY OK")

# Upsert replaces
db.save_summary("a1", "standard", "Updated summary.", "gemini-1.5-flash")
s2 = db.get_summary("a1", "standard")
assert s2 == "Updated summary."
print("SUMMARY_UPSERT OK")

db.save_summary("a1", "anchor", "Breaking news tonight.", "gemini-1.5-flash")
all_s = db.get_all_summaries("a1")
assert "standard" in all_s and "anchor" in all_s
print("ALL_SUMMARIES OK")

db.log_search("openai", 5)
db.log_search("climate change", 3)
db.log_search("openai", 2)
history = db.get_search_history(10)
assert len(history) == 3
popular = db.get_popular_searches(5)
assert popular[0]["query"].lower() == "openai"
assert popular[0]["count"] == 2
print("SEARCH_HISTORY OK")

stats = db.get_stats()
assert stats["total_articles"] == 1
assert stats["summarised"] == 1
assert stats["search_count"] == 3
print(f"STATS OK total={stats['total_articles']} summarised={stats['summarised']} db_mb={stats['db_size_mb']}")

results = db.search_articles("Test", limit=10)
assert len(results) >= 1
print("SEARCH_ARTICLES OK")

recent = db.get_recent_articles(10)
assert len(recent) == 1
print("RECENT_ARTICLES OK")

by_topic = db.get_articles_by_topic("Technology", limit=10)
assert len(by_topic) == 1
print("GET_BY_TOPIC OK")

deleted = db.purge_old_articles(keep_days=7)
assert deleted == 0
print("PURGE OK (nothing old)")

db.close()
os.unlink(tmp_path)
print("CLOSE + CLEANUP OK")

print("\n=== ALL CHECKS PASSED ===")
