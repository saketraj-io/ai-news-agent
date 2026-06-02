"""
db/database.py
──────────────
SQLite persistence layer for the AI News Agent.

Schema (3 tables):
  articles       — full Article records (enriched with summary + tags)
  summaries      — per-mode summaries for each article
  search_history — log of user search queries + result counts

Design principles:
  - Thread-safe: uses threading.local() for per-thread connections
  - Context manager (with db:) for all writes — auto commit + rollback
  - UPSERT semantics for articles (INSERT OR REPLACE)
  - Proper indexing for all common query patterns
  - JSON serialisation for list fields (tags)
  - Never raises — all errors are caught and logged
  - Schema migrations handled via IF NOT EXISTS + ALTER TABLE

Public surface:
  db = NewsDatabase()
  db.upsert_article(article)
  db.save_summary(article_id, mode, summary_text, model)
  db.log_search(query, results_count)
  articles = db.get_recent_articles(limit=20)
  articles = db.get_articles_by_topic("Technology")
  history  = db.get_search_history(limit=10)
  stats    = db.get_stats()
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from config.settings import settings
from utils.helpers import parse_date
from utils.logger import log


# ─────────────────────────────────────────────────────────────────────
# Schema DDL
# ─────────────────────────────────────────────────────────────────────

_CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT DEFAULT '',
    content         TEXT DEFAULT '',
    url             TEXT UNIQUE NOT NULL,
    image_url       TEXT,
    source_name     TEXT DEFAULT 'Unknown',
    published_at    TEXT,
    category        TEXT DEFAULT 'general',
    topic_label     TEXT DEFAULT 'General',
    summary         TEXT,
    sentiment       TEXT,
    tags            TEXT DEFAULT '[]',   -- JSON array
    scraped_text    TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

_CREATE_SUMMARIES = """
CREATE TABLE IF NOT EXISTS summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    summary         TEXT NOT NULL,
    model_used      TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    UNIQUE (article_id, mode),          -- one summary per article per mode
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);
"""

_CREATE_SEARCH_HISTORY = """
CREATE TABLE IF NOT EXISTS search_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query           TEXT NOT NULL,
    results_count   INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL
);
"""

# ── Indexes ───────────────────────────────────────────────────────────
_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(topic_label);",
    "CREATE INDEX IF NOT EXISTS idx_articles_sentiment ON articles(sentiment);",
    "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_summaries_article ON summaries(article_id);",
    "CREATE INDEX IF NOT EXISTS idx_search_created ON search_history(created_at DESC);",
]

_ALL_DDL = [
    _CREATE_ARTICLES,
    _CREATE_SUMMARIES,
    _CREATE_SEARCH_HISTORY,
] + _CREATE_INDEXES


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Returns current UTC time as ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _tags_to_json(tags: list[str] | None) -> str:
    """Serialises tags list → JSON string for storage."""
    return json.dumps(tags or [])


def _json_to_tags(raw: str | None) -> list[str]:
    """Deserialises tags JSON string → list."""
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_article_dict(row: sqlite3.Row) -> dict:
    """Converts a sqlite3.Row from the articles table to a plain dict."""
    d = dict(row)
    d["tags"] = _json_to_tags(d.get("tags"))
    return d


# ─────────────────────────────────────────────────────────────────────
# NewsDatabase
# ─────────────────────────────────────────────────────────────────────

class NewsDatabase:
    """
    Thread-safe SQLite persistence layer.

    Each thread gets its own sqlite3.Connection via threading.local().
    All public methods handle their own connection lifecycle.
    Schema is created/migrated automatically on first use.

    Usage:
        db = NewsDatabase()                   # or NewsDatabase(path)
        db.upsert_article(article)
        articles = db.get_recent_articles(20)
        db.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path else settings.db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._initialise_schema()
        log.info("NewsDatabase ready | path={}", self._path)

    # ── Connection management ─────────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        """Returns (or creates) a thread-local sqlite3 connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._path),
                check_same_thread=False,    # we guard with threading.local
                timeout=30,
            )
            conn.row_factory = sqlite3.Row   # access columns by name
            conn.execute("PRAGMA journal_mode=WAL;")   # better concurrency
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA synchronous=NORMAL;") # balance speed/safety
            self._local.conn = conn
        return conn

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for write operations.
        Auto-commits on success, rolls back on exception.
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            log.error("DB write error (rolled back): {}", exc)
            raise

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Executes a SELECT and returns all rows."""
        try:
            conn = self._get_connection()
            return conn.execute(sql, params).fetchall()
        except Exception as exc:
            log.error("DB read error: {} | SQL: {}", exc, sql[:80])
            return []

    def _read_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Executes a SELECT and returns the first row (or None)."""
        try:
            conn = self._get_connection()
            return conn.execute(sql, params).fetchone()
        except Exception as exc:
            log.error("DB read_one error: {} | SQL: {}", exc, sql[:80])
            return None

    def _initialise_schema(self) -> None:
        """Creates tables and indexes if they don't exist."""
        try:
            with self._write() as conn:
                for ddl in _ALL_DDL:
                    conn.execute(ddl)
            log.debug("DB schema initialised")
        except Exception as exc:
            log.error("Failed to initialise DB schema: {}", exc)

    # ── Article operations ────────────────────────────────────────────

    def upsert_article(self, article) -> bool:
        """
        Inserts or replaces an Article object.
        Returns True on success, False on failure.

        Accepts either an Article dataclass (from news_fetcher)
        or a plain dict with the same keys.
        """
        try:
            if hasattr(article, "to_dict"):
                data = article.to_dict()
            else:
                data = dict(article)

            now = _now_iso()
            with self._write() as conn:
                conn.execute(
                    """
                    INSERT INTO articles
                        (id, title, description, content, url, image_url,
                         source_name, published_at, category, topic_label,
                         summary, sentiment, tags, scraped_text,
                         created_at, updated_at)
                    VALUES
                        (:id, :title, :description, :content, :url, :image_url,
                         :source_name, :published_at, :category, :topic_label,
                         :summary, :sentiment, :tags, :scraped_text,
                         :created_at, :updated_at)
                    ON CONFLICT(id) DO UPDATE SET
                        title        = excluded.title,
                        description  = excluded.description,
                        content      = excluded.content,
                        image_url    = excluded.image_url,
                        summary      = excluded.summary,
                        sentiment    = excluded.sentiment,
                        tags         = excluded.tags,
                        scraped_text = excluded.scraped_text,
                        updated_at   = excluded.updated_at
                    """,
                    {
                        "id":           data.get("id", ""),
                        "title":        data.get("title", ""),
                        "description":  data.get("description", ""),
                        "content":      data.get("content", ""),
                        "url":          data.get("url", ""),
                        "image_url":    data.get("image_url"),
                        "source_name":  data.get("source_name", "Unknown"),
                        "published_at": data.get("published_at"),
                        "category":     data.get("category", "general"),
                        "topic_label":  data.get("topic_label", "General"),
                        "summary":      data.get("summary"),
                        "sentiment":    data.get("sentiment"),
                        "tags":         _tags_to_json(data.get("tags", [])),
                        "scraped_text": data.get("scraped_text", ""),
                        "created_at":   now,
                        "updated_at":   now,
                    },
                )
            return True
        except Exception as exc:
            log.error("upsert_article failed: {}", exc)
            return False

    def upsert_articles(self, articles: list) -> int:
        """
        Batch upsert. Returns number of successfully saved articles.
        """
        count = 0
        for article in articles:
            if self.upsert_article(article):
                count += 1
        log.info("Upserted {}/{} articles to DB", count, len(articles))
        return count

    def get_article(self, article_id: str) -> dict | None:
        """Fetch a single article by ID. Returns dict or None."""
        row = self._read_one(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        )
        return _row_to_article_dict(row) if row else None

    def get_article_by_url(self, url: str) -> dict | None:
        """Fetch a single article by URL."""
        row = self._read_one(
            "SELECT * FROM articles WHERE url = ?", (url,)
        )
        return _row_to_article_dict(row) if row else None

    def get_recent_articles(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Returns most-recently-added articles, newest first."""
        rows = self._read(
            "SELECT * FROM articles ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [_row_to_article_dict(r) for r in rows]

    def get_articles_by_topic(
        self,
        topic_label: str,
        limit: int = 20,
    ) -> list[dict]:
        """Returns articles filtered by topic_label, newest first."""
        rows = self._read(
            """
            SELECT * FROM articles
            WHERE topic_label = ?
            ORDER BY published_at DESC, created_at DESC
            LIMIT ?
            """,
            (topic_label, limit),
        )
        return [_row_to_article_dict(r) for r in rows]

    def get_articles_by_sentiment(
        self,
        sentiment: str,
        limit: int = 20,
    ) -> list[dict]:
        """Returns articles filtered by sentiment ('Positive'/'Neutral'/'Negative')."""
        rows = self._read(
            """
            SELECT * FROM articles
            WHERE sentiment = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (sentiment, limit),
        )
        return [_row_to_article_dict(r) for r in rows]

    def search_articles(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Full-text keyword search across title, description, and summary.
        Uses SQLite LIKE (no FTS5 dependency required).
        """
        pattern = f"%{query}%"
        rows = self._read(
            """
            SELECT * FROM articles
            WHERE  title LIKE ?
                OR description LIKE ?
                OR summary LIKE ?
                OR tags LIKE ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, limit),
        )
        return [_row_to_article_dict(r) for r in rows]

    def update_article_enrichment(
        self,
        article_id: str,
        summary: Optional[str] = None,
        sentiment: Optional[str] = None,
        tags: Optional[list[str]] = None,
        scraped_text: Optional[str] = None,
    ) -> bool:
        """
        Patches enrichment fields on an existing article row.
        Only provided (non-None) fields are updated.
        """
        updates: dict[str, Any] = {"id": article_id, "updated_at": _now_iso()}
        set_clauses = ["updated_at = :updated_at"]

        if summary is not None:
            updates["summary"] = summary
            set_clauses.append("summary = :summary")
        if sentiment is not None:
            updates["sentiment"] = sentiment
            set_clauses.append("sentiment = :sentiment")
        if tags is not None:
            updates["tags"] = _tags_to_json(tags)
            set_clauses.append("tags = :tags")
        if scraped_text is not None:
            updates["scraped_text"] = scraped_text
            set_clauses.append("scraped_text = :scraped_text")

        if len(set_clauses) == 1:
            return True  # nothing to update

        sql = f"UPDATE articles SET {', '.join(set_clauses)} WHERE id = :id"
        try:
            with self._write() as conn:
                conn.execute(sql, updates)
            return True
        except Exception as exc:
            log.error("update_article_enrichment failed: {}", exc)
            return False

    def delete_article(self, article_id: str) -> bool:
        """Deletes an article and its summaries (CASCADE)."""
        try:
            with self._write() as conn:
                conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            return True
        except Exception as exc:
            log.error("delete_article failed: {}", exc)
            return False

    def count_articles(self) -> int:
        """Returns total article count in the DB."""
        row = self._read_one("SELECT COUNT(*) AS n FROM articles")
        return row["n"] if row else 0

    # ── Summary operations ────────────────────────────────────────────

    def save_summary(
        self,
        article_id: str,
        mode: str,
        summary: str,
        model_used: str = "",
    ) -> bool:
        """
        Saves (or replaces) a summary for a given article + mode.
        UNIQUE constraint on (article_id, mode) means this is an upsert.
        """
        try:
            now = _now_iso()
            with self._write() as conn:
                conn.execute(
                    """
                    INSERT INTO summaries (article_id, mode, summary, model_used, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(article_id, mode) DO UPDATE SET
                        summary    = excluded.summary,
                        model_used = excluded.model_used,
                        created_at = excluded.created_at
                    """,
                    (article_id, mode, summary, model_used, now),
                )
            return True
        except Exception as exc:
            log.error("save_summary failed: {}", exc)
            return False

    def get_summary(self, article_id: str, mode: str) -> str | None:
        """
        Returns the stored summary text for a given article + mode,
        or None if not yet generated.
        """
        row = self._read_one(
            "SELECT summary FROM summaries WHERE article_id = ? AND mode = ?",
            (article_id, mode),
        )
        return row["summary"] if row else None

    def get_all_summaries(self, article_id: str) -> dict[str, str]:
        """
        Returns all summaries for an article as {mode: summary_text}.
        """
        rows = self._read(
            "SELECT mode, summary FROM summaries WHERE article_id = ?",
            (article_id,),
        )
        return {r["mode"]: r["summary"] for r in rows}

    # ── Search history operations ─────────────────────────────────────

    def log_search(self, query: str, results_count: int = 0) -> bool:
        """Records a user search query to the history table."""
        try:
            with self._write() as conn:
                conn.execute(
                    "INSERT INTO search_history (query, results_count, created_at) VALUES (?, ?, ?)",
                    (query.strip(), results_count, _now_iso()),
                )
            return True
        except Exception as exc:
            log.error("log_search failed: {}", exc)
            return False

    def get_search_history(self, limit: int = 20) -> list[dict]:
        """Returns recent searches, newest first."""
        rows = self._read(
            "SELECT * FROM search_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def get_popular_searches(self, limit: int = 10) -> list[dict]:
        """Returns most-searched queries, by frequency."""
        rows = self._read(
            """
            SELECT query, COUNT(*) AS count,
                   MAX(created_at) AS last_searched
            FROM   search_history
            GROUP  BY LOWER(query)
            ORDER  BY count DESC, last_searched DESC
            LIMIT  ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    def clear_search_history(self) -> bool:
        """Wipes all search history."""
        try:
            with self._write() as conn:
                conn.execute("DELETE FROM search_history")
            return True
        except Exception as exc:
            log.error("clear_search_history failed: {}", exc)
            return False

    # ── Statistics ────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        Returns an overview dict for display in the Streamlit sidebar.
        {
          total_articles, summarised, with_sentiment,
          by_topic: {label: count},
          by_sentiment: {label: count},
          search_count,
          db_size_mb,
        }
        """
        total      = self.count_articles()
        row_s      = self._read_one("SELECT COUNT(DISTINCT article_id) AS n FROM summaries")
        summarised = dict(row_s).get("n", 0) if row_s else 0
        row_sc     = self._read_one("SELECT COUNT(*) AS n FROM search_history")
        search_count = dict(row_sc).get("n", 0) if row_sc else 0
        sentiments = self._read(
            "SELECT sentiment, COUNT(*) AS n FROM articles WHERE sentiment IS NOT NULL GROUP BY sentiment"
        )
        topics = self._read(
            "SELECT topic_label, COUNT(*) AS n FROM articles GROUP BY topic_label ORDER BY n DESC"
        )

        db_size_mb = 0.0
        try:
            db_size_mb = round(self._path.stat().st_size / (1024 * 1024), 2)
        except OSError:
            pass

        return {
            "total_articles": total,
            "summarised":     int(summarised or 0),
            "with_sentiment": sum(r["n"] for r in sentiments),
            "by_topic":       {r["topic_label"]: r["n"] for r in topics if r["topic_label"]},
            "by_sentiment":   {r["sentiment"]: r["n"] for r in sentiments if r["sentiment"]},
            "search_count":   int(search_count or 0),
            "db_size_mb":     db_size_mb,
        }

    # ── Maintenance ───────────────────────────────────────────────────

    def purge_old_articles(self, keep_days: int = 7) -> int:
        """
        Deletes articles older than keep_days.
        Returns count of deleted rows.
        """
        cutoff = datetime.now(tz=timezone.utc)
        # We subtract keep_days via ISO string comparison (ISO sorts lexicographically)
        from datetime import timedelta
        cutoff_iso = (datetime.now(tz=timezone.utc) - timedelta(days=keep_days)).isoformat()
        try:
            with self._write() as conn:
                cursor = conn.execute(
                    "DELETE FROM articles WHERE created_at < ?", (cutoff_iso,)
                )
                deleted = cursor.rowcount
            log.info("Purged {} articles older than {} days", deleted, keep_days)
            return deleted
        except Exception as exc:
            log.error("purge_old_articles failed: {}", exc)
            return 0

    def vacuum(self) -> None:
        """Runs VACUUM to reclaim disk space after deletions."""
        try:
            conn = self._get_connection()
            conn.execute("VACUUM")
            log.info("DB VACUUM complete")
        except Exception as exc:
            log.error("VACUUM failed: {}", exc)

    def close(self) -> None:
        """Closes the thread-local connection."""
        conn = getattr(self._local, "conn", None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def __repr__(self) -> str:
        return f"NewsDatabase(path={self._path}, articles={self.count_articles()})"
