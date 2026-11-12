"""
Visual design — modeled on the owner's reference screens: true-black canvas, quiet grey hairlines,
pill-shaped inputs, a light pill primary button, and a muted green that only marks progress and selection.
"""
from __future__ import annotations

import html

import streamlit as st

BG = "#000000"
TEXT = "#F4F4F4"
MUTED = "#A1A1A1"
LINE = "#2B2B2B"
FIELD = "#3A3A3A"
GREEN = "#3D6B57"
GREEN_LT = "#5E9479"
ORANGE = "#F0884A"

CSS = f"""
<style>
html, body, [class*="css"], .stApp, button, input, textarea, select {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", Roboto, sans-serif !important;
}}
.stApp {{ background: {BG}; color: {TEXT}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.6rem; max-width: 760px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; color: {TEXT}; }}
p, li, label, .stMarkdown {{ color: {TEXT}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {MUTED} !important; }}

/* ---------- brand + progress ---------- */
.brand {{ display: flex; gap: .8rem; align-items: center; }}
.brand svg {{ width: 30px; height: 30px; flex: none; }}
.brand b {{ display: block; font-size: 1.35rem; font-weight: 600; line-height: 1.1; }}
.brand small {{ color: {MUTED}; font-size: .9rem; }}
.bars {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 1.1rem 0 1.2rem; }}
.bars span {{ height: 6px; border-radius: 6px; background: #2A2A2A; }}
.bars span.on {{ background: {GREEN}; }}
.steprow {{ display: flex; justify-content: space-between; align-items: center; color: {MUTED}; font-size: .95rem; }}
.steprow .lead {{ color: {TEXT}; letter-spacing: .04em; }}
.chip {{ display: inline-block; padding: .28rem .8rem; border-radius: 999px; background: #1C1C1C; color: {TEXT};
         font-size: .92rem; margin-right: .5rem; }}
.title {{ font-size: 2rem; font-weight: 650; margin: .4rem 0 .5rem; line-height: 1.2; }}
.sub {{ color: {MUTED}; font-size: 1.1rem; margin: 0 0 1.4rem; }}
.facts-line {{ display: flex; gap: .7rem; align-items: center; font-size: 1.15rem; margin: .55rem 0 .55rem 1rem; }}
.facts-line svg {{ width: 24px; height: 24px; flex: none; stroke: {TEXT}; }}
.qhead {{ display: flex; justify-content: space-between; align-items: center; margin: 1.6rem 0 .6rem; }}
.qhead b {{ font-size: 1.3rem; font-weight: 600; }}
.qhead span {{ color: {MUTED}; }}
.badge {{ padding: .3rem .8rem; border-radius: 999px; font-size: .95rem; }}
.badge.warn {{ background: #3A1B0C; color: {ORANGE}; }}
.badge.ok {{ background: #12261D; color: {GREEN_LT}; }}
.hint {{ color: {MUTED}; font-size: .95rem; margin-top: -.3rem; }}
.split {{ display: flex; justify-content: space-between; color: {MUTED}; font-size: .95rem; margin-top: -.6rem; }}
.bignum {{ font-size: 1.7rem; font-weight: 600; text-align: right; margin: -.2rem 0 -.6rem; }}
hr, [data-testid="stDivider"] {{ border-color: {LINE} !important; }}

/* ---------- inputs: pills ---------- */
[data-testid="stNumberInputContainer"], [data-testid="stTextInputRootElement"], .react-aria-ComboBox > div[role="group"],
.stDateInput div[data-baseweb="input"] {{
  border-radius: 999px !important; border: 1px solid {FIELD} !important; background: {BG} !important; min-height: 3.1rem;
}}
[data-testid="stNumberInputContainer"] input, [data-testid="stTextInputRootElement"] input {{
  background: transparent !important; font-size: 1.1rem; padding-left: 1.2rem; color: {TEXT};
}}
.react-aria-ComboBox > div[role="group"] {{ padding: 0 .9rem 0 1.1rem; align-items: center; }}
.react-aria-ComboBox input {{ background: transparent !important; font-size: 1.1rem !important; color: {TEXT} !important; }}
[data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {{ display: none; }}
label[data-testid="stWidgetLabel"] p {{ font-size: 1.02rem; color: #D8D8D8; }}
[data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p {{ font-size: 1.12rem !important; color: {TEXT}; }}
[data-testid="stRadio"] [role="radiogroup"] {{ gap: .55rem; }}

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button {{
  border-radius: 999px; border: 1px solid {FIELD}; background: {BG}; color: {TEXT}; min-height: 3rem;
}}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
  background: #ECECEC; color: #0A0A0A; border: none; font-size: 1.15rem; min-height: 3.6rem; font-weight: 500;
}}
.stButton > button[kind="primary"] p, .stDownloadButton > button[kind="primary"] p {{ color: #0A0A0A !important; font-size: 1.15rem; }}
.stButton > button[kind="primary"]:disabled p {{ color: #6E6E6E !important; }}
.stButton > button[kind="primary"]:hover {{ background: #FFFFFF; color: #000; }}
.stButton > button[kind="primary"]:disabled {{ background: #2A2A2A; color: #6E6E6E; }}
.stButton > button:focus-visible {{ outline: 2px solid {GREEN_LT}; outline-offset: 2px; }}
.stButton > button p, .stDownloadButton > button p {{ font-size: 1.02rem; }}
.st-key-nav_restart button, .st-key-nav_switch button {{
  border: none !important; background: transparent !important; color: #D8D8D8 !important; min-height: 2rem !important;
  font-size: .98rem;
}}

/* property-type cards */
[class*="st-key-type_"] button {{
  height: 150px; border-radius: 22px !important; border: 1px solid {LINE} !important; background: {BG} !important;
}}
[class*="st-key-type_"] button span[data-has-shortcut] {{ flex-direction: column; gap: .7rem; align-items: center; }}
[class*="st-key-type_"] button p {{ font-size: 1.25rem !important; }}
[class*="st-key-type_"] button span[data-testid="stIconMaterial"] {{ font-size: 2.2rem; }}
[class*="st-key-type_"] button:hover {{ border-color: #555 !important; }}

/* mode cards on the landing screen */
.modecard {{ border: 1px solid {LINE}; border-radius: 22px; padding: 1.4rem 1.4rem .4rem; height: 100%; }}
.modecard h3 {{ margin: 0 0 .3rem; font-size: 1.4rem; }}
.modecard .time {{ color: {GREEN_LT}; font-size: .95rem; }}
.modecard ul {{ color: {MUTED}; padding-left: 1.1rem; margin: .8rem 0 1rem; }}

/* segmented control: two halves, filled selection */
.stElementContainer:has([data-testid="stButtonGroup"]), [data-testid="stButtonGroup"] {{ width: 100% !important; }}
[data-testid="stButtonGroup"] [role="radiogroup"] {{ width: 100% !important; max-width: none !important; display: flex; gap: 4px; flex-wrap: nowrap; }}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {{
  flex: 1; border: none !important; background: transparent !important; border-radius: 999px !important;
  min-height: 3.1rem;
}}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] p {{ color: {MUTED}; font-size: 1.08rem; }}
[data-testid="stButtonGroup"] button[data-selected="true"] {{ background: #262626 !important; }}
[data-testid="stButtonGroup"] button[data-selected="true"] p {{ color: {TEXT}; }}

/* slider: white thumb on dark track */
[data-testid="stSliderThumbValue"], [data-testid="stSliderTickBar"] {{ display: none; }}
[data-testid="stSlider"] [data-orientation="horizontal"] > div:first-child {{ height: 44px !important; border-radius: 999px;
  background: #1E1E1E !important; }}
[data-testid="stSlider"] div[style*="absolute"] {{ background: #F4F4F4 !important; width: 34px !important;
  height: 34px !important; border-radius: 50%; box-shadow: none !important; }}

/* expanders + bordered containers */
[data-testid="stExpander"] details {{ border: 1px solid {LINE}; border-radius: 22px; background: {BG}; }}
[data-testid="stExpander"] summary p {{ font-size: 1.08rem; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {LINE} !important; border-radius: 22px !important; }}

/* ---------- summary card ---------- */
.card {{ border: 1px solid {LINE}; border-radius: 26px; padding: 1.5rem 1.6rem 1.2rem; margin: .4rem 0 1.2rem; }}
.card .top {{ display: flex; justify-content: space-between; align-items: flex-start;
              border-bottom: 1px solid {LINE}; padding-bottom: 1.3rem; margin-bottom: 1.3rem; }}
.card .kicker {{ color: {MUTED}; letter-spacing: .06em; font-size: .9rem; }}
.card h4 {{ font-size: 1.6rem; margin: .5rem 0 .4rem; font-weight: 650; padding: 0; }}
.card .loc {{ color: {MUTED}; font-size: 1.1rem; }}
.card .top svg {{ width: 46px; height: 46px; stroke: {TEXT}; }}
.card .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem 2rem; }}
.card .grid small {{ color: {MUTED}; font-size: 1rem; display: block; }}
.card .grid b {{ font-size: 1.7rem; font-weight: 650; display: block; margin: .3rem 0 .2rem; }}
.card .grid em {{ color: {MUTED}; font-style: normal; font-size: .98rem; }}
.note {{ display: flex; gap: .8rem; margin: .6rem 0 1.2rem 1.2rem; }}
.note svg {{ width: 22px; height: 22px; flex: none; stroke: {MUTED}; margin-top: .15rem; }}
.note b {{ font-weight: 500; font-size: 1.1rem; }}
.note p {{ color: {MUTED}; margin: .3rem 0 0; line-height: 1.5; }}

/* ---------- result ---------- */
.result {{ border-top: 1px solid {LINE}; margin-top: 1.4rem; padding-top: 1.4rem; }}
.result .kicker {{ color: {MUTED}; letter-spacing: .06em; font-size: .95rem; }}
.result .value {{ font-size: 3.4rem; font-weight: 700; letter-spacing: -0.02em; margin: .3rem 0 1rem; line-height: 1; }}
.range {{ position: relative; height: 10px; border-radius: 10px; background: #1F1F1F; margin: .5rem 0 .6rem; }}
.range span {{ position: absolute; inset: 0; border-radius: 10px;
               background: linear-gradient(90deg, #22392F, {GREEN} 50%, #22392F); }}
.range i {{ position: absolute; top: -6px; width: 4px; height: 22px; border-radius: 3px; background: #F4F4F4; }}
.ends {{ display: flex; justify-content: space-between; font-size: 1.05rem; }}
.ends small {{ color: {MUTED}; display: block; font-size: .85rem; }}
.rangenote {{ color: {MUTED}; font-size: .9rem; margin: .7rem 0 1.2rem; }}
.rfacts {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; border: 1px solid {LINE};
           border-radius: 20px; padding: 1rem 1.2rem; margin-bottom: 1rem; }}
.rfacts small {{ color: {MUTED}; display: block; font-size: .85rem; }}
.rfacts b {{ font-size: 1.25rem; font-weight: 600; }}
.fineprint {{ color: #6E6E6E; font-size: .82rem; margin-top: 2.4rem; }}
table {{ color: {TEXT}; }}
@media (max-width: 640px) {{
  .title {{ font-size: 1.6rem; }}
  .result .value {{ font-size: 2.5rem; }}
  .rfacts {{ grid-template-columns: 1fr 1fr; }}
  .card .grid b {{ font-size: 1.35rem; }}
  [class*="st-key-type_"] button {{ height: 104px; }}
}}
</style>
"""

ICONS = {
    "building": '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M4 21V4h9v17M13 9h7v12M2 21h20M7 8h1M7 12h1M7 16h1M16 13h1M16 17h1"/></svg>',
    "warehouse": '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M3 21V8l9-5 9 5v13"/><path d="M7 21v-9h10v9M7 15h10M7 18h10"/></svg>',
    "home": '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M3 11l9-7 9 7M5 9.5V21h14V9.5M10 21v-6h4v6"/></svg>',
    "pin": '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
           '<path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
    "info": '<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="9"/>'
            '<path d="M12 11v5M12 8h.01"/></svg>',
}


def apply():
    st.markdown(CSS, unsafe_allow_html=True)


def _e(s) -> str:
    return html.escape(str(s))


def brand(subtitle: str):
    icon = ICONS["building"].replace("<svg", '<svg stroke="#F4F4F4"')
    st.markdown(f'<div class="brand">{icon}'
                f'<div><b>PropertyValue</b><small>{_e(subtitle)}</small></div></div>', unsafe_allow_html=True)


def selected_card(key: str):
    """Green outline on the selected property-type card."""
    st.markdown(f"<style>.st-key-{key} button, .st-key-{key} button:hover {{ border: 2px solid {GREEN_LT} !important; }}"
                "</style>",
                unsafe_allow_html=True)


def progress(step: int, label: str, right_chip: bool = False):
    bars = "".join(f'<span class="{"on" if i < step else ""}"></span>' for i in range(3))
    if step == 1:
        st.markdown(f'<div><span class="chip">Step 1 of 3</span><span style="color:{MUTED}">{_e(label)}</span></div>'
                    f'<div class="bars">{bars}</div>', unsafe_allow_html=True)
    else:
        right = f'<span class="chip">{_e(label)}</span>' if right_chip else _e(label)
        st.markdown(f'<div class="bars">{bars}</div><div class="steprow"><span class="lead">STEP {step} OF 3</span>'
                    f'{right}</div>', unsafe_allow_html=True)


def title(text: str, sub: str | None = None):
    st.markdown(f'<div class="title">{_e(text)}</div>' + (f'<p class="sub">{_e(sub)}</p>' if sub else ""),
                unsafe_allow_html=True)


def facts_lines(location: str, kind_icon: str, kind_text: str):
    st.markdown(f'<div class="facts-line">{ICONS["pin"]}<span>{_e(location)}</span></div>'
                f'<div class="facts-line">{ICONS[kind_icon]}<span>{_e(kind_text)}</span></div>',
                unsafe_allow_html=True)


def qhead(text: str, right: str | None = None, badge: str | None = None):
    r = f'<span class="badge {badge}">{_e(right)}</span>' if badge else (f"<span>{_e(right)}</span>" if right else "")
    st.markdown(f'<div class="qhead"><b>{_e(text)}</b>{r}</div>', unsafe_allow_html=True)


def split(left: str, right: str):
    st.markdown(f'<div class="split"><span>{_e(left)}</span><span>{_e(right)}</span></div>', unsafe_allow_html=True)


def hint(text: str):
    st.markdown(f'<p class="hint">{_e(text)}</p>', unsafe_allow_html=True)


def summary_card(kicker: str, name: str, loc: str, icon: str, items: list[tuple[str, str, str]]):
    cells = "".join(f"<div><small>{_e(a)}</small><b>{_e(b)}</b><em>{_e(c)}</em></div>" for a, b, c in items)
    st.markdown(f'<div class="card"><div class="top"><div><div class="kicker">{_e(kicker)}</div><h4>{_e(name)}</h4>'
                f'<div class="loc">{_e(loc)}</div></div>{ICONS[icon]}</div><div class="grid">{cells}</div></div>',
                unsafe_allow_html=True)


def note(head: str, body: str):
    st.markdown(f'<div class="note">{ICONS["info"]}<div><b>{_e(head)}</b><p>{_e(body)}</p></div></div>',
                unsafe_allow_html=True)


def _money(x: float) -> str:
    if abs(x) < 0.5:
        return "$0"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def result_panel(low: float, mid: float, high: float, facts: list[tuple[str, str]], range_note: str | None = None,
                 kicker: str = "YOUR ESTIMATED PROPERTY VALUE"):
    span = high - low
    pos = 50 if span <= 0 else max(2, min(98, (mid - low) / span * 100))
    shown = round(mid, -3) if abs(mid) >= 10_000 else mid
    f = "".join(f"<div><small>{_e(k)}</small><b>{_e(v)}</b></div>" for k, v in facts)
    st.markdown(
        f'<div class="result" role="region" aria-label="Estimated value"><div class="kicker">{_e(kicker)}</div>'
        f'<div class="value">{_money(shown)}</div>'
        f'<div class="range"><span></span><i style="left:calc({pos:.1f}% - 2px)"></i></div>'
        f'<div class="ends"><div><small>Low</small>{_money(low)}</div>'
        f'<div style="text-align:right"><small>High</small>{_money(high)}</div></div>'
        + (f'<p class="rangenote">{_e(range_note)}</p>' if range_note else "")
        + f'<div class="rfacts">{f}</div></div>', unsafe_allow_html=True)


def fineprint(text: str):
    st.markdown(f'<p class="fineprint">{_e(text)}</p>', unsafe_allow_html=True)
