"""Results figure: three stacked rows on one shared time axis (D-029, D-060),
with the module output panel to their left (D-055).

Each row shows one **view** at a time, picked with the buttons on the row
(owner, D-060): Ambient (temperatures / sun), Power (thermal / electrical),
Operation (utility cost / energy price / demand charge / control state).
Every view is in the figure with its own y-axis; the buttons only switch
which traces and axis are visible (Plotly `updatemenus`), so switching is
instant and needs no rerun. The browser remembers the picks and the zoom
across reruns (app/components/results_chart.py).

Traces come from `columns_in_group`, so a module that registers a column with
a plot group appears in its view with no edit here; the module panel comes
from the module's own `ModuleOutputs`. Structure is greyscale; only data
traces carry color (registry colors).

The module panel is part of the same figure so its time axis can follow the
main one through Plotly alone (`matches`): Streamlit can't pass zoom between
two separate charts.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from app.components.module_outputs import ModuleOutputs
from app.components.style import (
    AXIS,
    BORDER,
    FONT_STACK,
    GRID,
    INK,
    INK_MUTED,
    PANEL_BG,
    PLACEHOLDER_BG,
    SMALL_PX,
)
from core.config.defaults import KW_PER_MW
from core.timeseries.columns import NET_LINE as NET_LINE_COLOR
from core.timeseries.columns import ColumnSpec, PlotGroup, columns_in_group


@dataclass(frozen=True)
class View:
    key: str
    label: str  # the button
    group: PlotGroup


@dataclass(frozen=True)
class Row:
    key: str
    title: str
    views: tuple[View, ...]  # the first is the default


# Top → bottom; the figure is built from this list (owner, D-060).
ROWS: tuple[Row, ...] = (
    Row(
        "ambient",
        "Ambient",
        (
            View("temperatures", "Temperatures", PlotGroup.AMBIENT),
            View("sun", "Sun", PlotGroup.SUN),
        ),
    ),
    Row(
        "power",
        "Power",
        (
            View("thermal", "Thermal", PlotGroup.THERMAL),
            View("electrical", "Electrical", PlotGroup.ELECTRICAL),
        ),
    ),
    Row(
        "operation",
        "Operation",
        (
            View("utility", "Utility cost", PlotGroup.UTILITY),
            View("energy_price", "Energy price", PlotGroup.ENERGY_PRICE),
            View("demand_charge", "Demand charge", PlotGroup.DEMAND_CHARGE),
            View("control", "Control state", PlotGroup.CONTROL),
        ),
    ),
)
STEP_GROUPS = {PlotGroup.ENERGY_PRICE, PlotGroup.DEMAND_CHARGE, PlotGroup.CONTROL}  # hourly steps
FIGURE_HEIGHT_PX = 1000
RANGE_SLIDER_THICKNESS = 0.05
SPACING = 0.07  # paper fraction between rows (title + buttons sit in it)
# Horizontal paper domains: module panel | main rows (about the two page columns).
MODULE_X = (0.0, 0.44)
MAIN_X = (0.54, 1.0)
UI_REVISION = "results"  # keeps zoom / pan when the figure is rebuilt (module switch, input edit)
TABLE_ROW_PX = 26
# Paper fraction kept free under the module plot: room for two-line date ticks
# (day + year when zoomed in) above the table's title.
TABLE_GAP = 0.04
NO_MODULE_NOTE = "Add a module on the Modules tab to see its output here."
STATE_TICK_CHARS = 16  # longer state names are cut on the axis (the hover has them whole)
SIDE_LEGEND_X = 1.02  # paper; just right of the rows
# Room for the widest legend, so switching a view never resizes the figure.
RIGHT_MARGIN_PX = 215

# kW columns are shown in MW for readability; the axis title says so.
_DISPLAY_UNIT = {"kW": ("MW", 1 / KW_PER_MW), "kW_th": ("MW_th", 1 / KW_PER_MW)}


def _scaled(spec: ColumnSpec, s: pd.Series) -> tuple[pd.Series, str]:
    unit, k = _DISPLAY_UNIT.get(spec.unit, (spec.unit, 1.0))
    return s * k, unit


def _axis_style() -> dict[str, object]:
    return {
        "showgrid": True,
        "gridcolor": GRID,
        "linecolor": AXIS,
        "tickcolor": AXIS,
        "ticks": "outside",
        "zeroline": False,
        "tickfont": {"size": SMALL_PX - 1, "color": INK_MUTED},
        "title_font": {"size": SMALL_PX, "color": INK_MUTED},
    }


def _domains(n: int, spacing: float) -> list[tuple[float, float]]:
    """Vertical (bottom, top) paper domains for n equal rows, row 1 on top."""
    h = (1 - spacing * (n - 1)) / n
    tops = [1 - r * (h + spacing) for r in range(n)]
    return [(max(0.0, round(t - h, 9)), min(1.0, round(t, 9))) for t in tops]


def _title(fig: go.Figure, text: str, x: float, y: float) -> None:
    fig.add_annotation(
        text=f"<b>{text}</b>",
        xref="paper",
        yref="paper",
        x=x,
        y=y,
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        font={"size": SMALL_PX, "color": INK},
    )


def _title_legend(title: str, x: float, y: float) -> dict[str, object]:
    """Module panels: title + legend in one row above the panel, left-aligned.

    The title is the legend's own title, so the (short, ≤ 2 entry) legend
    follows it instead of overlapping it.
    """
    return {
        "title": {
            "text": f"<b>{title}</b>",
            "side": "left",
            "font": {"size": SMALL_PX, "color": INK},
        },
        "orientation": "h",
        "x": x,
        "xanchor": "left",
        "y": y,
        "yanchor": "bottom",
        "font": {"size": SMALL_PX - 1},
        "bgcolor": "rgba(0,0,0,0)",
    }


def _side_legend(y: float, stacked: bool) -> dict[str, object]:
    """Main rows: one entry per line, right of the row, top-aligned.

    A row of up to six entries is wider than half the page, and Plotly only
    wraps a legend at the full plot width, so a row legend ran over the
    subplot title (owner). A column beside the plot never collides.
    """
    return {
        "orientation": "v",
        "x": SIDE_LEGEND_X,
        "xanchor": "left",
        "y": y,
        "yanchor": "top",
        "font": {"size": SMALL_PX - 1},
        "bgcolor": "rgba(0,0,0,0)",
        # stacked areas: list top-down like the stack itself
        "traceorder": "reversed" if stacked else "normal",
    }


def build_results_figure(
    df: pd.DataFrame,
    module: tuple[str, ModuleOutputs] | None = None,
    state_names: Sequence[str] = (),
    views: Mapping[str, str] | None = None,
) -> go.Figure:
    """Every main trace sits on the one x-axis `x`; each view has its own y-axis.

    Sharing a single x-axis (not linked ones) is what makes zoom, pan, the
    range slider and the unified hover line act on all rows at once. The
    module panel (`module` = label, outputs) has its own x-axis `x2` that
    matches `x`, so it zooms and pans with them. `state_names`: the control
    states in number order (0 = Default), for the control state view.
    `views`: row key → view key shown at first (default: each row's first).
    """
    fig = go.Figure()
    layout: dict[str, object] = {}
    menus: list[dict[str, object]] = []
    y_index = 0
    bottom_axis = "y"
    domains = _domains(len(ROWS), SPACING)
    for r, (row, (lo, hi)) in enumerate(zip(ROWS, domains, strict=True), 1):
        legend = "legend" if r == 1 else f"legend{r}"
        shown = (views or {}).get(row.key, row.views[0].key)
        if shown not in {v.key for v in row.views}:
            shown = row.views[0].key
        base = ""
        stacked_row = False
        per_view: list[tuple[View, str, list[int]]] = []  # view, its axis, its traces
        for view in row.views:
            y_index += 1
            axis = "y" if y_index == 1 else f"y{y_index}"
            base = base or axis
            on = view.key == shown
            specs = [c for c in columns_in_group(view.group) if c.name in df.columns]
            stacked_row |= any(c.stacked for c in specs)
            first = len(fig.data)
            units = _add_view_traces(fig, df, view.group, specs, axis, legend, on, state_names, r)
            per_view.append((view, axis, list(range(first, len(fig.data)))))
            layout[_layout_key(axis)] = {
                **_axis_style(),
                "domain": [lo, hi],
                "anchor": "x",
                "visible": on,
                "title_text": " / ".join(dict.fromkeys(units)),
                # its own ticks (an overlaid axis otherwise syncs to the base's)
                **({"overlaying": base, "tickmode": "auto"} if axis != base else {}),
                **(_state_axis(state_names) if view.group is PlotGroup.CONTROL else {}),
            }
        bottom_axis = base
        layout[legend] = _side_legend(hi, stacked_row)
        _title(fig, row.title, MAIN_X[0], hi)
        menus.append(_view_buttons(row, per_view, shown, hi))

    layout["xaxis"] = {
        **_axis_style(),
        "domain": list(MAIN_X),
        "anchor": bottom_axis,
        "showspikes": True,
        "spikemode": "across",
        "spikesnap": "cursor",
        "spikethickness": 1,
        "spikecolor": AXIS,
        "spikedash": "solid",
        "rangeslider": {"visible": True, "thickness": RANGE_SLIDER_THICKNESS},
    }
    _module_panel(fig, layout, df, module, domains, y_index, len(ROWS))
    fig.update_layout(
        **layout,
        updatemenus=menus,
        height=FIGURE_HEIGHT_PX,
        margin={"l": 56, "r": RIGHT_MARGIN_PX, "t": 36, "b": 24},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"family": FONT_STACK, "size": SMALL_PX, "color": INK},
        hovermode="x unified",
        hoversubplots="axis",  # one hover line/label across all the rows
        hoverlabel={"font": {"family": FONT_STACK, "size": SMALL_PX}},
        uirevision=UI_REVISION,
    )
    return fig


def _add_view_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    group: PlotGroup,
    specs: list[ColumnSpec],
    axis: str,
    legend: str,
    on: bool,
    state_names: Sequence[str],
    row: int,
) -> list[str]:
    """One view's traces on its axis; returns their display units."""
    units: list[str] = []
    for spec in specs:
        y, unit = _scaled(spec, df[spec.name])
        common = {
            "x": df.index,
            "y": y,
            "name": spec.label,
            "mode": "lines",
            "legend": legend,
            "xaxis": "x",
            "yaxis": axis,
            "visible": on,
            "hovertemplate": f"%{{y:,.2f}} {unit}",
        }
        if group is PlotGroup.CONTROL:
            trace = _state_trace(common, df[spec.name], state_names)
        elif spec.stacked:
            # Generation (all ≤ 0) stacks downward from zero in its own group,
            # so it doesn't eat into the load stack above zero.
            negative = bool((y <= 0).all() and (y < 0).any())
            hatch = {"shape": "/", "fgcolor": spec.color, "bgcolor": PANEL_BG}
            trace = go.Scatter(
                **common,
                stackgroup=f"stack{row}_{group.value}{'_neg' if negative else ''}",
                line={"width": 0.5, "color": spec.color},
                fillcolor=spec.color,
                **({"fillpattern": hatch} if spec.hatched else {}),
            )
        else:
            shape = "hv" if group in STEP_GROUPS else "linear"
            trace = go.Scatter(**common, line={"width": 1.3, "color": spec.color, "shape": shape})
        fig.add_trace(trace)
        units.append(unit)
    return units


def _view_buttons(
    row: Row, per_view: list[tuple[View, str, list[int]]], shown: str, top: float
) -> dict[str, object]:
    """The row's buttons, right-aligned above it: each shows its view's traces
    and y-axis and hides the others' (only this row's traces are touched)."""
    traces = [i for _, _, idx in per_view for i in idx]
    buttons = []
    for view, _, idx in per_view:
        visible = [i in idx for i in traces]
        axes = {f"{_layout_key(a)}.visible": v.key == view.key for v, a, _ in per_view}
        buttons.append(
            {"label": view.label, "method": "update", "args": [{"visible": visible}, axes, traces]}
        )
    return {
        "name": row.key,  # the browser remembers the pick per row by this
        "type": "buttons",
        "direction": "right",
        "active": [v.key for v in row.views].index(shown),
        "showactive": True,
        "buttons": buttons,
        "x": MAIN_X[1],
        "xanchor": "right",
        "y": top,
        "yanchor": "bottom",
        "pad": {"t": 0, "b": 4, "l": 0, "r": 0},
        "bgcolor": "#ffffff",
        "bordercolor": BORDER,
        "borderwidth": 1,
        "font": {"size": SMALL_PX - 1, "color": INK},
    }


def _module_panel(
    fig: go.Figure,
    layout: dict[str, object],
    df: pd.DataFrame,
    module: tuple[str, ModuleOutputs] | None,
    rows: list[tuple[float, float]],
    y_index: int,
    n_legends: int,
) -> None:
    """Left of the main subplots: the module's plot (one panel over the first two
    rows, or two panels on rows 1 and 2) and its text (a table over rows 3–4)."""
    if module is None or not module[1].available(df):
        fig.add_annotation(
            text=NO_MODULE_NOTE
            if module is None
            else f"{module[0]} has no results yet (finish its inputs on the Modules tab).",
            xref="paper",
            yref="paper",
            x=sum(MODULE_X) / 2,
            y=rows[0][1],
            yanchor="top",
            showarrow=False,
            font={"size": SMALL_PX, "color": INK_MUTED},
        )
        return
    label, outputs = module
    one = len(outputs.panels) == 1  # one panel spans rows 1–2; two take a row each
    domains = [(rows[1][0], rows[0][1])] if one else rows[:2]
    bottom_axis = ""
    for i, (panel, (lo, hi)) in enumerate(zip(outputs.panels, domains, strict=False)):
        y_index += 1
        axis = f"y{y_index}"
        legend = f"legend{n_legends + 1 + i}"
        bottom_axis = axis
        for t in panel.traces:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[t.column] * t.scale,
                    name=t.label,
                    mode="lines",
                    legend=legend,
                    xaxis="x2",
                    yaxis=axis,
                    line={"width": 1.3, "color": t.color},
                    hovertemplate=f"%{{y:,.2f}} {panel.unit}",
                )
            )
        layout[_layout_key(axis)] = {
            **_axis_style(),
            "domain": [lo, hi],
            "anchor": "x2",
            "title_text": panel.unit,
        }
        layout[legend] = _title_legend(panel.title, MODULE_X[0], hi)
    layout["xaxis2"] = {
        **_axis_style(),
        "domain": list(MODULE_X),
        "anchor": bottom_axis,
        "matches": "x",  # zoom / pan / range slider move both
        "showspikes": True,
        "spikemode": "across",
        "spikesnap": "cursor",
        "spikethickness": 1,
        "spikecolor": AXIS,
        "spikedash": "solid",
    }
    text = outputs.text(df)
    lo, hi = rows[-1][0], rows[2][1] - TABLE_GAP
    fig.add_trace(
        go.Table(
            domain={"x": list(MODULE_X), "y": [lo, hi]},
            columnwidth=[3, 2],
            header={
                "values": ["<b>Output</b>", "<b>Value</b>"],
                "align": "left",
                "fill_color": PLACEHOLDER_BG,
                "line_color": BORDER,
                "font": {"size": SMALL_PX, "color": INK},
                "height": TABLE_ROW_PX,
            },
            cells={
                "values": [[m.label for m in text], [m.value for m in text]],
                "align": "left",
                "fill_color": "#ffffff",
                "line_color": BORDER,
                "font": {"size": SMALL_PX, "color": INK},
                "height": TABLE_ROW_PX,
            },
        )
    )
    _title(fig, label, MODULE_X[0], hi)


def _state_trace(common: dict[str, object], s: pd.Series, names: Sequence[str]) -> go.Scatter:
    """The active state each hour, as a step line; the hover names the state."""
    number = s.round().astype(int)
    labels = [names[i] if 0 <= i < len(names) else f"State {i}" for i in number]
    return go.Scatter(
        **{**common, "name": "State", "hovertemplate": "%{customdata}"},
        customdata=labels,
        line={"width": 1.3, "color": NET_LINE_COLOR, "shape": "hv"},
    )


def _state_axis(names: Sequence[str]) -> dict[str, object]:
    """One tick per state, labelled with its name, Default (0) at the bottom."""
    n = max(len(names), 1)
    return {
        "tickmode": "array",
        "tickvals": list(range(n)),
        "ticktext": [_short(x) for x in names] or ["Default"],
        "range": [-0.5, n - 0.5],
        "title_text": "",
    }


def _short(name: str) -> str:
    return name if len(name) <= STATE_TICK_CHARS else name[: STATE_TICK_CHARS - 1] + "…"


def _layout_key(axis_ref: str) -> str:
    """'y' → 'yaxis', 'y3' → 'yaxis3'."""
    return "yaxis" + axis_ref[1:]
