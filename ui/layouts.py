"""
ui/layouts.py
─────────────
Page-level layout assembly functions.

Each function composes components into full sections:
  render_sidebar()          — full sidebar UI; returns dict of user settings
  render_article_grid()     — two-column article feed
  render_search_results()   — search-results header + grid
  render_trending_panel()   — compact trending cards (right panel)
  render_topic_summary_panel() — topic-mix breakdown
  render_history_tab()      — search history display
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Optional

import streamlit as st

from config.settings import settings, TOPICS
from ui.styles import TOPIC_ICONS, TOPIC_GRADIENTS, SUMMARY_MODE_LABELS
from ui.components import (
    render_article_card,
    render_section_header,
    render_empty_state,
    render_api_status,
    render_stat_row,
    compact_card_html,
    history_row_html,
    search_results_header_html,
)


# ─────────────────────────────────────────────────────────────────────
# Extended Category Configuration
# ─────────────────────────────────────────────────────────────────────
# Tuple layout: (icon, display_label, fetch_type, fetch_query)
#
# fetch_type options:
#   "headlines" → NewsFetcher.get_top_headlines()
#   "category"  → NewsFetcher.get_by_category(fetch_query)
#                 fetch_query must be a key in GNEWS_CATEGORY_MAP
#   "search"    → NewsFetcher.search(fetch_query)
#                 fetch_query is a keyword string
SIDEBAR_CATEGORIES: list[tuple[str, str, str, str]] = [
    ("🔥", "Top Headlines",  "headlines", ""),
    ("🏏", "Cricket",        "search",    "cricket IPL match highlights score wicket"),
    ("⚽", "Sports",         "category",  "Sports"),
    ("🏛️", "Politics",       "category",  "Politics"),
    ("🤖", "AI",             "search",    "artificial intelligence AI LLM GPT machine learning"),
    ("💻", "Technology",     "category",  "Technology"),
    ("📈", "Stocks",         "search",    "stocks market shares NSE BSE Sensex Nifty trading"),
    ("💰", "Finance",        "category",  "Business & Finance"),
    ("🚀", "Startups",       "search",    "startup funding unicorn venture capital tech"),
    ("🌍", "World",          "category",  "World"),
    ("🇮🇳", "India",          "search",    "India news today latest"),
    ("🎬", "Entertainment",  "category",  "Entertainment"),
]

# Quick lookup by display label → { icon, type, query }
CATEGORY_CONFIG: dict[str, dict] = {
    label: {"icon": icon, "type": ftype, "query": query}
    for icon, label, ftype, query in SIDEBAR_CATEGORIES
}

# Suggested-search chips shown beneath the search bar
SUGGESTED_SEARCHES: list[str] = [
    "IPL", "Virat Kohli", "Bitcoin",
    "NVIDIA", "ChatGPT", "Sensex",
    "Elon Musk", "Apple", "Budget",
    "Election", "Tesla", "RBI",
]


# ─────────────────────────────────────────────────────────────────────
# Top Navigation Bar  (replaces sidebar)
# ─────────────────────────────────────────────────────────────────────

def render_topnav(db=None) -> dict:
    """
    Renders a full-width top navigation bar with:
      • Logo / brand
      • Search bar (with Enter-to-search)
      • Category pill buttons
      • Refresh button
    Returns the same cfg dict as render_sidebar() so app.py is unchanged.
    """
    current_topic = st.session_state.get("selected_topic", "Top Headlines")
    max_articles  = st.session_state.get("max_articles",  10)
    summary_mode  = st.session_state.get("global_mode",   "standard")

    # ── Top bar: logo | search | refresh ─────────────────────────────
    st.markdown(
        """
<style>
/* ── Top-nav bar ── */
.topnav-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0.65rem 1.1rem;
    margin-bottom: 0.6rem;
    background: rgba(8,11,21,0.96);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    flex-wrap: wrap;
}
.topnav-brand {
    display: flex; align-items: center; gap: 8px;
    flex-shrink: 0;
    text-decoration: none;
}
.topnav-logo { font-size: 1.4rem; line-height: 1; }
.topnav-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1rem; font-weight: 800;
    background: linear-gradient(135deg, #f1f5f9 30%, #22d3ee 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
    white-space: nowrap;
}
.topnav-divider {
    width: 1px; height: 28px;
    background: rgba(255,255,255,0.08);
    flex-shrink: 0;
}
/* Category pills row */
.cat-pills {
    display: flex; gap: 5px; flex-wrap: wrap;
    margin-bottom: 0.5rem;
    padding: 0.45rem 1.1rem;
    background: rgba(8,11,21,0.7);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 12px;
}
.cat-pill {
    padding: 0.28rem 0.75rem;
    border-radius: 20px;
    font-size: 0.74rem; font-weight: 600;
    cursor: pointer; border: none;
    background: rgba(255,255,255,0.05);
    color: #94a3b8;
    transition: all 0.18s ease;
    white-space: nowrap;
}
.cat-pill:hover { background: rgba(99,102,241,0.18); color: #818cf8; }
.cat-pill-active {
    background: rgba(99,102,241,0.22) !important;
    color: #818cf8 !important;
    border: 1px solid rgba(99,102,241,0.45) !important;
    box-shadow: 0 0 10px rgba(99,102,241,0.2);
}
</style>
""",
        unsafe_allow_html=True,
    )

    # ── Row 1: Brand + Search + Refresh ──────────────────────────────
    brand_col, search_col, ref_col = st.columns([2.2, 6, 1.5])

    with brand_col:
        st.markdown(
            '<div class="topnav-brand">'
            '<span class="topnav-logo">🤖</span>'
            '<span class="topnav-title">AI News Agent</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    with search_col:
        with st.form("topnav_search", clear_on_submit=False):
            q_c, btn_c, clr_c = st.columns([8, 1.5, 1])
            with q_c:
                raw_q = st.text_input(
                    "search", placeholder="Search: IPL, Bitcoin, NVIDIA, Virat Kohli…",
                    label_visibility="collapsed",
                    value=st.session_state.get("search_query", ""),
                )
            with btn_c:
                do_search = st.form_submit_button("🔍 Search", type="primary", use_container_width=True)
            with clr_c:
                do_clear = st.form_submit_button("✕", use_container_width=True)

        if do_search and raw_q.strip():
            st.session_state.search_query = raw_q.strip()
            if db:
                try: db.log_search(raw_q.strip())
                except Exception: pass
            st.rerun()
        if do_clear:
            st.session_state.search_query = ""
            st.rerun()

    with ref_col:
        do_refresh = st.button(
            "🔄 Refresh", key="topnav_refresh",
            use_container_width=True, type="primary",
        )

    # ── Row 2: Category pills ─────────────────────────────────────────
    st.markdown('<div class="cat-pills">', unsafe_allow_html=True)
    pill_cols = st.columns(len(SIDEBAR_CATEGORIES))
    for idx, (icon, label, fetch_type, query) in enumerate(SIDEBAR_CATEGORIES):
        with pill_cols[idx]:
            is_active = label == current_topic
            btn_label = f"{icon} {label}"
            if st.button(
                btn_label,
                key=f"topnav_cat_{label}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
                help=label,
            ):
                _select_category(label, fetch_type, query)
    st.markdown('</div>', unsafe_allow_html=True)

    return {
        "selected_topic":    current_topic,
        "topic_fetch_type":  st.session_state.get("topic_fetch_type",  "headlines"),
        "topic_fetch_query": st.session_state.get("topic_fetch_query", ""),
        "max_articles":      max_articles,
        "summary_mode":      summary_mode,
        "search_query":      st.session_state.get("search_query", ""),
        "refresh":           do_refresh,
    }


# ─────────────────────────────────────────────────────────────────────
# Sidebar  (kept for reference; replaced by render_topnav in app.py)
# ─────────────────────────────────────────────────────────────────────

def render_sidebar(db=None) -> dict[str, Any]:
    """
    Renders the full sidebar and returns a dict of user-selected settings.

    Returns:
        {
          selected_topic:    str  — display label
          topic_fetch_type:  str  — "headlines" | "category" | "search"
          topic_fetch_query: str  — GNews label (category) or query string (search)
          max_articles:      int
          summary_mode:      str
          search_query:      str  — free-text search (empty = off)
          refresh:           bool
        }
    """
    with st.sidebar:

        # ── Branding ──────────────────────────────────────────────────
        st.markdown(
            """
<div style="text-align:center;padding:0.5rem 0 1.2rem">
  <div style="font-size:2.2rem;margin-bottom:0.25rem">🤖</div>
  <div style="font-family:'Space Grotesk',sans-serif;font-size:1.15rem;font-weight:800;
              background:linear-gradient(135deg,#f1f5f9,#22d3ee);
              -webkit-background-clip:text;-webkit-text-fill-color:transparent;
              background-clip:text">AI News Agent</div>
  <div style="font-size:0.7rem;color:#475569;margin-top:2px">Powered by Gemini 1.5</div>
</div>
""",
            unsafe_allow_html=True,
        )

        # ── API Status ────────────────────────────────────────────────
        with st.expander("⚙️ API Status", expanded=False):
            render_api_status("Gemini API", bool(settings.gemini_api_key))
            render_api_status("GNews API",  bool(settings.gnews_api_key))
            if not settings.gemini_api_key or not settings.gnews_api_key:
                st.markdown(
                    '<p style="font-size:0.75rem;color:#475569;margin-top:0.5rem">'
                    "Add keys to <code>.env</code> or Streamlit Secrets.</p>",
                    unsafe_allow_html=True,
                )

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Category Navigation ───────────────────────────────────────
        st.markdown(
            '<div style="font-size:0.7rem;font-weight:700;color:#475569;'
            'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:0.5rem">'
            "📂 Categories</div>",
            unsafe_allow_html=True,
        )

        # CSS for active button highlight (injected once per render)
        st.markdown(
            """
<style>
.nav-item-active > div > button {
    background: rgba(99,102,241,0.16) !important;
    border-color: rgba(99,102,241,0.45) !important;
    color: #818cf8 !important;
    font-weight: 600 !important;
}
</style>
""",
            unsafe_allow_html=True,
        )

        current_topic = st.session_state.get("selected_topic", "Top Headlines")

        for icon, label, fetch_type, query in SIDEBAR_CATEGORIES:
            is_active = label == current_topic
            display   = f"▸ {icon} {label}" if is_active else f"  {icon} {label}"

            if is_active:
                with st.container():
                    st.markdown('<div class="nav-item-active">', unsafe_allow_html=True)
                    if st.button(display, key=f"nav_{label}", use_container_width=True):
                        _select_category(label, fetch_type, query)
                    st.markdown("</div>", unsafe_allow_html=True)
            else:
                if st.button(display, key=f"nav_{label}", use_container_width=True):
                    _select_category(label, fetch_type, query)

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Search Bar ───────────────────────────────────────────────
        # Uses st.form so Enter key submits the search natively.
        st.markdown(
            '<div style="font-size:0.7rem;font-weight:700;color:#475569;'
            'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:0.5rem">'
            "🔍 Search News</div>",
            unsafe_allow_html=True,
        )

        with st.form(key="sidebar_search_form", clear_on_submit=False):
            raw_query = st.text_input(
                "Search",
                placeholder="IPL, Bitcoin, NVIDIA, Virat Kohli…",
                label_visibility="collapsed",
            )
            s_col, c_col = st.columns([4, 1])
            with s_col:
                do_search = st.form_submit_button(
                    "🔍 Search", use_container_width=True, type="primary"
                )
            with c_col:
                do_clear = st.form_submit_button("✕", use_container_width=True)

        # Process form results outside the form context
        if do_search:
            q = raw_query.strip()
            if q:
                st.session_state.search_query = q
                # Don't change selected_topic — preserve context
                if db:
                    db.log_search(q)
                st.rerun()
            else:
                st.toast("Please enter a search term.", icon="💡")

        if do_clear:
            st.session_state.search_query = ""
            st.rerun()

        # Active search indicator
        active_q = st.session_state.get("search_query", "")
        if active_q:
            st.markdown(
                f'<div style="font-size:0.74rem;color:#22d3ee;margin:0.3rem 0 0;">'
                f'🔍 &nbsp;<strong>{html.escape(active_q[:40])}</strong></div>',
                unsafe_allow_html=True,
            )
            if st.button("✕ Clear Search", use_container_width=True, key="btn_clr_active"):
                st.session_state.search_query = ""
                st.rerun()

        # ── Quick-search Chips ────────────────────────────────────────
        st.markdown(
            '<div style="font-size:0.63rem;color:#475569;font-weight:600;'
            'letter-spacing:0.08em;text-transform:uppercase;'
            'margin:0.7rem 0 0.35rem">⚡ Quick Search</div>',
            unsafe_allow_html=True,
        )

        chip_cols = st.columns(3)
        for i, chip in enumerate(SUGGESTED_SEARCHES):
            if chip_cols[i % 3].button(
                chip, key=f"chip_{chip}", use_container_width=True
            ):
                st.session_state.search_query = chip
                if db:
                    db.log_search(chip)
                st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Controls ──────────────────────────────────────────────────
        st.markdown(
            '<div style="font-size:0.7rem;font-weight:700;color:#475569;'
            'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:0.5rem">'
            "🎛️ Controls</div>",
            unsafe_allow_html=True,
        )

        max_articles = st.slider(
            "Articles to fetch",
            min_value=5, max_value=30,
            value=st.session_state.get("max_articles", 10),
            step=5,
            key="slider_max",
        )
        st.session_state.max_articles = max_articles

        summary_mode = st.selectbox(
            "Default Summary Mode",
            options=["standard", "anchor", "bullet", "headline"],
            format_func=lambda x: SUMMARY_MODE_LABELS.get(x, x),
            index=["standard", "anchor", "bullet", "headline"].index(
                st.session_state.get("global_mode", "standard")
            ),
            key="sel_global_mode",
        )
        st.session_state.global_mode = summary_mode

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Action Buttons ────────────────────────────────────────────
        refresh = st.button(
            "🔄 Refresh Feed",
            use_container_width=True,
            type="primary",
            key="btn_refresh",
        )

        # ── DB Stats ──────────────────────────────────────────────────
        if db is not None:
            with st.expander("📊 Database Stats", expanded=False):
                try:
                    stats = db.get_stats()
                    render_stat_row("Total articles", str(stats.get("total_articles", 0)), "indigo")
                    render_stat_row("Summarised",     str(stats.get("summarised", 0)), "green")
                    render_stat_row("Searches logged",str(stats.get("search_count", 0)))
                    render_stat_row("DB size",        f"{stats.get('db_size_mb', 0):.2f} MB")

                    if stats.get("by_sentiment"):
                        st.markdown(
                            '<p style="font-size:0.7rem;color:#475569;margin:0.5rem 0 0.25rem">'
                            "Sentiment breakdown:</p>",
                            unsafe_allow_html=True,
                        )
                        for sent, cnt in stats["by_sentiment"].items():
                            emojis = {"Positive": "🟢", "Neutral": "🟡", "Negative": "🔴"}
                            render_stat_row(f"{emojis.get(sent,'')} {sent}", str(cnt))

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Purge 7d+", use_container_width=True, key="btn_purge"):
                            deleted = db.purge_old_articles(keep_days=7)
                            st.toast(f"Purged {deleted} old articles")
                    with col2:
                        if st.button("VACUUM", use_container_width=True, key="btn_vacuum"):
                            db.vacuum()
                            st.toast("Database vacuumed ✓")
                except Exception as exc:
                    st.caption(f"Stats unavailable: {exc}")

        # ── Footer ────────────────────────────────────────────────────
        st.markdown(
            '<div style="text-align:center;padding-top:1.5rem">'
            '<p style="font-size:0.65rem;color:#1e293b">AI News Agent · v1.0 · Gemini powered</p>'
            "</div>",
            unsafe_allow_html=True,
        )

    return {
        "selected_topic":    st.session_state.get("selected_topic", "Top Headlines"),
        "topic_fetch_type":  st.session_state.get("topic_fetch_type",  "headlines"),
        "topic_fetch_query": st.session_state.get("topic_fetch_query", ""),
        "max_articles":      max_articles,
        "summary_mode":      summary_mode,
        "search_query":      st.session_state.get("search_query", ""),
        "refresh":           refresh,
    }


def _select_category(label: str, fetch_type: str, query: str) -> None:
    """
    Internal helper: writes category selection into session_state and reruns.
    Clears any active free-text search so topic mode takes over.
    """
    st.session_state.selected_topic    = label
    st.session_state.topic_fetch_type  = fetch_type
    st.session_state.topic_fetch_query = query
    st.session_state.search_query      = ""
    # Reset cache-tracking so app.py re-fetches immediately
    st.session_state.pop("_last_topic",      None)
    st.session_state.pop("_last_fetch_type", None)
    st.rerun()


# ─────────────────────────────────────────────────────────────────────
# Main Article Grid
# ─────────────────────────────────────────────────────────────────────

def render_article_grid(
    articles: list[dict],
    summarizer=None,
    db=None,
    n_cols: int = 2,
) -> None:
    """
    Renders articles in an n_cols grid.
    Each cell gets a full article card + summary expander.
    """
    if not articles:
        render_empty_state(
            "📭",
            "No articles found",
            "Try refreshing or selecting a different topic.",
        )
        return

    cols = st.columns(n_cols, gap="large")
    for idx, article in enumerate(articles):
        with cols[idx % n_cols]:
            render_article_card(
                article=article,
                summarizer=summarizer,
                db=db,
                show_summary_controls=True,
            )


def render_search_results(
    articles: list[dict],
    query: str,
    summarizer=None,
    db=None,
) -> None:
    """Renders free-text search results with header + grid."""
    st.markdown(
        search_results_header_html(query, len(articles)),
        unsafe_allow_html=True,
    )

    if not articles:
        # Show helpful no-result state with suggestions
        render_empty_state(
            "🔍",
            f'No results for "{query}"',
            "Try different keywords — or pick one from Quick Search below.",
        )
        # Suggest related quick searches as buttons
        st.markdown(
            '<div style="margin-top:1rem;font-size:0.78rem;color:#475569;">'
            "Try these instead:</div>",
            unsafe_allow_html=True,
        )
        suggestions = ["IPL", "Bitcoin", "NVIDIA", "ChatGPT", "Virat Kohli", "Sensex"]
        cols = st.columns(3)
        for i, s in enumerate(suggestions):
            if cols[i % 3].button(s, key=f"sr_sugg_{s}", use_container_width=True):
                st.session_state.search_query = s
                st.rerun()
    else:
        render_article_grid(articles, summarizer=summarizer, db=db)


# ─────────────────────────────────────────────────────────────────────
# Trending Panel (right column)
# ─────────────────────────────────────────────────────────────────────

def render_trending_panel(articles: list[dict]) -> None:
    """
    Renders the 'Trending Now' compact card list.
    Typically placed in a narrow right column.
    """
    render_section_header("🔥 Trending Now")

    if not articles:
        render_empty_state("📭", "No trending articles", "Fetch some news first.")
        return

    trending_html = "".join(
        compact_card_html(a, i + 1) for i, a in enumerate(articles[:8])
    )
    st.markdown(trending_html, unsafe_allow_html=True)


def render_topic_summary_panel(articles: list[dict]) -> None:
    """
    Renders a quick topic breakdown badge list.
    Placed below trending panel.
    """
    if not articles:
        return

    render_section_header("📊 Topic Mix")

    from collections import Counter
    topic_counts = Counter(a.get("topic_label", "General") for a in articles)

    for topic, count in topic_counts.most_common(6):
        icon = TOPIC_ICONS.get(topic, "📰")
        grad = TOPIC_GRADIENTS.get(topic, "")
        pct  = round(count / len(articles) * 100)
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;padding:5px 0;'
            f'border-bottom:1px solid rgba(255,255,255,0.05)">'
            f'<span style="font-size:0.85rem">{icon}</span>'
            f'<span style="flex:1;font-size:0.78rem;color:#94a3b8">{html.escape(topic)}</span>'
            f'<span style="font-size:0.72rem;color:#6366f1;font-weight:600">{count}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────
# History Tab
# ─────────────────────────────────────────────────────────────────────

def render_history_tab(db=None) -> None:
    """Renders the search history tab content."""
    if db is None:
        render_empty_state("🗄️", "Database not connected", "History unavailable.")
        return

    render_section_header("🕐 Recent Searches")

    history = db.get_search_history(limit=30)
    if not history:
        render_empty_state("🕐", "No searches yet", "Your search history will appear here.")
        return

    history_html = "".join(
        history_row_html(
            h.get("query", ""),
            h.get("results_count", 0),
            h.get("created_at", ""),
        )
        for h in history
    )
    st.markdown(history_html, unsafe_allow_html=True)

    # Re-run popular searches
    st.markdown("<br>", unsafe_allow_html=True)
    render_section_header("⭐ Most Searched")
    popular = db.get_popular_searches(limit=10)
    if popular:
        for p in popular:
            q   = p.get("query", "")
            cnt = p.get("count", 0)
            if st.button(
                f"🔍 {q}  ·  {cnt}×",
                key=f"pop_{q}",
                use_container_width=False,
            ):
                st.session_state.search_query = q
                if db:
                    db.log_search(q)
                st.rerun()

    if st.button("🗑️ Clear All History", key="btn_clr_hist"):
        db.clear_search_history()
        st.toast("Search history cleared ✓")
        st.rerun()
