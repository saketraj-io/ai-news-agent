"""
ui/styles.py
────────────
Complete dark-theme CSS for the AI News Agent dashboard.
Call inject_css() once at the top of app.py.

Design system:
  Palette  — Deep navy-black bg, indigo/cyan accents, semantic sentiment colours
  Type     — Inter (body) + Space Grotesk (headings/data)
  Cards    — Glassmorphism with backdrop-blur, hover lift + glow
  Ticker   — CSS infinite-scroll animation, pause-on-hover
  Skeleton — Shimmer loading placeholders
  Badges   — Pill shapes with colour-coded sentiment glow
"""

from __future__ import annotations
import streamlit as st


# ─────────────────────────────────────────────────────────────────────
# Design token maps referenced from Python code
# ─────────────────────────────────────────────────────────────────────

TOPIC_GRADIENTS: dict[str, str] = {
    "Artificial Intelligence": "linear-gradient(135deg,#6366f1 0%,#a855f7 100%)",
    "Technology":              "linear-gradient(135deg,#0ea5e9 0%,#22d3ee 100%)",
    "Business & Finance":      "linear-gradient(135deg,#059669 0%,#10b981 100%)",
    "Science":                 "linear-gradient(135deg,#d946ef 0%,#a855f7 100%)",
    "Health":                  "linear-gradient(135deg,#16a34a 0%,#4ade80 100%)",
    "Politics":                "linear-gradient(135deg,#b91c1c 0%,#f97316 100%)",
    "Sports":                  "linear-gradient(135deg,#d97706 0%,#fbbf24 100%)",
    "Climate & Environment":   "linear-gradient(135deg,#15803d 0%,#22d3ee 100%)",
    "Entertainment":           "linear-gradient(135deg,#db2777 0%,#f97316 100%)",
    "World":                   "linear-gradient(135deg,#1e40af 0%,#7c3aed 100%)",
    "General":                 "linear-gradient(135deg,#374151 0%,#1f2937 100%)",
    "Top Headlines":           "linear-gradient(135deg,#6366f1 0%,#22d3ee 100%)",
}

TOPIC_ICONS: dict[str, str] = {
    "Top Headlines":           "🔥",
    "Artificial Intelligence": "🤖",
    "Technology":              "💻",
    "Business & Finance":      "📈",
    "Science":                 "🔬",
    "Health":                  "🏥",
    "Politics":                "🏛️",
    "Sports":                  "⚽",
    "Climate & Environment":   "🌍",
    "Entertainment":           "🎬",
    "World":                   "🌐",
    "General":                 "📰",
}

SENTIMENT_CONFIG: dict[str, dict] = {
    "Positive": {"cls": "badge-positive", "emoji": "🟢", "color": "#4ade80"},
    "Neutral":  {"cls": "badge-neutral",  "emoji": "🟡", "color": "#fbbf24"},
    "Negative": {"cls": "badge-negative", "emoji": "🔴", "color": "#f87171"},
}

SUMMARY_MODE_LABELS: dict[str, str] = {
    "standard": "📝 Standard",
    "anchor":   "📺 AI Anchor",
    "bullet":   "📋 Bullet Points",
    "headline": "📰 Headline",
}


# ─────────────────────────────────────────────────────────────────────
# Full CSS bundle
# ─────────────────────────────────────────────────────────────────────

_CSS = """
<style>
/* ══════════════════════════════════════════════════
   FONTS
══════════════════════════════════════════════════ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;600;700;800&display=swap');

/* ══════════════════════════════════════════════════
   DESIGN TOKENS
══════════════════════════════════════════════════ */
:root {
    --bg-app:      #05060f;
    --bg-sidebar:  #080b15;
    --bg-card:     rgba(13,18,35,0.92);
    --bg-glass:    rgba(255,255,255,0.025);
    --bg-input:    rgba(255,255,255,0.05);

    --border:      rgba(255,255,255,0.06);
    --border-card: rgba(255,255,255,0.05);
    --border-focus:rgba(99,102,241,0.50);

    --indigo:  #6366f1;
    --cyan:    #22d3ee;
    --violet:  #a855f7;
    --pink:    #ec4899;
    --gold:    #f59e0b;

    --positive: #22c55e;
    --neutral:  #eab308;
    --negative: #ef4444;

    --text-1: #f1f5f9;
    --text-2: #94a3b8;
    --text-3: #475569;

    --radius-sm: 6px;
    --radius-md: 12px;
    --radius-lg: 18px;
    --radius-xl: 24px;

    --shadow-md: 0 4px 20px rgba(0,0,0,0.45);
    --shadow-lg: 0 8px 40px rgba(0,0,0,0.55);
    --glow-in:   0 0 25px rgba(99,102,241,0.22);
    --glow-cy:   0 0 25px rgba(34,211,238,0.18);

    --ease: cubic-bezier(0.4,0,0.2,1);
    --trans: all 0.22s var(--ease);
}

/* ══════════════════════════════════════════════════
   BASE / STREAMLIT OVERRIDES
══════════════════════════════════════════════════ */
/* ── Main app container ── */
.stApp {
    background: var(--bg-app) !important;
    font-family: 'Inter', sans-serif !important;
}

/* ── App view block - enable scrolling ── */
[data-testid="stAppViewBlockContainer"] {
    display: flex !important;
    flex-direction: row !important;
    width: 100% !important;
    overflow: visible !important;
}
/* Hide only the non-essential header chrome */
#MainMenu, footer { visibility: hidden !important; }
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
.stDeployButton { display: none !important; }

/* Minimize Streamlit header chrome */
header[data-testid="stHeader"] {
    background:    var(--bg-sidebar)   !important;
    border-bottom: 1px solid var(--border) !important;
    backdrop-filter: none !important;
    height: auto !important;
    padding: 0.4rem 0.8rem !important;
    min-height: unset !important;
}

[data-testid="stMainBlockContainer"] {
    padding: 0 2.5rem 3rem !important;
    max-width: 1500px !important;
    overflow-y: auto !important;
    max-height: calc(100vh - 60px) !important;
}
[data-testid="stAppViewBlockContainer"] { 
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}

/* ── Sidebar — VISIBLE & RESPONSIVE ── */
[data-testid="stSidebar"],
.stSidebar,
section[data-testid="stSidebar"] {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border) !important;
    width: 280px !important;
    min-width: 280px !important;
    max-width: 280px !important;
    padding: 0 !important;
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    transform: translateX(0) !important;
    position: relative !important;
}
[data-testid="stSidebarContent"] { 
    padding: 1.25rem 0.9rem !important;
    overflow-y: auto !important;
    height: calc(100vh - 120px) !important;
    display: block !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar            { width:5px; height:5px; }
::-webkit-scrollbar-track      { background:transparent; }
::-webkit-scrollbar-thumb      { background:rgba(255,255,255,0.09); border-radius:3px; }
::-webkit-scrollbar-thumb:hover{ background:rgba(99,102,241,0.45); }

/* ── Typography overrides ── */
h1,h2,h3,h4,h5,h6 { font-family:'Space Grotesk',sans-serif !important; color:var(--text-1) !important; }
p { color: var(--text-2); }

/* ── Tabs ── */
[data-testid="stTabs"] [role="tablist"] {
    border-bottom: 1px solid var(--border);
    gap: 0;
    background: transparent;
}
[data-testid="stTabs"] [role="tab"] {
    color: var(--text-2) !important;
    font-weight: 500;
    font-size: 0.88rem;
    padding: 0.6rem 1.3rem;
    background: transparent !important;
    border-radius: var(--radius-sm) var(--radius-sm) 0 0;
    transition: var(--trans);
    border: none !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: var(--indigo) !important;
    border-bottom: 2px solid var(--indigo) !important;
    background: rgba(99,102,241,0.06) !important;
}
[data-testid="stTabs"] [role="tab"]:hover { color:var(--text-1) !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid var(--border-card) !important;
    border-radius: var(--radius-md) !important;
    background: var(--bg-glass) !important;
    margin: 0 !important;
}
[data-testid="stExpander"] summary {
    color: var(--text-2) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
}
[data-testid="stExpander"] summary:hover { color:var(--text-1) !important; }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] { padding:0.75rem !important; }

/* ── Buttons ── */
.stButton > button {
    background: var(--bg-glass) !important;
    color: var(--text-1) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.83rem !important;
    transition: var(--trans) !important;
    padding: 0.38rem 0.9rem !important;
}
.stButton > button:hover {
    background: rgba(99,102,241,0.12) !important;
    border-color: rgba(99,102,241,0.45) !important;
    transform: translateY(-1px);
    box-shadow: var(--glow-in);
}
.stButton > button[kind="primary"] {
    background: var(--indigo) !important;
    border-color: transparent !important;
    color: #fff !important;
}
.stButton > button[kind="primary"]:hover {
    background: #4f46e5 !important;
    box-shadow: var(--glow-in);
}

/* ── Link button ── */
[data-testid="stLinkButton"] > a {
    background: var(--bg-glass) !important;
    color: var(--text-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    transition: var(--trans) !important;
    padding: 0.38rem 0.9rem !important;
    text-decoration: none !important;
}
[data-testid="stLinkButton"] > a:hover {
    color: var(--cyan) !important;
    border-color: rgba(34,211,238,0.4) !important;
    background: rgba(34,211,238,0.06) !important;
}

/* ── Text inputs ── */
.stTextInput input {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    color: var(--text-1) !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.9rem !important;
    padding: 0.55rem 1rem !important;
    transition: var(--trans) !important;
}
.stTextInput input:focus {
    border-color: var(--indigo) !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.18) !important;
}
.stTextInput input::placeholder { color: var(--text-3) !important; }

/* ── Selectbox ── */
.stSelectbox [data-baseweb="select"] > div {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-1) !important;
    font-size: 0.85rem !important;
}
[data-baseweb="popover"] { background: #0d1117 !important; border: 1px solid var(--border) !important; }
[data-baseweb="menu"] li:hover { background: rgba(99,102,241,0.12) !important; }

/* ── Slider ── */
.stSlider [data-testid="stThumbValue"] { color:var(--indigo) !important; }
.stSlider [data-baseweb="slider"] div[role="slider"] { background:var(--indigo) !important; }

/* ── Metrics ── */
[data-testid="stMetricValue"] {
    color: var(--indigo) !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] { color: var(--text-3) !important; font-size:0.75rem !important; }

/* ── Divider ── */
hr { border-color: var(--border) !important; margin: 0.8rem 0 !important; }

/* ── Page header ── */
.page-header {
    background: linear-gradient(135deg, rgba(99,102,241,0.09) 0%, rgba(34,211,238,0.04) 100%);
    border: 1px solid rgba(99,102,241,0.14);
    border-radius: var(--radius-xl);
    padding: 1.2rem 1.8rem;
    margin-bottom: 1.2rem;
    margin-top: 0.5rem;
    position: relative;
    overflow: hidden;
}
.page-header::before {
    content:'';
    position:absolute; top:-80px; right:-80px;
    width:250px; height:250px;
    background: radial-gradient(circle, rgba(99,102,241,0.18) 0%, transparent 70%);
    pointer-events:none;
}
.page-header::after {
    content:'';
    position:absolute; bottom:-60px; left:30%;
    width:180px; height:180px;
    background: radial-gradient(circle, rgba(34,211,238,0.1) 0%, transparent 70%);
    pointer-events:none;
}
.header-brand { display:flex; align-items:center; gap:12px; margin-bottom:0.3rem; }
.header-icon  { font-size:2rem; line-height:1; }
.header-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.75rem;
    font-weight: 800;
    background: linear-gradient(135deg, #f1f5f9 30%, var(--cyan) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0; line-height:1;
}
.header-sub { color:var(--text-2); font-size:0.85rem; margin:0; }
.header-meta { display:flex; align-items:center; gap:14px; margin-top:0.6rem; }
.live-dot {
    display:inline-block; width:7px; height:7px;
    background:var(--positive); border-radius:50%;
    margin-right:5px;
    animation: pulse-dot 2.2s ease-in-out infinite;
}
.header-badge {
    font-size:0.7rem; font-weight:600; letter-spacing:0.08em;
    color:var(--text-3); text-transform:uppercase;
}
@keyframes pulse-dot {
    0%,100% { opacity:1; box-shadow:0 0 0 0 rgba(34,197,94,0.5); }
    50%      { opacity:0.8; box-shadow:0 0 0 5px rgba(34,197,94,0); }
}

/* ══════════════════════════════════════════════════
   BREAKING NEWS TICKER
══════════════════════════════════════════════════ */
.ticker-wrap {
    display:flex; align-items:center;
    background: rgba(99,102,241,0.07);
    border: 1px solid rgba(99,102,241,0.18);
    border-radius: var(--radius-md);
    overflow:hidden; height:42px; margin-bottom:1.25rem;
}
.ticker-label {
    background: var(--indigo);
    color:#fff;
    font-size:0.65rem; font-weight:700; letter-spacing:0.12em;
    text-transform:uppercase;
    padding:0 16px;
    height:100%; display:flex; align-items:center;
    white-space:nowrap; flex-shrink:0;
    gap:6px;
}
.ticker-dot-live {
    width:6px; height:6px; background:#fff; border-radius:50%;
    animation: pulse-dot 1.5s ease-in-out infinite;
}
.ticker-track { flex:1; overflow:hidden; position:relative; }
.ticker-content {
    display:inline-flex; gap:48px; white-space:nowrap;
    animation: ticker-roll 50s linear infinite;
    will-change: transform;
}
.ticker-content:hover { animation-play-state:paused; }
.ticker-item a { color:var(--text-2) !important; text-decoration:none !important; font-size:0.82rem; transition:color 0.2s; }
.ticker-item a:hover { color:var(--cyan) !important; }
.ticker-sep { color:var(--indigo); opacity:0.5; }
@keyframes ticker-roll {
    0%   { transform: translateX(0); }
    100% { transform: translateX(-50%); }
}

/* ══════════════════════════════════════════════════
   ARTICLE CARD
══════════════════════════════════════════════════ */
.a-card {
    background: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: var(--radius-lg);
    overflow:hidden;
    transition: transform 0.28s var(--ease), box-shadow 0.28s var(--ease), border-color 0.28s var(--ease);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    margin-bottom: 1.2rem;
    position: relative;
}
.a-card:hover {
    transform: translateY(-5px);
    box-shadow: var(--shadow-lg), var(--glow-in);
    border-color: rgba(99,102,241,0.3);
}
/* Image */
.a-img {
    position: relative;
    height: 195px;
    overflow: hidden;
    /* Always show a rich dark gradient so the area is never blank */
    background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 60%, #080b15 100%);
}
.a-img img {
    width: 100%; height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.45s var(--ease);
}
.a-card:hover .a-img img { transform: scale(1.06); }
.a-img-fallback {
    width: 100%; height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-size: 3.2rem;
    /* Layered gradient for depth */
    background: linear-gradient(135deg,
        rgba(99,102,241,0.25) 0%,
        rgba(8,11,21,0.85) 60%,
        rgba(15,20,40,0.95) 100%) !important;
    position: relative;
}
.a-img-fallback::after {
    content: "No Image";
    position: absolute;
    bottom: 10px;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(148,163,184,0.45);
    font-family: 'Inter', sans-serif;
}
.a-cat {
    position:absolute; top:11px; left:11px;
    background:rgba(5,6,15,0.72); backdrop-filter:blur(8px);
    color:var(--cyan); font-size:0.62rem; font-weight:700;
    letter-spacing:0.1em; text-transform:uppercase;
    padding:3px 9px; border-radius:20px;
    border:1px solid rgba(34,211,238,0.22);
}
/* Body */
.a-body { padding:1rem 1.15rem 0.9rem; }
.a-meta { display:flex; align-items:center; gap:7px; margin-bottom:0.45rem; }
.a-source { font-size:0.7rem; font-weight:700; color:var(--indigo); text-transform:uppercase; letter-spacing:0.06em; }
.a-dot    { color:var(--text-3); font-size:0.65rem; }
.a-time   { font-size:0.7rem; color:var(--text-3); }
.a-title  {
    font-family:'Space Grotesk',sans-serif;
    font-size:0.97rem; font-weight:600; color:var(--text-1);
    line-height:1.45; margin:0 0 0.45rem;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
}
.a-title a { color:var(--text-1) !important; text-decoration:none !important; }
.a-title a:hover { color:var(--indigo) !important; }
.a-desc {
    font-size:0.82rem; color:var(--text-2); line-height:1.55;
    margin:0 0 0.8rem;
    display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;
}
.a-footer { display:flex; align-items:center; gap:7px; flex-wrap:wrap; }
/* Compact card */
.cc-wrap { display:flex; gap:10px; padding:9px 0; border-bottom:1px solid var(--border); transition:var(--trans); }
.cc-wrap:hover .cc-title { color:var(--indigo) !important; }
.cc-num  { font-family:'Space Grotesk',sans-serif; font-size:1rem; font-weight:700; color:var(--text-3); min-width:20px; padding-top:2px; }
.cc-title { font-size:0.8rem; font-weight:500; color:var(--text-2); line-height:1.4; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; transition:color 0.2s; }
.cc-src   { font-size:0.67rem; color:var(--text-3); margin-top:3px; }

/* ══════════════════════════════════════════════════
   BADGES + TAGS
══════════════════════════════════════════════════ */
.badge {
    display:inline-flex; align-items:center; gap:4px;
    padding:3px 9px; border-radius:20px;
    font-size:0.68rem; font-weight:600; letter-spacing:0.04em;
    white-space:nowrap;
}
.badge-positive { background:rgba(34,197,94,0.1);  color:#4ade80; border:1px solid rgba(34,197,94,0.22); box-shadow:0 0 8px rgba(34,197,94,0.12); }
.badge-neutral  { background:rgba(234,179,8,0.1);  color:#fbbf24; border:1px solid rgba(234,179,8,0.22); }
.badge-negative { background:rgba(239,68,68,0.1);  color:#f87171; border:1px solid rgba(239,68,68,0.22); box-shadow:0 0 8px rgba(239,68,68,0.12); }
.tag-pill {
    display:inline-block; padding:2px 8px;
    background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);
    border-radius:20px; font-size:0.67rem; color:var(--text-3);
}

/* ══════════════════════════════════════════════════
   AI SUMMARY BOX
══════════════════════════════════════════════════ */
.sum-box {
    background:rgba(99,102,241,0.07);
    border:1px solid rgba(99,102,241,0.16);
    border-left: 3px solid var(--indigo);
    border-radius: var(--radius-md);
    padding:0.95rem 1.1rem;
    margin-top:0.6rem;
    font-size:0.875rem; color:var(--text-1); line-height:1.7;
}
.sum-mode-label {
    font-size:0.65rem; font-weight:700; color:var(--indigo);
    text-transform:uppercase; letter-spacing:0.1em;
    display:flex; align-items:center; gap:5px;
    margin-bottom:0.55rem;
}
.sum-headline-h { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:1rem; color:var(--text-1); margin-bottom:4px; }
.sum-headline-s { font-size:0.85rem; color:var(--text-2); }
.sum-anchor     { font-style:italic; color:var(--text-1); }
.sum-bullet li  { color:var(--text-1); margin-bottom:5px; }

/* ══════════════════════════════════════════════════
   SKELETON LOADER
══════════════════════════════════════════════════ */
@keyframes shimmer {
    0%   { background-position:200% 0; }
    100% { background-position:-200% 0; }
}
.skeleton {
    background:linear-gradient(90deg,rgba(255,255,255,0.04) 25%,rgba(255,255,255,0.09) 50%,rgba(255,255,255,0.04) 75%);
    background-size:200% 100%;
    animation:shimmer 1.7s ease-in-out infinite;
    border-radius:var(--radius-sm);
}
.sk-card { background:var(--bg-card); border:1px solid var(--border-card); border-radius:var(--radius-lg); overflow:hidden; margin-bottom:1.2rem; }
.sk-img  { height:185px; }
.sk-body { padding:1rem 1.15rem; }
.sk-line { margin-bottom:9px; border-radius:6px; }
.sk-title{ width:80%; height:15px; }
.sk-meta { width:40%; height:9px; margin-bottom:14px; }
.sk-d1   { width:100%; height:10px; }
.sk-d2   { width:65%;  height:10px; }
.sk-d3   { width:85%;  height:10px; }

/* ══════════════════════════════════════════════════
   SECTION HEADERS
══════════════════════════════════════════════════ */
.sec-header {
    display:flex; align-items:center; gap:8px;
    margin-bottom:0.9rem; padding-bottom:0.55rem;
    border-bottom:1px solid var(--border);
}
.sec-dot  { width:6px; height:6px; background:var(--indigo); border-radius:50%; box-shadow:var(--glow-in); flex-shrink:0; }
.sec-title { font-family:'Space Grotesk',sans-serif; font-size:0.82rem; font-weight:700; color:var(--text-1); text-transform:uppercase; letter-spacing:0.1em; }
.sec-count { font-size:0.72rem; color:var(--text-3); margin-left:auto; }

/* ══════════════════════════════════════════════════
   EMPTY STATE
══════════════════════════════════════════════════ */
.empty-state { text-align:center; padding:3.5rem 1.5rem; }
.empty-icon  { font-size:3.5rem; margin-bottom:1rem; opacity:0.7; }
.empty-title { font-family:'Space Grotesk',sans-serif; font-size:1.1rem; font-weight:600; color:var(--text-2); margin-bottom:0.4rem; }
.empty-sub   { font-size:0.83rem; color:var(--text-3); }

/* ══════════════════════════════════════════════════
   SIDEBAR STATS
══════════════════════════════════════════════════ */
.stat-row { display:flex; justify-content:space-between; align-items:center; padding:5px 0; border-bottom:1px solid var(--border); font-size:0.78rem; }
.stat-lbl { color:var(--text-3); }
.stat-val { color:var(--text-1); font-weight:600; font-family:'Space Grotesk',sans-serif; }
.stat-val.indigo { color:var(--indigo); }
.stat-val.green  { color:var(--positive); }
.stat-val.gold   { color:var(--gold); }

/* ══════════════════════════════════════════════════
   API STATUS
══════════════════════════════════════════════════ */
.api-status { display:flex; align-items:center; gap:8px; padding:7px 10px; border-radius:var(--radius-sm); margin-bottom:5px; font-size:0.78rem; }
.api-ok   { background:rgba(34,197,94,0.08);  border:1px solid rgba(34,197,94,0.2);  color:#4ade80; }
.api-miss { background:rgba(239,68,68,0.08);  border:1px solid rgba(239,68,68,0.2);  color:#f87171; }
.api-dot  { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
.api-ok   .api-dot { background:var(--positive); }
.api-miss .api-dot { background:var(--negative); }

/* ══════════════════════════════════════════════════
   NAV TOPIC BUTTON (sidebar)
══════════════════════════════════════════════════ */
.nav-active > button { 
    background:rgba(99,102,241,0.14) !important; 
    border-color:rgba(99,102,241,0.45) !important; 
    color:var(--indigo) !important;
    box-shadow:var(--glow-in);
}

/* ══════════════════════════════════════════════════
   SEARCH RESULTS HEADER
══════════════════════════════════════════════════ */
.search-header {
    display:flex; align-items:center; gap:10px; margin-bottom:1rem;
    padding:0.7rem 1rem;
    background:rgba(34,211,238,0.05); border:1px solid rgba(34,211,238,0.14);
    border-radius:var(--radius-md);
    font-size:0.83rem; color:var(--text-2);
}
.search-q { color:var(--cyan); font-weight:600; }
.search-count { margin-left:auto; color:var(--text-3); }

/* ══════════════════════════════════════════════════
   HISTORY ROW
══════════════════════════════════════════════════ */
.hist-row { display:flex; align-items:center; gap:10px; padding:7px 0; border-bottom:1px solid var(--border); font-size:0.8rem; color:var(--text-2); }
.hist-q   { flex:1; }
.hist-cnt { color:var(--indigo); font-weight:600; font-size:0.75rem; }
.hist-t   { color:var(--text-3); font-size:0.72rem; }

/* ══════════════════════════════════════════════════
   SIDEBAR TOGGLE — NATIVE STREAMLIT BUTTONS
   Both buttons are real, fully functional Streamlit
   elements. We only restyle them — no JS trickery.
══════════════════════════════════════════════════ */

/* ── Collapse button (inside the open sidebar, top-right) ── */
[data-testid="stSidebarCollapseButton"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: absolute !important;
    top: 0.8rem !important;
    right: 0.8rem !important;
    z-index: 100 !important;
    width: 2.2rem !important;
    height: 2.2rem !important;
}
[data-testid="stSidebarCollapseButton"] > button {
    background: rgba(99,102,241,0.15) !important;
    border: 1px solid rgba(99,102,241,0.35) !important;
    border-radius: 8px !important;
    color: #818cf8 !important;
    transition: all 0.25s ease !important;
    padding: 0 !important;
    width: 100% !important;
    height: 100% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 1.2rem !important;
}
[data-testid="stSidebarCollapseButton"] > button:hover {
    background: rgba(99,102,241,0.28) !important;
    border-color: rgba(99,102,241,0.60) !important;
    box-shadow: 0 0 14px rgba(99,102,241,0.30) !important;
    transform: none !important;
}

/* ── Hamburger toggle button (visible in header when sidebar is collapsed) ── */
[data-testid="collapsedControl"] {
    display:        flex !important;
    align-items:    center !important;
    justify-content: center !important;
    visibility:     visible !important;
    opacity:        1 !important;
    pointer-events: auto !important;

    position: fixed !important;
    top: 0.75rem !important;
    left: 1rem !important;
    z-index: 100 !important;

    width: 2.4rem !important;
    height: 2.4rem !important;
    background:    rgba(99,102,241,0.20) !important;
    border:        1px solid rgba(99,102,241,0.40) !important;
    border-radius: 8px !important;
    padding:       0 !important;
    cursor:        pointer !important;
    transition:    all 0.25s ease !important;
}
[data-testid="collapsedControl"]:hover {
    background:   rgba(99,102,241,0.35) !important;
    border-color: rgba(99,102,241,0.70) !important;
    box-shadow: 0 0 14px rgba(99,102,241,0.35) !important;
}
[data-testid="collapsedControl"] > button {
    background: transparent !important;
    border:     none !important;
    color:      #a5b4fc !important;
    box-shadow: none !important;
    padding:    0 !important;
    cursor:     pointer !important;
    display:    flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
    font-size: 1.4rem !important;
    transition: color 0.25s ease !important;
}
[data-testid="collapsedControl"] > button:hover {
    background: transparent !important;
    box-shadow: none !important;
    color:      #e0e7ff !important;
}
/* Hide text labels - show ONLY hamburger icon */
[data-testid="collapsedControl"]::after,
[data-testid="collapsedControl"]::before { 
    content: none !important; 
    display: none !important;
}
[data-testid="collapsedControl"] svg {
    width: 22px !important;
    height: 22px !important;
}

/* ══════════════════════════════════════════════════
   RESPONSIVE & LAYOUT FIXES
══════════════════════════════════════════════════ */

/* Ensure main content is properly spaced */
.block-container {
    padding-top: 0 !important;
}

/* Fix for content not being clipped or hidden */
.main {
    overflow: visible !important;
}

/* Responsive layout for smaller screens */
@media (max-width: 768px) {
    [data-testid="stMainBlockContainer"] {
        padding: 0 1.2rem 2rem !important;
    }
    
    [data-testid="stSidebar"] {
        width: 100% !important;
        max-width: 280px !important;
    }
}
</style>
"""


def inject_css() -> None:
    """Injects the full dark-theme CSS bundle into the Streamlit app."""
    st.markdown(_CSS, unsafe_allow_html=True)
