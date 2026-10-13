"""Results figure is registry-driven on one shared time axis; metrics; theme."""

import tomllib
from pathlib import Path

import pandas as pd
import pytest

from app.components.metrics import output_metrics
from app.components.modules import BY_KEY, MODULES
from app.components.plots import (
    MAIN_X,
    MODULE_X,
    NO_MODULE_NOTE,
    ROWS,
    SPACING,
    TABLE_GAP,
    UI_REVISION,
    _domains,
    build_results_figure,
)
from app.components.style import PAGE_TOP_PADDING
from core.config.defaults import ASSUMPTIONS, KW_PER_TR
from core.domain.site import AreaPolygon
from core.geometry.local_frame import LocalFrame
from core.models.site_model import run_site_model
from core.timeseries import columns as col
from core.timeseries.columns import PlotGroup, columns_in_group
from core.weather.tmy import WeatherMeta

ROOT = Path(__file__).resolve().parents[2]
META = WeatherMeta("NSRDB tmy-2024", "1", 33.45, -112.07, 300.0, -7.0, "k")


@pytest.fixture
def frame(dc_10mw, synthetic_weather: pd.DataFrame) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    return run_site_model(dc_10mw, synthetic_weather, ASSUMPTIONS)


def test_one_shared_x_axis_for_every_trace(frame: pd.DataFrame) -> None:
    fig = build_results_figure(frame)
    assert {t.xaxis for t in fig.data} == {"x"}
    assert [k for k in fig.layout.to_plotly_json() if k.startswith("xaxis")] == ["xaxis"]
    assert fig.layout.xaxis.rangeslider.visible
    assert fig.layout.hovermode == "x unified" and fig.layout.hoversubplots == "axis"


def test_rows_and_views_in_order_with_registry_traces(frame: pd.DataFrame) -> None:
    """D-060: three rows, each with view buttons; every view's traces are in
    the figure, only the first view of each row visible."""
    assert [(r.key, [v.group for v in r.views]) for r in ROWS] == [
        ("ambient", [PlotGroup.AMBIENT, PlotGroup.SUN]),
        ("power", [PlotGroup.THERMAL, PlotGroup.ELECTRICAL]),
        (
            "operation",
            [
                PlotGroup.UTILITY,
                PlotGroup.ENERGY_PRICE,
                PlotGroup.DEMAND_CHARGE,
                PlotGroup.CONTROL,
            ],
        ),
    ]
    fig = build_results_figure(frame)
    present = [
        (r, v, spec)
        for r in ROWS
        for v in r.views
        for spec in columns_in_group(v.group)
        if spec.name in frame.columns
    ]
    assert [t.name for t in fig.data] == [
        "State" if v.group is PlotGroup.CONTROL else spec.label for _, v, spec in present
    ]
    for t, (r, v, spec) in zip(fig.data, present, strict=True):
        assert t.visible == (v is r.views[0])
        if v.group is not PlotGroup.CONTROL:
            assert t.line.color == spec.color and spec.color is not None
            assert (t.stackgroup is not None) == spec.stacked
    annotations = [a.text for a in fig.layout.annotations]
    assert annotations == [f"<b>{r.title}</b>" for r in ROWS] + [NO_MODULE_NOTE]
    # legends beside the plots, so they can't run over the titles (owner)
    for i in range(1, len(ROWS) + 1):
        legend = fig.layout["legend" if i == 1 else f"legend{i}"]
        assert legend.orientation == "v" and legend.x > 1


def test_view_buttons_switch_traces_and_axis(frame: pd.DataFrame) -> None:
    """Each row's buttons show one view's traces and y-axis and hide the rest
    of that row, without touching other rows (D-060)."""
    fig = build_results_figure(frame, views={"power": "electrical"})
    menus = {m.name: m for m in fig.layout.updatemenus}
    assert list(menus) == [r.key for r in ROWS]
    power = menus["power"]
    assert [b.label for b in power.buttons] == ["Thermal", "Electrical"]
    assert power.active == 1  # views= picks the shown view
    for button in power.buttons:
        visible, axes, traces = button.args
        rows = {fig.data[i].yaxis for i in traces}
        assert len(axes) == 2 and all(k.endswith(".visible") for k in axes)
        shown = [fig.data[i].yaxis for i, on in zip(traces, visible["visible"], strict=True) if on]
        assert len(set(shown)) == 1 and axes[f"yaxis{shown[0][1:]}.visible"] is True
        assert rows <= {f"y{k.removeprefix('yaxis').removesuffix('.visible')}" for k in axes}
    elec = [t for t in fig.data if t.name == "IT load"]
    assert elec[0].visible is True
    assert all(t.visible is False for t in fig.data if t.name == "Chillers")


def test_rows_stacked_top_to_bottom_one_axis_per_view(frame: pd.DataFrame) -> None:
    fig = build_results_figure(frame)
    L = fig.layout
    # y: temperatures, y2: sun (overlaid on y), y3 thermal, y4 electrical, y5–y8 operation
    assert L.yaxis.domain[0] > L.yaxis3.domain[1] > L.yaxis3.domain[0] > L.yaxis5.domain[1]
    assert L.yaxis2.overlaying == "y" and L.yaxis4.overlaying == "y3"
    assert L.yaxis2.tickmode == "auto"  # own ticks, not synced to the base axis
    assert (L.yaxis.title.text, L.yaxis2.title.text) == ("°C", "W/m²")
    assert (L.yaxis3.title.text, L.yaxis4.title.text) == ("MW_th", "MW")
    assert L.yaxis5.title.text == "$" and L.yaxis6.title.text == "$/kWh"
    assert (L.yaxis.visible, L.yaxis2.visible) == (True, False)
    assert "yaxis9" not in L.to_plotly_json()
    assert {t.legend for t in fig.data} == {"legend", "legend2", "legend3"}
    ghi = next(t for t in fig.data if t.name == "GHI")
    assert ghi.yaxis == "y2"


def test_domains_valid() -> None:
    d = _domains(3, 0.07)
    assert d[0][1] == 1.0 and d[-1][0] == 0.0
    assert all(0 <= lo < hi <= 1 for lo, hi in d)


def test_electric_in_mw_with_black_net_line(frame: pd.DataFrame) -> None:
    fig = build_results_figure(frame)
    it = next(t for t in fig.data if t.name == "IT load")
    assert it.y[0] == pytest.approx(10.0)  # 10 MW, shown in MW
    net = next(t for t in fig.data if t.name == "Net grid load")
    assert net.line.color == "#000000" and net.stackgroup is None


def test_metrics(frame: pd.DataFrame) -> None:
    m = {x.label: x.value for x in output_metrics(frame, META)}
    assert m["Annual IT energy"] == f"{10 * 8760:,.0f} MWh/yr"
    grid_mwh = frame[col.GRID_NET_KW].sum() / 1000
    assert m["Annual grid energy"] == f"{grid_mwh:,.0f} MWh/yr"
    free = int((frame[col.COOLING_FREE_KWTH] > 0).sum())
    assert m["Free-cooling hours"].startswith(f"{free:,} h")
    assert "NSRDB tmy-2024" in m["Weather"] and "UTC-7" in m["Weather"]


def test_theme_greyscale_square_arial() -> None:
    theme = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
    assert theme["baseRadius"] == "none"
    r, g, b = (theme["primaryColor"][i : i + 2] for i in (1, 3, 5))
    assert r == g == b  # grey, no accent color
    assert theme["font"].startswith("Arial")
    assert theme["baseFontSize"] == 16  # 12 pt
    assert all(float(s.removesuffix("px")) <= 18.67 for s in theme["headingFontSizes"])  # ≤ 14 pt
    assert theme["headingFontWeights"] == 700


def test_content_clears_header_by_three_text_lines() -> None:
    previous_rem, text_line_rem = 1.5, 1.0  # 16 px body text
    assert float(PAGE_TOP_PADDING.removesuffix("rem")) >= previous_rem + 3 * text_line_rem


def test_generation_stacks_below_zero(frame: pd.DataFrame) -> None:
    with_pv = frame.assign(**{col.PV_KW: -0.5 * frame[col.IT_LOAD_KW]})
    fig = build_results_figure(with_pv)
    by_name = {t.name: t for t in fig.data}
    assert by_name["Solar PV"].stackgroup.endswith("_neg")
    assert by_name["IT load"].stackgroup == by_name["Cooling electrical"].stackgroup
    assert not by_name["IT load"].stackgroup.endswith("_neg")
    m = {x.label: x.value for x in output_metrics(with_pv, META)}
    assert m["Annual PV generation"] == f"{0.5 * 10 * 8760:,.0f} MWh/yr"


def test_utility_metrics_have_one_dollar_sign_each(frame: pd.DataFrame) -> None:
    """Two "$" in one Streamlit metric render as a maths formula."""
    m = {x.label: x.value for x in output_metrics(frame, META)}
    for label in (
        "Annual utility cost",
        "Annual energy cost",
        "Annual demand charges",
        "Average utility cost",
    ):
        assert m[label].count("$") == 1
    energy = frame[col.ENERGY_COST_USD].sum()
    assert m["Annual energy cost"] == f"${energy:,.0f}/yr"


def test_utility_subplot_shows_running_totals_as_lines(frame: pd.DataFrame) -> None:
    fig = build_results_figure(frame)
    utility = [t for t in fig.data if t.yaxis == "y5"]
    assert [t.name for t in utility] == [
        "Energy cost to date",
        "Demand charges to date",
        "Utility cost to date",
    ]
    assert all(t.stackgroup is None for t in utility)  # lines, not areas
    total = next(t for t in utility if t.name == "Utility cost to date")
    assert total.y[-1] == pytest.approx(frame[col.UTILITY_COST_USD].sum())


# --- module output panel (D-055) -------------------------------------------------


def square_m2(m2: float, center: tuple[float, float] = (33.45, -112.06)) -> AreaPolygon:
    half = m2**0.5 / 2
    ring = LocalFrame(center).to_latlon(
        [(-half, -half), (half, -half), (half, half), (-half, half)]
    )
    return AreaPolygon(exterior=tuple(ring))


_MODULES_FRAME: list[pd.DataFrame] = []  # one model run shared by the module tests


@pytest.fixture
def modules_frame(synthetic_weather: pd.DataFrame) -> pd.DataFrame:
    """Every module except PV (needs PySAM), brine ice mixer, everything run."""
    if _MODULES_FRAME:
        return _MODULES_FRAME[0]
    from core.config.defaults import IceMixerFluid
    from core.control.catalog import ALL_ON
    from core.domain.datacenter import DataCenter
    from core.domain.datacenter_type import DataCenterType
    from core.domain.modules import (
        BrineSeparationParams,
        GreenhouseParams,
        HotWaterStorageParams,
        IceMixerParams,
        IceStorageParams,
        ModuleSettings,
        PowerGenerationParams,
    )

    modules = ModuleSettings(
        ice_storage=IceStorageParams(enabled=True),
        ice_mixer=IceMixerParams(enabled=True, fluid=IceMixerFluid.BRINE),
        brine_separation=BrineSeparationParams(enabled=True),
        hot_water_storage=HotWaterStorageParams(enabled=True),
        power_generation=PowerGenerationParams(enabled=True),
        greenhouse=GreenhouseParams(enabled=True, area=(square_m2(4047.0),)),  # 1 acre
    )
    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    _MODULES_FRAME.append(
        run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=ALL_ON)
    )
    return _MODULES_FRAME[0]


@pytest.mark.parametrize("key", [m.key for m in MODULES if m.key != "solar_pv"])
def test_module_panel_follows_the_main_time_axis(modules_frame: pd.DataFrame, key: str) -> None:
    ui = BY_KEY[key]
    fig = build_results_figure(modules_frame, (ui.label, ui.outputs))
    L = fig.layout
    # its own x-axis on the left, matched to the main one: zoom / pan / slider move both
    assert L.xaxis2.matches == "x" and L.xaxis2.domain == MODULE_X
    assert L.xaxis.domain == MAIN_X and MODULE_X[1] < MAIN_X[0]
    assert L.uirevision == UI_REVISION
    lines = [t for t in fig.data if t.type == "scatter" and t.xaxis == "x2"]
    assert [t.name for t in lines] == [t.label for p in ui.outputs.panels for t in p.traces]
    # one panel spans rows 1–2; two panels take one row each, aligned with the main rows
    rows = _domains(len(ROWS), SPACING)
    axes = list(dict.fromkeys(t.yaxis for t in lines))
    assert len(axes) == len(ui.outputs.panels) <= 2
    tops = [L[f"yaxis{a[1:]}"].domain[1] for a in axes]
    assert tops[0] == pytest.approx(rows[0][1])
    if len(axes) == 2:
        assert tops[1] == pytest.approx(rows[1][1])
    # text output: a table under the plot, every value filled in
    (table,) = [t for t in fig.data if t.type == "table"]
    # room under the plot for two-line date ticks when zoomed in (owner: overlap)
    assert table.domain.y[1] == pytest.approx(rows[2][1] - TABLE_GAP)
    labels, values = table.cells["values"]
    assert list(labels) == [m.label for m in ui.outputs.text(modules_frame)]
    assert all(v != "—" for v in values)


def test_operation_views_draw_steps_and_named_states(frame: pd.DataFrame) -> None:
    """D-057, D-060: prices and the state are hourly steps; the state axis is
    labelled with the (cut) state names."""
    names = ["Default", "A very long state name indeed"]
    fig = build_results_figure(frame, state_names=names, views={"operation": "control"})
    (state,) = [t for t in fig.data if t.name == "State"]
    assert state.visible is True and state.line.shape == "hv"
    assert state.customdata[0] == "Default"
    axis = fig.layout["yaxis" + state.yaxis[1:]]
    assert list(axis.tickvals) == [0, 1] and axis.visible is True
    assert axis.ticktext[1].endswith("…") and len(axis.ticktext[1]) <= 16
    price = next(t for t in fig.data if t.name == "Energy price")
    assert price.line.shape == "hv" and price.visible is False


def test_module_without_results_gets_a_note(frame: pd.DataFrame) -> None:
    ui = BY_KEY["solar_pv"]  # e.g. added, but no area drawn yet
    fig = build_results_figure(frame, (ui.label, ui.outputs))
    assert not [t for t in fig.data if t.xaxis == "x2" or t.type == "table"]
    notes = [a.text for a in fig.layout.annotations]
    assert "Solar PV has no results yet (finish its inputs on the Modules tab)." in notes


def test_module_text_values(modules_frame: pd.DataFrame) -> None:
    df = modules_frame
    ice = {m.label: m.value for m in BY_KEY["ice_storage"].outputs.text(df)}
    made_kwth = df[col.ICE_INSTANT_KWTH] + df[col.ICE_CHARGE_KWTH]
    per_day_t = (made_kwth * 3600 / 330 / 1000).resample("D").sum()
    assert ice["Max ice made per day"] == f"{per_day_t.max():,.0f} t/day"
    on = made_kwth[made_kwth > 0]
    weighted_tr = float((on**2).sum() / on.sum()) / KW_PER_TR
    assert ice["Ice making rate while on (production-weighted)"] == f"{weighted_tr:,.0f} TR"
    # the production-weighted rate lies between the mean and the max rate while on
    assert on.mean() / KW_PER_TR - 1 <= weighted_tr <= on.max() / KW_PER_TR + 1
    mixer = {m.label: m.value for m in BY_KEY["ice_mixer"].outputs.text(df)}
    t_on = df.loc[df[col.ICE_MIX_Q_KWTH] > 0, col.ICE_MIX_T_C]
    assert mixer["Min cooling temperature"] == f"{t_on.min():,.1f} °C"
    brine = {m.label: m.value for m in BY_KEY["brine_separation"].outputs.text(df)}
    assert brine["Max concentration"] == f"{df[col.BRINE_CONC_WT_PCT].max():,.1f} wt%"
    assert df[col.BRINE_SOC_FRAC].between(0, 1 + 1e-9).all()


def test_plotly_js_served_from_the_static_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-060: the results component loads the plotly.js bundled with plotly.py,
    copied into the static folder that Streamlit serves."""
    from app.components import results_chart

    monkeypatch.setattr(results_chart, "STATIC_DIR", tmp_path / "static")
    target = results_chart.ensure_plotly_js()
    assert target.parent == tmp_path / "static" and target.stat().st_size > 1_000_000
    assert f"app/static/{target.name}" == results_chart.PLOTLY_URL
    server = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["server"]
    assert server["enableStaticServing"] is True
