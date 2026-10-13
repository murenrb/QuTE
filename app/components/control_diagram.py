"""State diagram for the Control tab (docs/control.md, D-053).

Default and the user's states are the corners of a regular polygon (Default
at the top, the states clockwise by priority), so no arrow runs through
another node or along another arrow (owner, D-063). One state: a line.
Arrows = allowed moves between the user's states (double-headed when both
ways); dashed lines = the fall back to Default (always allowed, both ways).
Greyscale structure (docs/gui.md); the selected state is filled dark.

Drawn by a small keyed v2 component (like the results figure, D-060) that
reports a click on a state as a trigger value (D-066). Not `st.plotly_chart`
with `on_select`: there a double-click (e.g. a trackpad double tap) or a
click Plotly doesn't attach to a point sends an empty selection, so the click
was lost (owner: "a tiny flicker but the state doesn't change"), and every
click needed a remount and a second rerun.
"""

import math
from collections.abc import Callable
from typing import Any

import plotly.graph_objects as go
import streamlit as st
from streamlit.components.v2.get_bidi_component_manager import get_bidi_component_manager

from app.components.results_chart import PLOTLY_URL, ensure_plotly_js
from app.components.style import AXIS, BODY_PX, BORDER, FONT_STACK, GRID, INK, PANEL_BG, SMALL_PX
from core.domain.control import DEFAULT_STATE_ID, ControlSettings

DIAGRAM_HEIGHT_PX = 340
RING_RADIUS = 1.0
NODE_SIZE_PX = 22
ARROW_INSET = 0.14  # stop arrows short of the node so the head stays visible


def node_positions(settings: ControlSettings) -> dict[str, tuple[float, float]]:
    """Corners of a regular polygon: Default at the top, the user's states
    clockwise after it. No states: Default alone in the centre."""
    if not settings.states:
        return {DEFAULT_STATE_ID: (0.0, 0.0)}
    ids = [DEFAULT_STATE_ID, *(s.id for s in settings.states)]
    pos = {}
    for k, i in enumerate(ids):
        a = math.pi / 2 - 2 * math.pi * k / len(ids)
        pos[i] = (RING_RADIUS * math.cos(a), RING_RADIUS * math.sin(a))
    return pos


def node_label(settings: ControlSettings, state_id: str) -> str:
    if state_id == DEFAULT_STATE_ID:
        return settings.default.name
    order = [s.id for s in settings.states].index(state_id) + 1
    return f"{order}. {settings.state(state_id).name}"  # number = priority


def edges(settings: ControlSettings) -> list[tuple[str, str, bool]]:
    """(a, b, both ways) for each pair of the user's states with an allowed move."""
    out = []
    ids = [s.id for s in settings.states]
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ab, ba = settings.state(a).allows(b), settings.state(b).allows(a)
            if ab and ba:
                out.append((a, b, True))
            elif ab:
                out.append((a, b, False))
            elif ba:
                out.append((b, a, False))
    return out


def _inset(p: tuple[float, float], q: tuple[float, float]) -> tuple[float, float, float, float]:
    """The segment p→q shortened at both ends."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    return (
        p[0] + ARROW_INSET * dx,
        p[1] + ARROW_INSET * dy,
        q[0] - ARROW_INSET * dx,
        q[1] - ARROW_INSET * dy,
    )


def build_state_diagram(settings: ControlSettings, selected: str | None) -> go.Figure:
    pos = node_positions(settings)
    fig = go.Figure()
    for s in settings.states:  # fall back to Default: always allowed, both ways
        x0, y0, x1, y1 = _inset(pos[DEFAULT_STATE_ID], pos[s.id])
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line={"color": BORDER, "width": 1, "dash": "dash"},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    for a, b, both in edges(settings):
        x0, y0, x1, y1 = _inset(pos[a], pos[b])
        fig.add_annotation(
            x=x1,
            y=y1,
            ax=x0,
            ay=y0,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            showarrow=True,
            arrowhead=2,
            arrowside="end+start" if both else "end",
            arrowsize=1.2,
            arrowwidth=1.2,
            arrowcolor=AXIS,
            text="",
        )
    ids = [DEFAULT_STATE_ID, *(s.id for s in settings.states)]
    fig.add_trace(
        go.Scatter(
            x=[pos[i][0] for i in ids],
            y=[pos[i][1] for i in ids],
            mode="markers+text",
            customdata=ids,
            text=[node_label(settings, i) for i in ids],
            textposition="bottom center",
            textfont={"family": FONT_STACK, "size": SMALL_PX, "color": INK},
            marker={
                "symbol": "square",
                "size": NODE_SIZE_PX,
                "color": [INK if i == selected else PANEL_BG for i in ids],
                "line": {"color": INK, "width": 1.5},
            },
            hovertemplate="%{text}<extra>click to edit</extra>",
            showlegend=False,
        )
    )
    span = RING_RADIUS * 1.35
    fig.update_layout(
        height=DIAGRAM_HEIGHT_PX,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor=PANEL_BG,
        plot_bgcolor=PANEL_BG,
        font={"family": FONT_STACK, "size": BODY_PX, "color": INK},
        xaxis={"visible": False, "range": [-span, span], "fixedrange": True},
        yaxis={
            "visible": False,
            "range": [-span, span],
            "fixedrange": True,
            "scaleanchor": "x",
        },
        clickmode="event",
        dragmode=False,
        hoverlabel={"font": {"family": FONT_STACK}, "bgcolor": PANEL_BG, "bordercolor": GRID},
    )
    return fig


_JS = """
const loading = {};

function loadPlotly(src) {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!loading[src]) {
    loading[src] = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = new URL(src, document.baseURI).href;
      s.onload = () => resolve(window.Plotly);
      s.onerror = () => {
        delete loading[src];
        reject(new Error("could not load " + src));
      };
      document.head.appendChild(s);
    });
  }
  return loading[src];
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let div = parentElement.querySelector(".state-diagram");
  if (!div) {
    div = document.createElement("div");
    div.className = "state-diagram";
    parentElement.appendChild(div);
  }
  div._send = setTriggerValue;  // the latest, for the handler hooked once below
  const fig = JSON.parse(data.figure);
  loadPlotly(data.plotly_src)
    .then((Plotly) => Plotly.react(div, fig.data, fig.layout, data.config))
    .then(() => {
      if (div.dataset.hooked) return;
      div.dataset.hooked = "1";
      div.on("plotly_click", (ev) => {
        const p = (ev.points || []).find((q) => q.customdata != null);
        if (p) div._send("clicked", p.customdata);
      });
    })
    .catch((err) => { div.textContent = "Could not draw the diagram: " + err.message; });
}
"""

NAME = "state_diagram"
_renderer: Any = None


def _component() -> Any:
    """The mount command, registering the component if this runtime doesn't
    have it yet (see results_chart._component)."""
    global _renderer
    if _renderer is None or get_bidi_component_manager().get(NAME) is None:
        _renderer = st.components.v2.component(NAME, js=_JS, isolate_styles=False)
    return _renderer


def state_diagram(
    settings: ControlSettings, selected: str, key: str, on_click: Callable[[], None]
) -> None:
    """Draw the diagram under `key`; a click on a state calls `on_click`, which
    reads the clicked state id with `clicked_state(key)`."""
    ensure_plotly_js()
    _component()(
        key=key,
        data={
            "figure": build_state_diagram(settings, selected).to_json(),
            "plotly_src": PLOTLY_URL,
            "config": {"displayModeBar": False, "responsive": True},
        },
        height=DIAGRAM_HEIGHT_PX,
        on_clicked_change=on_click,
    )


def clicked_state(key: str) -> str | None:
    """The state id the last click sent (inside the on_click callback)."""
    try:
        value = st.session_state[key]["clicked"]
    except (KeyError, TypeError):
        return None
    return value if isinstance(value, str) else None
