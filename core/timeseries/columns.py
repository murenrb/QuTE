"""Registry of hourly DataFrame columns (docs/data-model.md).

Plots are built from this registry, so a new subsystem's columns appear in the
right chart just by registering them here.
"""

from dataclasses import dataclass
from enum import StrEnum


class PlotGroup(StrEnum):
    """One view of a results row (D-060): each row shows one group at a time,
    picked with the buttons on the row (app/components/plots.py → ROWS)."""

    NONE = "none"
    AMBIENT = "ambient"  # temperatures
    SUN = "sun"
    THERMAL = "thermal"
    ELECTRICAL = "electrical"
    UTILITY = "utility"
    ENERGY_PRICE = "energy_price"
    DEMAND_CHARGE = "demand_charge"
    CONTROL = "control"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    unit: str
    label: str
    plot_group: PlotGroup = PlotGroup.NONE
    stacked: bool = False  # stacked area (True) vs. line (False)
    stack_order: int = 0  # lower = closer to the axis
    color: str | None = None
    # Hatched band: heat that is not the data center's this hour (from a store,
    # D-065); it sits on top of the stack, above the data center's own heat.
    hatched: bool = False


_REGISTRY: dict[str, ColumnSpec] = {}


def register(spec: ColumnSpec) -> ColumnSpec:
    if spec.name in _REGISTRY and _REGISTRY[spec.name] != spec:
        raise ValueError(f"Column {spec.name!r} already registered with a different spec")
    _REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> ColumnSpec:
    return _REGISTRY[name]


def all_columns() -> list[ColumnSpec]:
    return list(_REGISTRY.values())


def columns_in_group(group: PlotGroup) -> list[ColumnSpec]:
    """Columns for one chart, stacked traces ordered bottom-to-top."""
    cols = [c for c in _REGISTRY.values() if c.plot_group is group]
    return sorted(cols, key=lambda c: (not c.stacked, c.stack_order))


# Categorical data colors (dataviz reference palette, validated for CVD
# separation; fixed order per chart, never cycled). Structure stays greyscale.
SERIES_1 = "#2a78d6"  # blue
SERIES_2 = "#eb6834"  # orange
SERIES_3 = "#1baf7a"  # aqua
SERIES_4 = "#eda100"  # yellow
SERIES_5 = "#e87ba4"  # magenta
SERIES_6 = "#8f4a1e"  # brown (power generation; checked for CVD vs. neighbours)
SERIES_7 = "#4a3aa7"  # violet
SERIES_8 = "#2bb3c0"  # cyan (hot water storage; checked for CVD vs. neighbours)
SERIES_9 = "#b04a8a"  # plum (brine separation; checked for CVD vs. neighbours)
SERIES_10 = "#5f8f1c"  # leaf green (greenhouse; not next to the ice mixer's aqua in the stack)
NET_LINE = "#000000"

# --- Step 1 columns --------------------------------------------------------
TIMESTAMP = "timestamp"

# The planned (daily-profile) IT load; the state machine sets how much of it runs
# each hour, giving the actual IT load (D-053).
IT_LOAD_PLAN_KW = register(ColumnSpec("it_load_plan_kw", "kW", "Planned IT load")).name
IT_LOAD_KW = register(
    ColumnSpec("it_load_kw", "kW", "IT load", PlotGroup.ELECTRICAL, True, 1, color=SERIES_1)
).name
CONTROL_STATE = register(
    ColumnSpec(
        "control_state",
        "-",
        "Control state (0 = Default, then priority order)",
        PlotGroup.CONTROL,
        color=NET_LINE,
    )
).name
TDB_C = register(ColumnSpec("tdb_c", "°C", "Dry bulb", PlotGroup.AMBIENT, color=SERIES_1)).name
TWB_C = register(ColumnSpec("twb_c", "°C", "Wet bulb", PlotGroup.AMBIENT, color=SERIES_2)).name
TDP_C = register(ColumnSpec("tdp_c", "°C", "Dew point", PlotGroup.AMBIENT, color=SERIES_3)).name
RH_PCT = register(ColumnSpec("rh_pct", "%", "Relative humidity")).name
GHI_W_M2 = register(ColumnSpec("ghi_w_m2", "W/m²", "GHI", PlotGroup.SUN, color=SERIES_4)).name
# Solar resource + wind, used by the PV module (PVWatts needs beam + diffuse).
DNI_W_M2 = register(ColumnSpec("dni_w_m2", "W/m²", "DNI")).name
DHI_W_M2 = register(ColumnSpec("dhi_w_m2", "W/m²", "DHI")).name
WIND_M_S = register(ColumnSpec("wind_m_s", "m/s", "Wind speed")).name
T_AMBIENT_REJ_C = register(ColumnSpec("t_ambient_rej_c", "°C", "Heat rejection ambient")).name
# Cold supply water to IT (D-047): setpoint with chillers; with free cooling it
# floats at ambient + approach, clamped to [min, setpoint]. Modules that reject
# into the cooling loop use it as their coolant / cold side.
T_COOLANT_C = register(ColumnSpec("t_coolant_c", "°C", "Supply (coolant) water temperature")).name
IT_PARASITIC_KW = register(
    ColumnSpec(
        "it_parasitic_kw", "kW", "IT parasitics", PlotGroup.ELECTRICAL, True, 2, color=SERIES_2
    )
).name
# Data center heat handed to modules (brine separation, power generation, hot
# water storage) as the state links them (D-054).
HEAT_OFFTAKE_KWTH = register(ColumnSpec("heat_offtake_kwth", "kW_th", "Heat offtake")).name
# Brine separation (D-048): its boiler heat, which its condenser passes on
# (power generation, ice mixer, supply coolant) — a line, not part of the stack.
BRINE_HEAT_KWTH = register(
    ColumnSpec("brine_heat_kwth", "kW_th", "Brine separation", PlotGroup.THERMAL, color=SERIES_9)
).name
BRINE_MASS_KG = register(ColumnSpec("brine_mass_kg", "kg", "Brine in tank")).name
BRINE_CONC_WT_PCT = register(ColumnSpec("brine_conc_wt_pct", "wt%", "Brine concentration")).name
BRINE_SOC_FRAC = register(
    ColumnSpec("brine_soc_frac", "-", "Brine tank state of charge (volume / tank volume)")
).name
BRINE_WATER_OUT_KG_H = register(
    ColumnSpec("brine_water_out_kg_h", "kg/h", "Water recovered from brine")
).name
BRINE_WATER_TO_ICE_KG_S = register(
    ColumnSpec("brine_water_to_ice_kg_s", "kg/s", "Recovered water into ice storage")
).name
BRINE_OUT_KG_S = register(ColumnSpec("brine_out_kg_s", "kg/s", "Brine to the ice mixer")).name
BRINE_IN_KG_S = register(
    ColumnSpec("brine_in_kg_s", "kg/s", "Diluted brine back from the ice mixer")
).name
# The thermal stack shows where the data center's heat (IT + parasitics) ends
# up each hour (D-054): free cooling + chillers + ice mixer + converted to power
# + hot water storage (net) = cooling_total_kwth. Heat modules reject into the
# supply coolant is in free cooling / chillers.
COOLING_TOTAL_KWTH = register(ColumnSpec("cooling_total_kwth", "kW_th", "Total cooling load")).name
# Heat needing mechanical cooling (hours without free cooling): what the data
# center cools itself plus what modules reject into the coolant, before the ice
# mixer takes the data center's share. The chillers carry cooling_chiller_kwth.
COOLING_MECH_KWTH = register(
    ColumnSpec("cooling_mech_kwth", "kW_th", "Mechanical cooling demand")
).name
COOLING_CHILLER_KWTH = register(
    ColumnSpec(
        "cooling_chiller_kwth", "kW_th", "Chillers", PlotGroup.THERMAL, True, 1, color=SERIES_1
    )
).name
# Ice storage duties are an FYI at h_f(0); the cooling the site sees is the ice
# mixer's (D-050), so these are not in the thermal stack.
ICE_INSTANT_KWTH = register(ColumnSpec("ice_instant_kwth", "kW_th", "Ice (made & taken)")).name
ICE_DISCHARGE_KWTH = register(ColumnSpec("ice_discharge_kwth", "kW_th", "Ice from storage")).name
# Everything rejected by the dry coolers / towers without a chiller (hours with
# free cooling): the data center's own heat plus modules' coolant rejection.
COOLING_FREE_KWTH = register(
    ColumnSpec(
        "cooling_free_kwth", "kW_th", "Free cooling", PlotGroup.THERMAL, True, 4, color=SERIES_2
    )
).name
# Power generation (D-045, D-054): heat in = power + heat rejected to its cold
# side (coolant or ice mixer, so already in the stack); the power is the stack's
# "converted to power" band.
POWER_GEN_REJECT_KWTH = register(
    ColumnSpec("power_gen_reject_kwth", "kW_th", "Heat rejected from waste heat to power")
).name
POWER_GEN_POWER_KWTH = register(
    ColumnSpec(
        "power_gen_power_kwth",
        "kW_th",
        "Converted to power",
        PlotGroup.THERMAL,
        True,
        5,
        color=SERIES_6,
    )
).name
POWER_GEN_HEAT_IN_KWTH = register(
    ColumnSpec("power_gen_heat_in_kwth", "kW_th", "Heat into waste heat to power")
).name
POWER_GEN_EFF = register(ColumnSpec("power_gen_eff", "-", "Power cycle efficiency")).name
HWS_CHARGE_KWTH = register(
    ColumnSpec("hws_charge_kwth", "kW_th", "Hot water storage charging")
).name
HWS_DISCHARGE_KWTH = register(
    ColumnSpec("hws_discharge_kwth", "kW_th", "Hot water storage discharging")
).name
# Net heat into storage (charge − discharge): negative while it gives heat back.
HWS_NET_KWTH = register(ColumnSpec("hws_net_kwth", "kW_th", "Hot water storage (net)")).name
# The thermal-stack band (D-065): charge − discharge, leaving out what it gives
# the greenhouse (that is the hatched band on top), so heat stored for the
# greenhouse isn't drawn as negative heat.
HWS_STACK_KWTH = register(
    ColumnSpec(
        "hws_stack_kwth",
        "kW_th",
        "Hot water storage",
        PlotGroup.THERMAL,
        True,
        6,
        color=SERIES_8,
    )
).name
HWS_SOC_FRAC = register(ColumnSpec("hws_soc_frac", "-", "Hot water storage state of charge")).name
HWS_T_HOT_C = register(ColumnSpec("hws_t_hot_c", "°C", "Hot tank temperature")).name
HWS_T_COLD_C = register(ColumnSpec("hws_t_cold_c", "°C", "Cold tank temperature")).name
# Facility-side water leaving the storage HX — for downstream processes.
HWS_T_SYS_C = register(
    ColumnSpec("hws_t_sys_c", "°C", "Facility water temperature from hot water storage")
).name
ICE_CHARGE_KWTH = register(ColumnSpec("ice_charge_kwth", "kW_th", "Ice into storage")).name
ICE_SOC_FRAC = register(ColumnSpec("ice_soc_frac", "-", "Ice tank state of charge")).name
ICE_WATER_SOC_FRAC = register(
    ColumnSpec("ice_water_soc_frac", "-", "Ice storage water tank state of charge")
).name
# Ice storage mass flows (D-049): ice handed to other modules, water taken back.
ICE_SUPPLIED_KG_S = register(ColumnSpec("ice_supplied_kg_s", "kg/s", "Ice supplied")).name
ICE_WATER_IN_KG_S = register(
    ColumnSpec("ice_water_in_kg_s", "kg/s", "Water accepted into ice storage")
).name
# Ice mixer (D-050, D-052): the settled flows of each hour. Its cooling (to the
# data center, power generation, brine separation) is in the thermal stack.
ICE_MIX_Q_KWTH = register(
    ColumnSpec("ice_mix_q_kwth", "kW_th", "Ice mixer", PlotGroup.THERMAL, True, 2, color=SERIES_3)
).name
ICE_MIX_T_C = register(ColumnSpec("ice_mix_t_c", "°C", "Ice mixer temperature")).name
ICE_MIX_ICE_KG_S = register(
    ColumnSpec("ice_mix_ice_kg_s", "kg/s", "Ice used by the ice mixer")
).name
ICE_MIX_BRINE_KG_S = register(
    ColumnSpec("ice_mix_brine_kg_s", "kg/s", "Brine used by the ice mixer")
).name
ICE_MIX_BRINE_OUT_KG_S = register(
    ColumnSpec("ice_mix_brine_out_kg_s", "kg/s", "Diluted brine from the ice mixer")
).name
ICE_MIX_BRINE_OUT_WT_PCT = register(
    ColumnSpec("ice_mix_brine_out_wt_pct", "wt%", "Diluted brine concentration")
).name
ICE_MIX_WATER_OUT_KG_S = register(
    ColumnSpec("ice_mix_water_out_kg_s", "kg/s", "Melt water from the ice mixer")
).name
COP_MECH = register(ColumnSpec("cop_mech", "-", "Mechanical COP")).name
# Greenhouse (D-061): the load comes from weather alone (before the solver);
# the heat it gets from the data center is a destination of the data center's
# heat, so it is in the thermal stack.
GREENHOUSE_LOSS_KWTH = register(
    ColumnSpec("greenhouse_loss_kwth", "kW_th", "Greenhouse heat loss through the glass")
).name
GREENHOUSE_SOLAR_KWTH = register(
    ColumnSpec("greenhouse_solar_kwth", "kW_th", "Greenhouse solar gain")
).name
GREENHOUSE_DEMAND_KWTH = register(
    ColumnSpec("greenhouse_demand_kwth", "kW_th", "Greenhouse heating demand")
).name
GREENHOUSE_VENTED_KWTH = register(
    ColumnSpec("greenhouse_vented_kwth", "kW_th", "Greenhouse excess heat vented")
).name
# Greenhouse heat straight from the data center's return water (D-065).
GREENHOUSE_HEAT_KWTH = register(
    ColumnSpec(
        "greenhouse_heat_kwth",
        "kW_th",
        "Greenhouse",
        PlotGroup.THERMAL,
        True,
        7,
        color=SERIES_10,
    )
).name
# Greenhouse heat from a module, not the data center (D-064, D-065): a hatched
# band on top of the whole stack, above the data center's heat.
STACK_TOP = 100
GREENHOUSE_HEAT_HWS_KWTH = register(
    ColumnSpec(
        "greenhouse_heat_hws_kwth",
        "kW_th",
        "Greenhouse from hot water storage",
        PlotGroup.THERMAL,
        True,
        STACK_TOP,
        color=SERIES_10,
        hatched=True,
    )
).name
GREENHOUSE_UNMET_KWTH = register(
    ColumnSpec("greenhouse_unmet_kwth", "kW_th", "Greenhouse heat not met")
).name
# Generation is negative: it reduces net grid load (GridBalance sums the stack).
PV_KW = register(
    ColumnSpec("pv_kw", "kW", "Solar PV", PlotGroup.ELECTRICAL, True, 4, color=SERIES_4)
).name
# What the array can make (≥ 0), before the state's THEN (curtailed when off).
PV_AVAILABLE_KW = register(ColumnSpec("pv_available_kw", "kW", "PV output (available)")).name
ICE_MAKER_ELEC_KW = register(
    ColumnSpec(
        "ice_maker_elec_kw", "kW", "Ice maker", PlotGroup.ELECTRICAL, True, 5, color=SERIES_5
    )
).name
POWER_GEN_KW = register(
    ColumnSpec(
        "power_gen_kw", "kW", "Waste heat to power", PlotGroup.ELECTRICAL, True, 6, color=SERIES_6
    )
).name
COOLING_ELEC_KW = register(
    ColumnSpec(
        "cooling_elec_kw",
        "kW",
        "Cooling electrical",
        PlotGroup.ELECTRICAL,
        True,
        3,
        color=SERIES_3,
    )
).name
GRID_NET_KW = register(
    ColumnSpec("grid_net_kw", "kW", "Net grid load", PlotGroup.ELECTRICAL, color=NET_LINE)
).name

# --- Utility (D-043): $ per hour unless noted --------------------------------------
ENERGY_PRICE_USD_KWH = register(
    ColumnSpec(
        "energy_price_usd_kwh", "$/kWh", "Energy price", PlotGroup.ENERGY_PRICE, color=SERIES_1
    )
).name
DEMAND_CHARGE_USD_KW = register(
    ColumnSpec(
        "demand_charge_usd_kw", "$/kW", "Demand charge", PlotGroup.DEMAND_CHARGE, color=SERIES_2
    )
).name
ENERGY_COST_USD = register(ColumnSpec("energy_cost_usd", "$", "Energy cost")).name
DEMAND_COST_POTENTIAL_USD = register(
    ColumnSpec("demand_cost_potential_usd", "$", "Potential demand cost")
).name
DEMAND_COST_USD = register(ColumnSpec("demand_cost_usd", "$", "Demand charge (monthly peak)")).name
UTILITY_COST_USD = register(ColumnSpec("utility_cost_usd", "$", "Utility cost")).name
# Running totals through the year (D-044) — what the Utility subplot shows, as lines.
CUM_ENERGY_COST_USD = register(
    ColumnSpec("cum_energy_cost_usd", "$", "Energy cost to date", PlotGroup.UTILITY, color=SERIES_1)
).name
CUM_DEMAND_COST_USD = register(
    ColumnSpec(
        "cum_demand_cost_usd", "$", "Demand charges to date", PlotGroup.UTILITY, color=SERIES_2
    )
).name
CUM_UTILITY_COST_USD = register(
    ColumnSpec(
        "cum_utility_cost_usd", "$", "Utility cost to date", PlotGroup.UTILITY, color=NET_LINE
    )
).name
