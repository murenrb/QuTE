"""Visual style constants + CSS the theme can't reach (docs/gui.md → Visual style).

Theme basics (greyscale primary, square corners, fonts, sizes) are in
`.streamlit/config.toml`; this adds panel/tab polish and styling for the
third-party Leaflet and Plotly elements.
"""

import streamlit as st

FONT_STACK = "Arial, 'Helvetica Neue', Helvetica, 'Liberation Sans', sans-serif"
BODY_PX = 16  # 12 pt
HEADER_PX = 18.67  # 14 pt
SMALL_PX = 13

INK = "#1a1a1a"
INK_MUTED = "#555555"
GRID = "#e3e3e3"
AXIS = "#8a8a8a"
BORDER = "#c8c8c8"
PANEL_BG = "#ffffff"
PLACEHOLDER_BG = "#f4f4f4"
MAP_OUTLINE = "#000000"  # 1 px outline around the map, drawn over the tiles
# Overlay inside the Leaflet container, so it sits above the tiles on every tab.
MAP_OUTLINE_CSS = (
    ".leaflet-container::after { content: ''; position: absolute; inset: 0; "
    f"border: 1px solid var(--map-outline, {MAP_OUTLINE}); pointer-events: none; "
    "z-index: 1000; }"
)
# Clear the top navigation bar: the previous 1.5 rem plus ≥ 3 lines of 16 px text.
PAGE_TOP_PADDING = "5rem"

_CSS = f"""
<style>
/* Headers: bold, never above 14 pt */
h1, h2, h3, h4, h5, h6 {{
  font-size: {HEADER_PX}px !important; font-weight: 700 !important;
  padding-top: 0.2rem !important; padding-bottom: 0.2rem !important;
}}
/* Square corners on anything the theme misses (Leaflet, tooltips, popovers) */
.leaflet-bar, .leaflet-bar a, .leaflet-control, .leaflet-popup-content-wrapper,
.leaflet-draw-toolbar a, .leaflet-draw-actions a, .leaflet-tooltip,
iframe, .js-plotly-plot .plotly .hoverlayer .hovertext {{
  border-radius: 0 !important;
}}
/* Tabs: compact, greyscale, square */
.stTabs [data-baseweb="tab-list"] {{ gap: 0; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{
  border: 1px solid {BORDER}; border-bottom: none; margin-right: -1px;
  padding: 2px 12px; border-radius: 0; font-size: {BODY_PX}px;
}}
.stTabs [aria-selected="true"] {{ background: {PANEL_BG}; font-weight: 700; }}
/* Tighter page padding for a dense engineering layout */
.block-container, [data-testid="stMainBlockContainer"] {{
  padding-top: {PAGE_TOP_PADDING} !important; padding-bottom: 1rem;
}}
/* Control tab: the state picker stays at the top while the editor scrolls.
   Sticky goes on Streamlit's wrapper around the keyed container (the
   container's own parent is only as tall as the picker, so it can't stick),
   and the tab's content block must be as tall as its content (Streamlit sizes
   it to the panel, which would end the sticky range half way down). */
[data-testid="stLayoutWrapper"]:has(> .st-key-ctl_picker) {{
  position: sticky; top: 0; z-index: 10; background: {PANEL_BG};
  border-bottom: 1px solid {BORDER}; padding: 4px 0;
}}
[data-testid="stTabPanel"] > [data-testid="stVerticalBlock"]:has(.st-key-ctl_picker) {{
  min-height: max-content;
}}
[data-testid="stMetricValue"] {{ font-size: {HEADER_PX}px; font-weight: 700; }}
[data-testid="stMetricLabel"] p {{ font-size: {SMALL_PX}px; color: {INK_MUTED}; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


SECTION_RULE_CLASS = "dcs-section-rule"


def section_rule() -> None:
    """Full-width grey line between the input/map layer and the outputs below."""
    st.markdown(
        f'<hr class="{SECTION_RULE_CLASS}" style="border:none;border-top:1px solid {AXIS};'
        'margin:12px 0 8px 0">',
        unsafe_allow_html=True,
    )


def placeholder(message: str, height: int) -> None:
    """Grey panel shown before results exist."""
    st.markdown(
        f'<div style="height:{height}px;background:{PLACEHOLDER_BG};border:1px solid {BORDER};'
        f"display:flex;align-items:center;justify-content:center;color:{INK_MUTED};"
        f'font-size:{SMALL_PX}px;text-align:center;padding:8px">{message}</div>',
        unsafe_allow_html=True,
    )
