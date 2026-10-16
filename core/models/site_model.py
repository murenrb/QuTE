"""Assemble and run the full hourly site model."""

from collections.abc import Iterable

import pandas as pd

from core.config.defaults import IceMixerFluid, ModelAssumptions
from core.control.catalog import controller
from core.domain.control import ControlSettings
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.modules import ModuleContext, ModuleSettings
from core.domain.utility import UtilityTariff
from core.models.brine_separation import BrineSeparation
from core.models.datacenter import CoolantTemperature, DataCenterNode
from core.models.greenhouse import KEY as GREENHOUSE_KEY
from core.models.greenhouse import GreenhouseHeating, GreenhouseLoad, coil_water_c
from core.models.grid import GridBalance, GridDraw, electrical_stack
from core.models.hot_water_storage import HotWaterStorage
from core.models.ice_mixer import IceMixer
from core.models.ice_storage import IceStorage
from core.models.power_generation import PowerGeneration
from core.models.solar_pv import PvOutput, PvSite, SolarPV
from core.models.utility import UtilityCost, UtilityPrice
from core.timeseries import streams as st
from core.timeseries.frame import build_hourly_frame
from core.timeseries.pipeline import Subsystem, run_pipeline
from core.timeseries.solver import HourlyNode, HourlySolver
from core.weather.tmy import WeatherMeta


def coupled_nodes(
    modules: ModuleSettings,
    ctx: ModuleContext,
    t: DataCenterType,
    assumptions: ModelAssumptions,
) -> tuple[HourlyNode, ...]:
    """The data center and every enabled module as solver nodes (D-052, D-054),
    in the order each hour runs them; what they exchange is set by the hour's
    state. The grid draw comes last (the state machine's grid IF).
    """
    mixer = modules.ice_mixer
    if mixer.enabled:
        if not modules.ice_storage.enabled:
            raise ValueError("The ice mixer needs ice storage turned on")
        if mixer.fluid is IceMixerFluid.BRINE and not modules.brine_separation.enabled:
            raise ValueError("The ice mixer on brine needs brine separation turned on")
    nodes: list[HourlyNode] = [DataCenterNode(t, assumptions)]
    if modules.brine_separation.enabled:
        brine = modules.brine_separation.resolved(ctx)
        nodes.append(BrineSeparation(brine, t.t_return_c, assumptions.it_parasitic_frac))
    if modules.hot_water_storage.enabled:
        hws = modules.hot_water_storage.resolved(ctx)
        sinks = {}  # what each receiver cools its hot water to (D-064)
        if modules.greenhouse.placed:
            sinks[GREENHOUSE_KEY] = coil_water_c(modules.greenhouse.t_set_c)
        nodes.append(HotWaterStorage(hws, t.t_supply_c, t.t_return_c, sinks))
    if mixer.enabled:  # before power generation, which may run on its temperature
        nodes.append(IceMixer(mixer, modules.brine_separation.props))
    if modules.power_generation.enabled:
        pg = modules.power_generation.resolved(ctx)
        nodes.append(PowerGeneration(pg, t_return_c=t.t_return_c))
    if modules.ice_storage.enabled:
        nodes.append(IceStorage(modules.ice_storage.resolved(ctx)))
    if modules.greenhouse.placed:
        nodes.append(GreenhouseHeating(modules.greenhouse.t_set_c, t.t_return_c))
    if modules.solar_pv.placed:
        nodes.append(PvOutput())
    elec = tuple(
        spec.name for n in nodes for spec in n.writes if spec.name.startswith(st.ELEC_PREFIX)
    )
    nodes.append(GridDraw(reads=elec))
    return tuple(nodes)


def _context(
    it_peak_mw: float | None,
    site_lat: float | None,
    dc: DataCenter | None,
    assumptions: ModelAssumptions | None,
) -> ModuleContext:
    t = dc.dc_type if dc is not None else None
    return ModuleContext(
        it_peak_mw=it_peak_mw,
        site_lat=site_lat,
        t_supply_c=t.t_supply_c if t else None,
        t_return_c=t.t_return_c if t else None,
        it_parasitic_frac=assumptions.it_parasitic_frac if assumptions else None,
    )


def module_subsystems(
    modules: ModuleSettings,
    weather: WeatherMeta | None,
    site_lat: float | None = None,
    dc_roof_m2: float = 0.0,
) -> list[Subsystem]:
    """Module parts that need only weather (run before the solver). Add new
    modules here and / or in `coupled_nodes` (architecture.md → Writing a module)."""
    subs: list[Subsystem] = []
    if modules.solar_pv.placed:
        if weather is None:
            raise ValueError("Solar PV needs the weather site (lat/lon/time zone)")
        subs.append(SolarPV(modules.solar_pv, PvSite.from_weather(weather), site_lat, dc_roof_m2))
    if modules.greenhouse.placed:
        subs.append(GreenhouseLoad(modules.greenhouse))
    return subs


def site_subsystems(
    dc: DataCenter,
    assumptions: ModelAssumptions,
    modules: ModuleSettings | None = None,
    weather: WeatherMeta | None = None,
    initial_columns: Iterable[str] = (),
    site_lat: float | None = None,
    tariff: UtilityTariff | None = None,
    control: ControlSettings | None = None,
) -> list[Subsystem]:
    modules = modules or ModuleSettings()
    tariff = tariff or UtilityTariff()
    subs: list[Subsystem] = [
        CoolantTemperature(dc.dc_type, assumptions),
        UtilityPrice(tariff),  # known up front, so the state machine can test it
    ]
    roof_m2 = dc.footprint.area_m2 if dc.footprint is not None else 0.0
    subs += module_subsystems(modules, weather, site_lat, roof_m2)
    # The state machine picks each hour's state; the solver steps the data
    # center and the modules under it (D-052, D-053, D-054).
    ctx = _context(dc.it_load_peak_mw, site_lat, dc, assumptions)
    nodes = coupled_nodes(modules, ctx, dc.dc_type, assumptions)
    before_solver = set(initial_columns) | {c for s in subs for c in s.provides}
    ctl = controller(control or ControlSettings(), dc.it_load_peak_kw, tariff, before_solver)
    subs.append(HourlySolver(nodes, ctl))
    available = set(initial_columns) | {c for s in subs for c in s.provides}
    # Net grid load sums the stacked electrical columns that will actually exist.
    subs.append(GridBalance(requires=tuple(c for c in electrical_stack() if c in available)))
    subs.append(UtilityCost())  # bills the net grid load (D-043)
    return subs


def run_site_model(
    dc: DataCenter,
    weather: pd.DataFrame,
    assumptions: ModelAssumptions,
    modules: ModuleSettings | None = None,
    weather_meta: WeatherMeta | None = None,
    site_lat: float | None = None,
    tariff: UtilityTariff | None = None,
    control: ControlSettings | None = None,
) -> pd.DataFrame:
    """site_lat: the map location's latitude (default PV tilt follows it).
    control: the state machine (None = only the Default state, D-053)."""
    df = build_hourly_frame(weather, dc.daily_profile_kw)
    subs = site_subsystems(
        dc, assumptions, modules, weather_meta, df.columns, site_lat, tariff, control
    )
    return run_pipeline(df, subs)
