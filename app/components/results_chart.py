"""The results figure in the browser: a keyed Streamlit v2 component (D-060).

Why not `st.plotly_chart`: Streamlit derives its element identity from the
figure's contents, so every model run mounts a brand-new chart and the zoom is
lost (owner: "zoom state must persist over any change to the model"). This
component's identity is its key alone, so it stays mounted; each rerun hands
the same Plotly chart a new figure and `Plotly.react` updates it in place,
which keeps legend clicks etc. (`uirevision`). The browser remembers, per tab,
the zoom and each row's view button (sessionStorage) and puts them back on
every redraw, so they survive model runs, remounts (page switch, a run that
failed) and reloads.

plotly.js is the copy bundled with the Python plotly package, served by
Streamlit's static file serving (`server.enableStaticServing`), so it matches
plotly.py and works offline.
"""

import shutil
from pathlib import Path
from typing import Any

import plotly
import plotly.graph_objects as go
import plotly.offline
import streamlit as st
from streamlit.components.v2.get_bidi_component_manager import get_bidi_component_manager

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "static"  # served at app/static/ (next to streamlit_app.py)
PLOTLY_JS = f"plotly-{plotly.offline.get_plotlyjs_version()}.min.js"
PLOTLY_URL = f"app/static/{PLOTLY_JS}"
STORE_PREFIX = "results-figure:"  # sessionStorage keys: zoom and view picks

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

function load(prefix, k) {
  try { return JSON.parse(sessionStorage.getItem(prefix + k)); } catch (e) { return null; }
}

function save(prefix, k, v) {
  try { sessionStorage.setItem(prefix + k, JSON.stringify(v)); } catch (e) {}
}

function setPath(obj, path, value) {
  const parts = path.split(".");
  let o = obj;
  for (const p of parts.slice(0, -1)) { o[p] = o[p] || {}; o = o[p]; }
  o[parts[parts.length - 1]] = value;
}

// Show the remembered view of each row: apply that button's update to the
// figure before drawing it (no flicker, no rerun).
function applyViews(fig, views) {
  for (const menu of fig.layout.updatemenus || []) {
    const want = views[menu.name];
    if (want === undefined || want === menu.active || !menu.buttons[want]) continue;
    const [traceUpdate, layoutUpdate, indices] = menu.buttons[want].args;
    indices.forEach((t, j) => { fig.data[t].visible = traceUpdate.visible[j]; });
    for (const [k, v] of Object.entries(layoutUpdate)) setPath(fig.layout, k, v);
    menu.active = want;
  }
}

export default function (component) {
  const { data, parentElement } = component;
  const prefix = data.store_prefix;
  let div = parentElement.querySelector(".results-figure");
  if (!div) {
    div = document.createElement("div");
    div.className = "results-figure";
    parentElement.appendChild(div);
  }
  const fig = JSON.parse(data.figure);
  applyViews(fig, load(prefix, "views") || {});
  // The last zoom, on every redraw (a model run, a remount, a reload); null =
  // the full year (zoomed out / double-clicked).
  const range = load(prefix, "x_range");
  if (range) {
    fig.layout.xaxis = Object.assign({}, fig.layout.xaxis, { range: range, autorange: false });
  }
  loadPlotly(data.plotly_src)
    .then((Plotly) => Plotly.react(div, fig.data, fig.layout, data.config))
    .then(() => {
      if (div.dataset.hooked) return;
      div.dataset.hooked = "1";
      div.on("plotly_buttonclicked", (ev) => {
        const views = load(prefix, "views") || {};
        views[ev.menu.name] = ev.active;
        save(prefix, "views", views);
      });
      div.on("plotly_relayout", () => {
        const xa = div._fullLayout.xaxis;
        save(prefix, "x_range", xa.autorange ? null : xa.range.slice());
      });
    })
    .catch((err) => { div.textContent = "Could not draw the results: " + err.message; });
}
"""

NAME = "results_figure"
_renderer: Any = None


def _component() -> Any:
    """The mount command, registering the component if this Streamlit runtime
    doesn't have it yet (a new runtime, e.g. each app test, starts empty).
    Unstyled (not a shadow root): plotly.js puts its styles in the page head."""
    global _renderer
    if _renderer is None or get_bidi_component_manager().get(NAME) is None:
        _renderer = st.components.v2.component(NAME, js=_JS, isolate_styles=False)
    return _renderer


def ensure_plotly_js() -> Path:
    """Copy plotly.js from the plotly package into the static folder (once per
    version; the folder is git-ignored)."""
    target = STATIC_DIR / PLOTLY_JS
    if not target.is_file():
        STATIC_DIR.mkdir(exist_ok=True)
        source = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        tmp = target.with_suffix(".tmp")
        shutil.copyfile(source, tmp)
        tmp.replace(target)
    return target


def results_chart(fig: go.Figure, key: str, config: dict[str, Any]) -> None:
    """Draw (or update in place) the results figure under `key`."""
    ensure_plotly_js()
    _component()(
        key=key,
        data={
            "figure": fig.to_json(),
            "plotly_src": PLOTLY_URL,
            "config": {**config, "responsive": True},
            "store_prefix": STORE_PREFIX,
        },
    )
