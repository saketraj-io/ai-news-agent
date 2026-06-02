"""
app.py
──────
AI News Agent — Streamlit application entry point.

Run with:
    streamlit run app.py

Architecture:
    ┌─────────────────────────────────────┐
    │  @st.cache_resource  singletons     │
    │  NewsFetcher · ArticleSummarizer    │
    │  ArticleCategorizer · NewsDatabase  │
    └──────────────┬──────────────────────┘
                   │
    ┌──────────────▼──────────────────────┐
    │  @st.cache_data(ttl)  data layer    │
    │  _fetch_topic · _fetch_search       │
    └──────────────┬──────────────────────┘
                   │
    ┌──────────────▼──────────────────────┐
    │  Streamlit UI                       │
    │  Sidebar → Header → Ticker → Feed   │
    │  Trending panel · History tab       │
    └─────────────────────────────────────┘
"""

# ══════════════════════════════════════════════════════════════════════
# IMPORTANT: load_dotenv MUST fire before any project module is imported.
# We use an explicit absolute path so Streamlit's CWD never matters.
# override=True ensures .env values win over any stale process-env values.
# ══════════════════════════════════════════════════════════════════════
import os
import pathlib

from dotenv import load_dotenv

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
_DOTENV_PATH  = _PROJECT_ROOT / ".env"

_dotenv_loaded = load_dotenv(dotenv_path=_DOTENV_PATH, override=True)

# ── Page config MUST be the very first Streamlit call ─────────────────
import streamlit as st

st.set_page_config(
    page_title="AI News Agent · Gemini Powered",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": (
            "**AI News Agent v1.0**\n\n"
            "Real-time AI-powered news intelligence.\n"
            "Powered by Google Gemini · GNews API · RSS feeds.\n\n"
            "Built with ❤️ using Python + Streamlit."
        ),
    },
)

# ── CSS injection — immediately after page config ─────────────────────
from ui.styles import inject_css
inject_css()

# ── Standard library ──────────────────────────────────────────────────
import sys
from datetime import datetime, timezone

# ── Project imports (all AFTER load_dotenv) ────────────────────────────
# settings.py creates Settings() at import time; by this point os.environ
# already has the values from .env thanks to the load_dotenv call above.
from config.settings import settings, TOPICS

# ── Runtime patch: if settings.py was somehow imported earlier (e.g. by
#    a cached Streamlit module) with empty keys, re-read from os.environ.
#    This is a safety net — should not be needed on a clean first run.
if not settings.gemini_api_key:
    settings.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
if not settings.gnews_api_key:
    settings.gnews_api_key = os.environ.get("GNEWS_API_KEY", "")
from db.database import NewsDatabase
from services.news_fetcher import NewsFetcher
from services.summarizer import ArticleSummarizer, SummaryMode
from services.categorizer import ArticleCategorizer
from ui.components import (
    render_page_header,
    render_breaking_ticker,
    render_skeleton_grid,
    render_empty_state,
    render_section_header,
)
from ui.layouts import (
    render_sidebar,       # kept for reference (not called)
    render_topnav,        # ← active: top navigation bar replacing sidebar
    render_article_grid,
    render_search_results,
    render_trending_panel,
    render_topic_summary_panel,
    render_history_tab,
    CATEGORY_CONFIG,   # icon / fetch_type / query lookup
)


# ─────────────────────────────────────────────────────────────────────
# Cached service singletons
# @st.cache_resource persists across all reruns — no re-initialisation
# ─────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_db() -> NewsDatabase:
    """Singleton SQLite database instance."""
    return NewsDatabase()


@st.cache_resource(show_spinner=False)
def get_fetcher() -> NewsFetcher:
    """Singleton news fetcher (GNews + RSS)."""
    return NewsFetcher()


@st.cache_resource(show_spinner=False)
def get_summarizer() -> ArticleSummarizer:
    """Singleton Gemini summarizer."""
    return ArticleSummarizer()


@st.cache_resource(show_spinner=False)
def get_categorizer() -> ArticleCategorizer:
    """Singleton Gemini / keyword categorizer."""
    return ArticleCategorizer()


# ─────────────────────────────────────────────────────────────────────
# Cached data fetchers (TTL-based)
# Returns list[dict] — plain dicts are pickle-safe for st.cache_data
# ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_topic(
    topic: str,
    fetch_type: str,
    fetch_query: str,
    max_articles: int,
    cache_version: int = 2,          # bump to bust stale cache
) -> list[dict]:
    """
    Fetches and caches articles for a nav-bar category (5-min TTL).

    fetch_type:
      "headlines" → NewsFetcher.get_top_headlines()
      "category"  → NewsFetcher.get_by_category(fetch_query)
                    fetch_query is a GNEWS_CATEGORY_MAP key
      "search"    → NewsFetcher.search(fetch_query)
                    fetch_query is a keyword string (Cricket, AI, Stocks…)
    """
    try:
        fetcher = get_fetcher()
        if fetch_type == "headlines":
            arts = fetcher.get_top_headlines(max_articles)
        elif fetch_type == "category":
            arts = fetcher.get_by_category(fetch_query, max_articles)
        else:  # "search" — used for Cricket, AI, Stocks, India, etc.
            arts = fetcher.search(fetch_query, max_articles)
        return [a.to_dict() for a in arts]
    except Exception as exc:
        st.session_state["_api_error"] = str(exc)
        return []


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_search(query: str, max_articles: int) -> list[dict]:
    """
    Fetches and caches free-text search results (2-min TTL).
    Returns a list of Article.to_dict() payloads.
    """
    try:
        fetcher = get_fetcher()
        arts = fetcher.search(query, max_articles)
        return [a.to_dict() for a in arts]
    except Exception as exc:
        st.session_state["_api_error"] = str(exc)
        return []


# ─────────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────────

def _init_state() -> None:
    """Bootstraps all session-state keys with safe defaults."""
    defaults: dict = {
        "selected_topic":    "Top Headlines",
        "topic_fetch_type":  "headlines",    # how to fetch the active category
        "topic_fetch_query": "",             # GNews label or search string
        "search_query":      "",             # free-text user search
        "max_articles":      settings.max_articles_per_topic,
        "global_mode":       "standard",
        "_last_topic":       None,
        "_last_fetch_type":  None,
        "_api_error":        None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _clear_api_error() -> None:
    st.session_state["_api_error"] = None


def _render_quick_stats(db: NewsDatabase) -> None:
    """Compact two-metric widget for the right panel."""
    render_section_header("📊 Quick Stats")
    try:
        stats = db.get_stats()
        c1, c2 = st.columns(2)
        with c1:
            st.metric("📰 Articles", stats.get("total_articles", 0))
        with c2:
            st.metric("🤖 Summarised", stats.get("summarised", 0))

        # Sentiment bar (if data exists)
        by_sent = stats.get("by_sentiment", {})
        if by_sent:
            total_sent = sum(by_sent.values()) or 1
            parts = []
            colors = {"Positive": "#22c55e", "Neutral": "#eab308", "Negative": "#ef4444"}
            for label, count in by_sent.items():
                pct  = round(count / total_sent * 100)
                col  = colors.get(label, "#6366f1")
                parts.append(
                    f'<div style="flex:{pct};background:{col};height:6px;'
                    f'border-radius:3px;min-width:4px;'
                    f'title="{label}: {pct}%"></div>'
                )
            st.markdown(
                '<div style="display:flex;gap:3px;margin-top:0.4rem;">'
                + "".join(parts)
                + "</div>"
                + '<div style="display:flex;gap:10px;margin-top:4px;">'
                + "".join(
                    f'<span style="font-size:0.65rem;color:{colors.get(l,"#6366f1")}">'
                    f'{l[0]} {round(c/total_sent*100)}%</span>'
                    for l, c in by_sent.items()
                )
                + "</div>",
                unsafe_allow_html=True,
            )
    except Exception:
        st.caption("Stats loading…")


def _show_config_warnings() -> None:
    """Shows a collapsible warning if API keys are missing."""
    missing = settings.validate()
    if missing:
        with st.expander("⚠️ Configuration warnings", expanded=True):
            for w in missing:
                st.warning(w, icon="⚠️")
            st.info(
                "Add missing keys to your `.env` file and restart the app.\n\n"
                "See `.env.example` for the full list of required variables.",
                icon="ℹ️",
            )


def _show_env_debug_panel() -> None:
    """
    Debug panel — shows which keys are loaded and where .env was found.
    Rendered in the main area (NOT sidebar) so the sidebar stays collapsed.
    """
    with st.expander("🔑 Env Debug", expanded=False):
        gemini_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        gnews_key  = settings.gnews_api_key  or os.environ.get("GNEWS_API_KEY",  "")

        def _mask(k: str) -> str:
            return f"{k[:8]}…***" if len(k) >= 8 else ("(empty)" if not k else f"{k[:4]}…")

        env_file_status = (
            f"✅ Found: `{_DOTENV_PATH}`"
            if _dotenv_loaded
            else f"❌ Not found: `{_DOTENV_PATH}`"
        )
        st.markdown(
            f"""
**`.env` file:** {env_file_status}

| Key | Value |
|-----|-------|
| `GEMINI_API_KEY` | `{_mask(gemini_key)}` |
| `GNEWS_API_KEY`  | `{_mask(gnews_key)}` |
| `GEMINI_MODEL`   | `{settings.gemini_model}` |
"""
        )
        if not gemini_key or not gnews_key:
            st.error(
                "One or more keys are missing. Make sure your `.env` file is in:\n\n"
                f"`{_PROJECT_ROOT}`"
            )
        else:
            st.success("Both API keys are loaded ✓")



# ─────────────────────────────────────────────────────────────────────
# Service cache helper
# ─────────────────────────────────────────────────────────────────────

def _maybe_bust_service_cache() -> None:
    """
    If the @st.cache_resource singletons (summarizer, fetcher, categorizer)
    were built before .env keys were loaded, their internal clients hold
    empty API-key strings.  Detect this and force a one-time re-init by
    clearing the cache so the next get_*() call rebuilds them properly.

    We track whether we've already done this bust via session_state so
    we only do it once per server process start, not on every rerender.
    """
    bust_key = "_service_cache_busted"
    if st.session_state.get(bust_key):
        return  # already busted in a previous rerender this session

    gemini_key = settings.gemini_api_key
    gnews_key  = settings.gnews_api_key

    # Check whether summarizer was built with an empty key by peeking at
    # its internal GeminiClient.  If available() is False while a key IS
    # now present, the cache is stale.
    try:
        summ = get_summarizer.__wrapped__()  # won't work; use a flag instead
    except Exception:
        pass

    # Simpler and reliable: check the session-state flag we set on boot.
    already_initialized = st.session_state.get("_services_have_keys")
    if not already_initialized and gemini_key:
        # Keys are now available but singletons may not know — bust them.
        get_summarizer.clear()
        get_categorizer.clear()
        get_fetcher.clear()
        st.session_state["_services_have_keys"] = True
        st.session_state[bust_key] = True
    elif gemini_key:
        # Keys available and singletons already rebuilt — mark as done.
        st.session_state["_services_have_keys"] = True
        st.session_state[bust_key] = True


# ─────────────────────────────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Core application function — called on every Streamlit rerender.

    Flow:
      1. init session state
      2. get singletons (cached)
      3. render sidebar → get user settings
      4. fetch articles (TTL-cached)
      5. persist to DB
      6. render: header → ticker → two-column layout
    """
    _init_state()

    # ── Show env debug panel in sidebar (always visible during setup) ─
    _show_env_debug_panel()

    # ── Singletons ────────────────────────────────────────────────────
    # IMPORTANT: if this is the first run after keys were just loaded,
    # the @st.cache_resource objects may have been built with empty keys
    # (if Streamlit warmed the cache before this script ran fully).
    # We detect this and bust the service cache so they re-init properly.
    _maybe_bust_service_cache()

    db         = get_db()
    summarizer = get_summarizer()

    # ── Top navigation bar (search + categories + refresh) ─────────
    cfg = render_topnav(db=db)

    selected_topic = cfg["selected_topic"]
    fetch_type     = cfg["topic_fetch_type"]
    fetch_query    = cfg["topic_fetch_query"]
    max_articles   = cfg["max_articles"]
    search_query   = cfg["search_query"]
    do_refresh     = cfg["refresh"]

    # Category icon for headers
    cat_icon = CATEGORY_CONFIG.get(selected_topic, {}).get("icon", "📰")

    # ── Handle refresh ────────────────────────────────────────────────
    if do_refresh:
        _fetch_topic.clear()
        _fetch_search.clear()
        _clear_api_error()
        st.session_state.pop("_last_topic",      None)
        st.session_state.pop("_last_fetch_type", None)
        st.toast("✅ Feed refreshed!", icon="✅")

    # ── Fetch articles ────────────────────────────────────────────────
    articles: list[dict] = []

    if search_query:
        # ── Free-text search mode ─────────────────────────────────────
        with st.spinner(f'🔍 Searching "{search_query}"…'):
            articles = _fetch_search(search_query, max_articles)
        # Log once per unique query
        last_logged = st.session_state.get("_last_logged_search")
        if search_query != last_logged:
            try:
                db.log_search(search_query, len(articles))
            except Exception:
                pass
            st.session_state["_last_logged_search"] = search_query

    else:
        # ── Category / topic mode ─────────────────────────────────────
        topic_changed = (
            selected_topic != st.session_state.get("_last_topic")
            or fetch_type   != st.session_state.get("_last_fetch_type")
        )
        spin_label = (
            f"🔍 Loading {selected_topic}…"
            if fetch_type == "search"
            else f"📡 Fetching {selected_topic} news…"
        )
        if topic_changed or do_refresh:
            with st.spinner(spin_label):
                articles = _fetch_topic(selected_topic, fetch_type, fetch_query, max_articles)
            st.session_state["_last_topic"]      = selected_topic
            st.session_state["_last_fetch_type"] = fetch_type
        else:
            articles = _fetch_topic(selected_topic, fetch_type, fetch_query, max_articles)

    # ── Persist fetched articles to DB (best-effort) ──────────────────
    if articles:
        try:
            db.upsert_articles(articles)
        except Exception:
            pass  # DB errors must never crash the UI

    # ── API error notice ──────────────────────────────────────────────
    if st.session_state.get("_api_error"):
        st.warning(
            f"⚠️ API issue — {st.session_state['_api_error']}. "
            "Showing cached / DB results if available.",
            icon="⚠️",
        )

    # ── Fallback: load from DB if live fetch returned nothing ─────────
    if not articles:
        if search_query:
            articles = db.search_articles(search_query, limit=max_articles)
        elif fetch_type == "search":
            # Search-based categories: try first word as a DB keyword search
            keyword = fetch_query.split()[0] if fetch_query else selected_topic
            articles = db.search_articles(keyword, limit=max_articles)
        elif fetch_type == "category":
            articles = db.get_articles_by_topic(fetch_query, limit=max_articles)
        if not articles:
            articles = db.get_recent_articles(limit=max_articles)

    # ── Config warnings (collapsible, non-blocking) ───────────────────
    _show_config_warnings()


    # ── Page header ───────────────────────────────────────────────────
    if search_query:
        topic_display = f'🔍 Search: "{search_query}"'
    else:
        topic_display = f"{cat_icon} {selected_topic}"
    render_page_header(topic_display, len(articles))

    # ── Breaking news ticker ──────────────────────────────────────────
    render_breaking_ticker(articles[:10])

    # ── Two-column main layout ────────────────────────────────────────
    # Feed: 62 % width  |  Right panel: 38 % width
    feed_col, panel_col = st.columns([62, 38], gap="large")

    # ════════════════════════ LEFT: Article Feed ══════════════════════
    with feed_col:
        if search_query:
            # ── Free-text search results view ────────────────────────
            render_search_results(
                articles=articles,
                query=search_query,
                summarizer=summarizer,
                db=db,
            )

        else:
            # ── Tabbed category feed ──────────────────────────────────
            tab_stories, tab_history = st.tabs(
                ["📰  Top Stories", "🕐  Search History"]
            )

            with tab_stories:
                # Section header with icon + fetch-type badge
                fetch_badge = (
                    '<span style="font-size:0.65rem;background:rgba(99,102,241,0.15);'
                    'color:#818cf8;border-radius:8px;padding:1px 7px;'
                    f'margin-left:6px;vertical-align:middle">'
                    + ("via search" if fetch_type == "search" else "live feed")
                    + "</span>"
                    if fetch_type != "headlines" else ""
                )
                render_section_header(
                    f"{cat_icon} {selected_topic}",
                    count=len(articles),
                )

                if not articles:
                    render_empty_state(
                        cat_icon,
                        f"No {selected_topic} articles found",
                        "Try clicking Refresh Feed or check your API keys.",
                    )
                else:
                    render_article_grid(
                        articles=articles,
                        summarizer=summarizer,
                        db=db,
                        n_cols=2,
                    )

            with tab_history:
                render_history_tab(db=db)

    # ═══════════════════════ RIGHT: Side Panel ════════════════════════
    with panel_col:

        # ── Trending Now ──────────────────────────────────────────────
        render_trending_panel(articles)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Topic Mix ─────────────────────────────────────────────────
        render_topic_summary_panel(articles)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Quick stats ───────────────────────────────────────────────
        _render_quick_stats(db)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Gemini status card ────────────────────────────────────────
        _render_gemini_card()


def _render_gemini_card() -> None:
    """Small Gemini status + tip card in the right panel."""
    render_section_header("🤖 Gemini AI")
    gemini_ok = bool(settings.gemini_api_key)
    status_color = "#22c55e" if gemini_ok else "#ef4444"
    status_text  = "Connected" if gemini_ok else "Not connected"
    model_name   = settings.gemini_model if gemini_ok else "—"

    st.markdown(
        f"""
<div style="background:rgba(99,102,241,0.06);border:1px solid rgba(99,102,241,0.15);
            border-radius:12px;padding:0.9rem 1rem;font-size:0.82rem;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:0.5rem;">
    <span style="width:8px;height:8px;background:{status_color};border-radius:50%;
                 flex-shrink:0;box-shadow:0 0 8px {status_color}40;"></span>
    <span style="color:#94a3b8;">Status: </span>
    <span style="color:{status_color};font-weight:600;">{status_text}</span>
  </div>
  <div style="color:#475569;margin-bottom:0.3rem;">Model: <span style="color:#94a3b8">{model_name}</span></div>
  <div style="color:#475569;">Rate limit: <span style="color:#94a3b8">{settings.gemini_rpm_limit} RPM</span></div>
  {"" if gemini_ok else
    '<div style="margin-top:0.6rem;color:#f87171;font-size:0.75rem;">'
    'Set GEMINI_API_KEY in .env to enable AI summaries.'
    '</div>'
  }
</div>
""",
        unsafe_allow_html=True,
    )

    if gemini_ok:
        mode = st.session_state.get("global_mode", "standard")
        mode_labels = {
            "standard": "📝 Standard — factual 2-3 sentence summary",
            "anchor":   "📺 Anchor — broadcast script narration",
            "bullet":   "📋 Bullets — 4-5 key facts",
            "headline": "📰 Headline — punchy title + context",
        }
        st.markdown(
            f'<div style="margin-top:0.6rem;font-size:0.75rem;color:#6366f1;">'
            f'Active mode: {mode_labels.get(mode, mode)}</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

main()
