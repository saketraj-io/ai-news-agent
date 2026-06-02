"""
ui/components.py
────────────────
Pure HTML/Streamlit component functions.
Each function is self-contained with no side-effects outside rendering.

HTML generators   — return strings, called from layouts.py
Streamlit renders — call st.* directly (render_ prefix)
"""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from typing import Optional

import streamlit as st

from ui.styles import (
    TOPIC_GRADIENTS,
    TOPIC_ICONS,
    SENTIMENT_CONFIG,
    SUMMARY_MODE_LABELS,
)


# ─────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────

def _time_ago(published_at) -> str:
    """Returns a human-readable relative time string."""
    if not published_at:
        return "Recently"
    try:
        if isinstance(published_at, str):
            from utils.helpers import parse_date
            dt = parse_date(published_at)
        else:
            dt = published_at
        if dt is None:
            return "Recently"
        # Make UTC-aware for comparison
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(tz=timezone.utc) - dt
        s = int(diff.total_seconds())
        if s < 60:        return "just now"
        if s < 3600:      return f"{s // 60}m ago"
        if s < 86400:     return f"{s // 3600}h ago"
        if s < 604800:    return f"{s // 86400}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return "Recently"


# ─────────────────────────────────────────────────────────────────────
# HTML generators
# ─────────────────────────────────────────────────────────────────────

def sentiment_badge_html(sentiment: Optional[str]) -> str:
    """Returns an HTML badge for a sentiment label."""
    if not sentiment or sentiment not in SENTIMENT_CONFIG:
        return ""
    cfg = SENTIMENT_CONFIG[sentiment]
    return (
        f'<span class="badge {cfg["cls"]}">'
        f'{cfg["emoji"]} {html.escape(sentiment)}'
        f"</span>"
    )


def tags_html(tags: list[str], max_tags: int = 4) -> str:
    """Returns HTML pill tags from a list of tag strings."""
    if not tags:
        return ""
    pills = "".join(
        f'<span class="tag-pill">#{html.escape(t)}</span>'
        for t in tags[:max_tags]
    )
    return pills


def article_card_html(article: dict) -> str:
    """
    Generates the full HTML for a news article card.
    article is a plain dict (from Article.to_dict() or DB row).
    """
    title   = html.escape(article.get("title", "Untitled")[:120])
    desc    = html.escape((article.get("description") or "")[:220])
    url     = article.get("url", "#")
    source  = html.escape(article.get("source_name", "Unknown")[:30])
    topic   = article.get("topic_label") or article.get("category", "General")
    img_url = article.get("image_url") or ""
    sent    = article.get("sentiment", "")
    tags    = article.get("tags") or []
    time_s  = _time_ago(article.get("published_at"))
    icon    = TOPIC_ICONS.get(topic, "📰")
    grad    = TOPIC_GRADIENTS.get(topic, TOPIC_GRADIENTS["General"])

    # Ensure HTTPS — browsers block mixed-content HTTP images on HTTPS pages
    if img_url and img_url.startswith("http://"):
        img_url = "https://" + img_url[7:]

    # Image section — referrerpolicy=no-referrer bypasses hotlink protection
    # on most news CDNs. onerror swaps to the gradient fallback immediately.
    if img_url:
        img_html = (
            f'<img src="{html.escape(img_url)}" '
            f'referrerpolicy="no-referrer" '
            f'crossorigin="anonymous" '
            f'loading="lazy" alt="" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;" '
            f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" '
            f'/>'
            f'<div class="a-img-fallback" style="display:none;background:{grad}">{icon}</div>'
        )
    else:
        img_html = (
            f'<div class="a-img-fallback" style="background:{grad}">{icon}</div>'
        )

    badge  = sentiment_badge_html(sent)
    t_html = tags_html(tags)
    footer = badge + t_html

    return f"""
<div class="a-card">
  <div class="a-img">
    {img_html}
    <span class="a-cat">{html.escape(topic)}</span>
  </div>
  <div class="a-body">
    <div class="a-meta">
      <span class="a-source">{source}</span>
      <span class="a-dot">·</span>
      <span class="a-time">{time_s}</span>
    </div>
    <div class="a-title"><a href="{html.escape(url)}" target="_blank">{title}</a></div>
    <p class="a-desc">{desc}</p>
    <div class="a-footer">{footer}</div>
  </div>
</div>
"""


def compact_card_html(article: dict, rank: int) -> str:
    """Generates a compact trending card (index + title + source)."""
    title  = html.escape((article.get("title") or "")[:90])
    source = html.escape(article.get("source_name", "")[:25])
    url    = article.get("url", "#")
    return f"""
<a href="{html.escape(url)}" target="_blank" style="text-decoration:none;">
  <div class="cc-wrap">
    <span class="cc-num">0{rank}</span>
    <div>
      <div class="cc-title">{title}</div>
      <div class="cc-src">{source}</div>
    </div>
  </div>
</a>
"""


def breaking_ticker_html(articles: list[dict]) -> str:
    """
    Generates the animated breaking-news ticker HTML.
    Duplicates items so the animation loops seamlessly.
    """
    if not articles:
        return ""

    items = [
        f'<span class="ticker-item"><a href="{html.escape(a.get("url","#"))}" target="_blank">'
        f'{html.escape((a.get("title") or "")[:80])}'
        f'</a></span>'
        f'<span class="ticker-sep"> ◆ </span>'
        for a in articles[:12]
    ]
    content = "".join(items)
    # Duplicate for seamless loop
    content_double = content + content

    return f"""
<div class="ticker-wrap">
  <div class="ticker-label">
    <span class="ticker-dot-live"></span>BREAKING
  </div>
  <div class="ticker-track">
    <div class="ticker-content">{content_double}</div>
  </div>
</div>
"""


def skeleton_card_html() -> str:
    """Returns HTML for a shimmer skeleton loading card."""
    return """
<div class="sk-card">
  <div class="sk-img skeleton"></div>
  <div class="sk-body">
    <div class="sk-line sk-meta skeleton"></div>
    <div class="sk-line sk-title skeleton"></div>
    <div class="sk-line sk-d1 skeleton"></div>
    <div class="sk-line sk-d2 skeleton"></div>
    <div class="sk-line sk-d3 skeleton"></div>
  </div>
</div>
"""


def empty_state_html(icon: str, title: str, subtitle: str = "") -> str:
    """Returns HTML for an empty / no-results state."""
    sub = f'<p class="empty-sub">{html.escape(subtitle)}</p>' if subtitle else ""
    return f"""
<div class="empty-state">
  <div class="empty-icon">{icon}</div>
  <div class="empty-title">{html.escape(title)}</div>
  {sub}
</div>
"""


def search_results_header_html(query: str, count: int) -> str:
    """Returns HTML banner for search results."""
    return f"""
<div class="search-header">
  🔍 Results for <span class="search-q">"{html.escape(query)}"</span>
  <span class="search-count">{count} article{"s" if count != 1 else ""} found</span>
</div>
"""


def history_row_html(query: str, count: int, created_at: str) -> str:
    """One search history row."""
    try:
        from utils.helpers import parse_date
        dt = parse_date(created_at)
        t_str = dt.strftime("%b %d, %H:%M") if dt else created_at[:16]
    except Exception:
        t_str = created_at[:16]
    return (
        f'<div class="hist-row">'
        f'<span class="hist-q">🔍 {html.escape(query)}</span>'
        f'<span class="hist-cnt">{count} results</span>'
        f'<span class="hist-t">{html.escape(t_str)}</span>'
        f'</div>'
    )


def api_status_html(label: str, ok: bool) -> str:
    cls = "api-ok" if ok else "api-miss"
    icon = "✓" if ok else "✗"
    return (
        f'<div class="api-status {cls}">'
        f'<span class="api-dot"></span>'
        f'{icon} {html.escape(label)}'
        f"</div>"
    )


def section_header_html(title: str, count: Optional[int] = None) -> str:
    cnt = f'<span class="sec-count">{count} articles</span>' if count is not None else ""
    return (
        f'<div class="sec-header">'
        f'<span class="sec-dot"></span>'
        f'<span class="sec-title">{html.escape(title)}</span>'
        f'{cnt}'
        f"</div>"
    )


# ─────────────────────────────────────────────────────────────────────
# Streamlit renderers
# ─────────────────────────────────────────────────────────────────────

def render_page_header(topic: str, article_count: int) -> None:
    """Renders the hero header with live dot and topic context."""
    icon = TOPIC_ICONS.get(topic, "📰")
    now  = datetime.now(tz=timezone.utc).strftime("%b %d, %Y  %H:%M UTC")
    st.markdown(
        f"""
<div class="page-header">
  <div class="header-brand">
    <span class="header-icon">🤖</span>
    <h1 class="header-title">AI News Agent</h1>
  </div>
  <p class="header-sub">
    <span class="live-dot"></span>
    AI-powered news intelligence · {html.escape(topic)} · {article_count} stories
  </p>
  <div class="header-meta">
    <span class="header-badge">⏱ {now}</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_breaking_ticker(articles: list[dict]) -> None:
    """Renders the animated breaking news ticker."""
    if articles:
        st.markdown(breaking_ticker_html(articles), unsafe_allow_html=True)


def render_skeleton_grid(count: int = 4, cols: int = 2) -> None:
    """Renders a grid of skeleton loading cards."""
    columns = st.columns(cols)
    for i in range(count):
        with columns[i % cols]:
            st.markdown(skeleton_card_html(), unsafe_allow_html=True)


def render_article_card(
    article: dict,
    summarizer=None,
    db=None,
    show_summary_controls: bool = True,
) -> None:
    """
    Renders a complete article card (HTML visual + Streamlit summary expander).

    Args:
        article:              Article dict (from Article.to_dict() or DB)
        summarizer:           ArticleSummarizer instance (optional)
        db:                   NewsDatabase instance (optional, used to cache summaries)
        show_summary_controls: Whether to show the summary expander
    """
    article_id = article.get("id", "")
    title      = article.get("title", "")
    url        = article.get("url", "#")
    text       = article.get("content") or article.get("description") or ""

    # ── Visual card ───────────────────────────────────────────────────
    st.markdown(article_card_html(article), unsafe_allow_html=True)

    # ── Actions row ───────────────────────────────────────────────────
    btn_col, link_col = st.columns([1, 1])
    with link_col:
        st.link_button("↗ Read Full Article", url, use_container_width=True)

    # ── AI Summary expander ───────────────────────────────────────────
    if show_summary_controls and summarizer is not None:
        with st.expander("🤖 AI Summary", expanded=False):
            render_summary_section(
                article_id=article_id,
                title=title,
                text=text,
                summarizer=summarizer,
                db=db,
            )


def render_summary_section(
    article_id: str,
    title: str,
    text: str,
    summarizer,
    db=None,
) -> None:
    """
    Renders the AI summary generation UI inside an expander.
    Uses session_state to cache generated summaries across reruns.
    """
    from services.summarizer import SummaryMode

    state_key = f"sum_{article_id}"

    # Try loading from DB first (persisted summaries)
    if state_key not in st.session_state and db is not None and article_id:
        mode_val = st.session_state.get("global_mode", "standard")
        persisted = db.get_summary(article_id, mode_val)
        if persisted:
            st.session_state[state_key] = {
                "text": persisted,
                "mode": mode_val,
                "ok": True,
                "from_db": True,
            }

    # ── Controls row ──────────────────────────────────────────────────
    c1, c2, c3 = st.columns([3, 1.2, 1.2])
    with c1:
        mode_val = st.selectbox(
            "Mode",
            options=["standard", "anchor", "bullet", "headline"],
            format_func=lambda x: SUMMARY_MODE_LABELS.get(x, x),
            index=["standard", "anchor", "bullet", "headline"].index(
                st.session_state.get("global_mode", "standard")
            ),
            key=f"sel_mode_{article_id}",
            label_visibility="collapsed",
        )
    with c2:
        gen_clicked = st.button(
            "✨ Generate",
            key=f"gen_{article_id}",
            use_container_width=True,
            type="primary",
        )
    with c3:
        regen_clicked = st.button(
            "🔄 Clear",
            key=f"clr_{article_id}",
            use_container_width=True,
        )

    # ── Handle actions ────────────────────────────────────────────────
    if regen_clicked:
        st.session_state.pop(state_key, None)
        st.rerun()

    if gen_clicked:
        if not text.strip():
            st.warning("No article text available to summarize.")
        else:
            with st.spinner(f"Generating {SUMMARY_MODE_LABELS.get(mode_val, mode_val)} summary…"):
                result = summarizer.summarize_text(
                    text=text,
                    title=title,
                    article_id=article_id,
                    mode=SummaryMode(mode_val),
                    force_refresh=True,
                )
            if result.ok:
                st.session_state[state_key] = {
                    "text": result.summary,
                    "mode": mode_val,
                    "ok": True,
                    "from_db": False,
                }
                # Persist to DB
                if db and article_id:
                    db.save_summary(article_id, mode_val, result.summary, result.model_used)
            else:
                st.session_state[state_key] = {
                    "text": result.error or "Failed to generate summary.",
                    "mode": mode_val,
                    "ok": False,
                    "from_db": False,
                }
            st.rerun()

    # ── Display cached summary ────────────────────────────────────────
    if state_key in st.session_state:
        cached = st.session_state[state_key]
        _render_summary_display(
            text=cached["text"],
            mode=cached["mode"],
            ok=cached["ok"],
            from_db=cached.get("from_db", False),
        )
    else:
        st.markdown(
            '<p style="color:var(--text-3);font-size:0.82rem;margin:0.5rem 0 0;">'
            "Choose a mode and click Generate to create an AI summary.</p>",
            unsafe_allow_html=True,
        )


def _render_summary_display(text: str, mode: str, ok: bool, from_db: bool = False) -> None:
    """Renders the formatted summary inside the summary box."""
    if not ok:
        st.warning(f"⚠️ {text}")
        return

    mode_label = SUMMARY_MODE_LABELS.get(mode, mode.title())
    db_badge   = ' <span style="font-size:0.65rem;color:var(--text-3)">· cached</span>' if from_db else ""

    if mode == "headline":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        h_line = lines[0] if lines else text
        s_line = lines[1] if len(lines) > 1 else ""
        body = (
            f'<div class="sum-headline-h">{html.escape(h_line)}</div>'
            + (f'<div class="sum-headline-s">{html.escape(s_line)}</div>' if s_line else "")
        )

    elif mode == "bullet":
        lines = [l.strip().lstrip("•").strip() for l in text.splitlines() if l.strip()]
        items = "".join(f"<li>{html.escape(l)}</li>" for l in lines)
        body  = f'<ul class="sum-bullet" style="margin:0;padding-left:1.4em">{items}</ul>'

    elif mode == "anchor":
        body = f'<div class="sum-anchor">{html.escape(text)}</div>'

    else:  # standard
        body = f'<span style="color:var(--text-1)">{html.escape(text)}</span>'

    st.markdown(
        f"""
<div class="sum-box">
  <div class="sum-mode-label">🤖 {html.escape(mode_label)}{db_badge}</div>
  {body}
</div>
""",
        unsafe_allow_html=True,
    )


def render_stat_row(label: str, value: str, cls: str = "") -> None:
    """Renders a single stat row in the sidebar."""
    st.markdown(
        f'<div class="stat-row">'
        f'<span class="stat-lbl">{html.escape(label)}</span>'
        f'<span class="stat-val {cls}">{html.escape(str(value))}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_api_status(label: str, ok: bool) -> None:
    st.markdown(api_status_html(label, ok), unsafe_allow_html=True)


def render_empty_state(icon: str, title: str, subtitle: str = "") -> None:
    st.markdown(empty_state_html(icon, title, subtitle), unsafe_allow_html=True)


def render_section_header(title: str, count: Optional[int] = None) -> None:
    st.markdown(section_header_html(title, count), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# Top-bar search (shown when sidebar may be collapsed)
# ─────────────────────────────────────────────────────────────────────

def render_topbar_search(db=None) -> None:
    """
    Renders a compact search bar + category chip strip directly inside
    the main content area.

    The container has CSS class ``topbar-search`` which is:
      • display:none   on screens > 1024 px  (sidebar visible → redundant)
      • display:flex   on screens ≤ 1024 px  (sidebar collapsed → needed)

    This ensures search is ALWAYS reachable regardless of sidebar state.
    """
    from ui.layouts import SIDEBAR_CATEGORIES, SUGGESTED_SEARCHES

    # ── Outer wrapper (CSS hides/shows via @media) ─────────────────
    st.markdown('<div class="topbar-search">', unsafe_allow_html=True)

    # ── Inner layout: label | search form | refresh ─────────────────
    lbl_col, form_col, btn_col = st.columns([1.4, 6, 1.2])

    with lbl_col:
        st.markdown(
            '<div class="topbar-label" style="padding-top:0.55rem">🔍 Search</div>',
            unsafe_allow_html=True,
        )

    with form_col:
        with st.form("topbar_search_form", clear_on_submit=False):
            q_col, s_col, c_col = st.columns([7, 1.5, 1])
            with q_col:
                raw = st.text_input(
                    "Topbar search",
                    placeholder="IPL, Bitcoin, NVIDIA, Virat Kohli…",
                    label_visibility="collapsed",
                )
            with s_col:
                do_search = st.form_submit_button(
                    "Search", use_container_width=True, type="primary"
                )
            with c_col:
                do_clear = st.form_submit_button("✕", use_container_width=True)

        if do_search and raw.strip():
            st.session_state.search_query = raw.strip()
            if db:
                try:
                    db.log_search(raw.strip())
                except Exception:
                    pass
            st.rerun()

        if do_clear:
            st.session_state.search_query = ""
            st.rerun()

    with btn_col:
        if st.button(
            "🔄 Refresh",
            key="topbar_refresh",
            use_container_width=True,
            type="primary",
        ):
            # Signal refresh via session_state flag; app.py checks it
            st.session_state["_topbar_refresh"] = True
            st.rerun()

    # ── Category chip row ────────────────────────────────────────────
    st.markdown(
        '<div style="width:100%;margin-top:0.55rem;display:flex;'
        'gap:6px;flex-wrap:wrap;align-items:center;">'
        '<span style="font-size:0.65rem;color:#475569;font-weight:700;'
        'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap">'
        "Categories:</span>",
        unsafe_allow_html=True,
    )

    current = st.session_state.get("selected_topic", "Top Headlines")
    chip_cols = st.columns(len(SIDEBAR_CATEGORIES))
    for idx, (icon, label, fetch_type, query) in enumerate(SIDEBAR_CATEGORIES):
        active_style = (
            "background:rgba(99,102,241,0.18);border-color:rgba(99,102,241,0.5);"
            "color:#818cf8;font-weight:700;"
            if label == current
            else ""
        )
        # Render as a button so it's interactive
        with chip_cols[idx]:
            if st.button(
                f"{icon}",
                key=f"topbar_cat_{label}",
                use_container_width=True,
                help=label,
            ):
                st.session_state.selected_topic    = label
                st.session_state.topic_fetch_type  = fetch_type
                st.session_state.topic_fetch_query = query
                st.session_state.search_query      = ""
                st.session_state.pop("_last_topic",      None)
                st.session_state.pop("_last_fetch_type", None)
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)  # close .topbar-search
