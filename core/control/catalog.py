"""Every IF source and THEN target the state machine offers (docs/control.md).

Ambient, utility and time are declared here. The data center and each module
declare their own IFs / THENs in their model file (`CONTROL_SPEC`) and are
collected here, so a new module only adds its spec to `TARGETS` (and its key
to the `ends` of the link THENs it can be the other end of).
"""

from core.control.engine import Controller
from core.domain.control import (
    COOLANT,
    DATA_CENTER,
    DRAIN,
    Action,
    ControlSettings,
    ControlSpec,
    ControlVariable,
)
from core.domain.utility import UtilityTariff
from core.models import (
    brine_separation,
    datacenter,
    greenhouse,
    hot_water_storage,
    ice_mixer,
    ice_storage,
    power_generation,
    solar_pv,
)
from core.timeseries import columns as col

AMBIENT = ControlSpec(
    "ambient",
    "Ambient",
    ifs=(
        ControlVariable("tdb_c", "Dry bulb", "°C"),
        ControlVariable("twb_c", "Wet bulb", "°C"),
        ControlVariable("tdp_c", "Dew point", "°C"),
        ControlVariable("rh_pct", "Relative humidity", "%"),
        ControlVariable("t_ambient_rej_c", "Heat-rejection ambient", "°C"),
        ControlVariable("ghi_w_m2", "GHI", "W/m²"),
        ControlVariable("dni_w_m2", "DNI", "W/m²"),
        ControlVariable("dhi_w_m2", "DHI", "W/m²"),
        ControlVariable("wind_m_s", "Wind speed", "m/s"),
    ),
)
UTILITY = ControlSpec(
    "utility",
    "Utility",
    ifs=(
        ControlVariable(
            "energy_price", "Energy price", "$/kWh", statistics=True, rate_field="energy_usd_kwh"
        ),
        ControlVariable(
            "demand_charge", "Demand charge", "$/kW", statistics=True, rate_field="demand_usd_kw"
        ),
        # The previous hour's net grid draw (start of the hour, like module IFs).
        ControlVariable("grid_draw_kw", "Grid draw (previous hour)", "kW"),
    ),
)
TIME = ControlSpec(
    "time",
    "Time",
    ifs=(
        ControlVariable("hour", "Time (hour of day)", "0–23"),
        ControlVariable("date", "Date", "MM-DD", kind="date"),
        ControlVariable("month", "Month", "1–12"),
        ControlVariable("weekend", "Weekend (1 = Sat/Sun, 0 = weekday)"),
        ControlVariable("always", "Always", kind="on_off"),
    ),
)
EXOGENOUS: dict[tuple[str, str], str] = {
    ("ambient", "tdb_c"): col.TDB_C,
    ("ambient", "twb_c"): col.TWB_C,
    ("ambient", "tdp_c"): col.TDP_C,
    ("ambient", "rh_pct"): col.RH_PCT,
    ("ambient", "t_ambient_rej_c"): col.T_AMBIENT_REJ_C,
    ("ambient", "ghi_w_m2"): col.GHI_W_M2,
    ("ambient", "dni_w_m2"): col.DNI_W_M2,
    ("ambient", "dhi_w_m2"): col.DHI_W_M2,
    ("ambient", "wind_m_s"): col.WIND_M_S,
    ("utility", "energy_price"): col.ENERGY_PRICE_USD_KWH,
    ("utility", "demand_charge"): col.DEMAND_CHARGE_USD_KW,
    ("solar_pv", "available_kw"): col.PV_AVAILABLE_KW,
    ("greenhouse", "demand_kw"): col.GREENHOUSE_DEMAND_KWTH,
}

# THEN targets: the data center, then the modules in Modules-tab order.
TARGETS: tuple[ControlSpec, ...] = (
    datacenter.CONTROL_SPEC,
    solar_pv.CONTROL_SPEC,
    ice_storage.CONTROL_SPEC,
    power_generation.CONTROL_SPEC,
    hot_water_storage.CONTROL_SPEC,
    brine_separation.CONTROL_SPEC,
    ice_mixer.CONTROL_SPEC,
    greenhouse.CONTROL_SPEC,
)
# IF sources, in the order the editor lists them.
SOURCES: tuple[ControlSpec, ...] = (*TARGETS, AMBIENT, UTILITY, TIME)
SPECS: dict[str, ControlSpec] = {s.key: s for s in SOURCES}

# Names for the other end of a link, where it isn't just the module's name.
END_LABELS: dict[str, str] = {
    **{t.key: t.label for t in TARGETS},
    COOLANT: "supply coolant (free cooling / chillers)",
    DRAIN: "drain",
}
# A heat source named by what it gives (power generation's dropdown).
HEAT_SOURCE_LABELS: dict[str, str] = {
    DATA_CENTER: "data center return water",
    "hot_water_storage": "hot water storage",
    "brine_separation": "brine separation condenser steam",
}


def end_label(target: str, setting: str, end: str) -> str:
    if (target, setting) == (power_generation.KEY, "heat_in"):
        return HEAT_SOURCE_LABELS.get(end, END_LABELS.get(end, end))
    return END_LABELS.get(end, end)


def controller(
    settings: ControlSettings,
    it_peak_kw: float | None = None,
    tariff: UtilityTariff | None = None,
    available: set[str] | None = None,
) -> Controller:
    """tariff: for IFs compared with a rate category (D-059). available: the
    columns this run will have (None = all); an IF on a column that won't
    exist (its module isn't on the site) never holds instead of stopping the
    run (D-061)."""
    exogenous = {k: c for k, c in EXOGENOUS.items() if available is None or c in available}
    return Controller(settings, SPECS, exogenous, it_peak_kw, tariff=tariff)


# "Run everything" (Default-state preset, and the tests' all-on case): every
# module on, wired the way the modules ran before the state machine (D-054
# keeps it as a starting point): brine separation first on the data center's
# heat (after the greenhouse, D-061), then power generation and hot water
# storage; the ice mixer cools the
# data center from ice storage (and brine separation's brine); recovered water
# goes back to ice storage; PV generates.
RUN_EVERYTHING: tuple[Action, ...] = (
    Action(target=greenhouse.KEY, setting=greenhouse.HEAT_IN, to=DATA_CENTER),
    Action(target=brine_separation.KEY, setting="heat_in", value=100, to=DATA_CENTER),
    Action(target=power_generation.KEY, setting="heat_in", to=DATA_CENTER),
    Action(target=power_generation.KEY, setting="cooling_in", to=COOLANT),
    Action(target=hot_water_storage.KEY, setting="heat_in", to=DATA_CENTER),
    Action(target=ice_storage.KEY, setting=ice_storage.CLEARED),
    Action(target=ice_storage.KEY, setting="ice_out", to=ice_mixer.KEY),
    Action(target=brine_separation.KEY, setting="brine_out", to=ice_mixer.KEY),
    Action(target=brine_separation.KEY, setting="water_out", to=ice_storage.KEY),
    Action(target=ice_mixer.KEY, setting="cooling_out", to=DATA_CENTER),
    Action(target=solar_pv.KEY, setting=solar_pv.GENERATE),
)


def run_everything_in_default(settings: ControlSettings) -> ControlSettings:
    """Replace the Default state's THENs with `RUN_EVERYTHING` (keeps its IT load)."""
    kept = tuple(a for a in settings.default.actions if a.target == DATA_CENTER)
    return settings.replace(settings.default.model_copy(update={"actions": kept + RUN_EVERYTHING}))


ALL_ON = run_everything_in_default(ControlSettings())
