"""Single source of truth for engineering constants and input defaults.

Mirrors docs/assumptions.md and docs/data-model.md — change both together.
Models never read these module globals directly; values are passed in through
config objects so they can later become user-editable without touching models.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class CoolingType(StrEnum):
    DRY = "dry"
    EVAPORATIVE = "evaporative"


class PvArrayType(IntEnum):
    """PVWatts array_type codes."""

    FIXED_OPEN_RACK = 0
    FIXED_ROOF_MOUNT = 1
    ONE_AXIS = 2
    ONE_AXIS_BACKTRACKING = 3
    TWO_AXIS = 4


class PvModuleType(IntEnum):
    """PVWatts module_type codes."""

    STANDARD = 0
    PREMIUM = 1
    THIN_FILM = 2


class HwsConnection(StrEnum):
    """How the hot water storage tanks connect to the data center loop."""

    DIRECT = "direct"  # tank water is the loop water: no pinch
    INDIRECT = "indirect"  # through a heat exchanger: pinch on both ends


class BrineType(StrEnum):
    POTASSIUM_ACETATE = "potassium_acetate"


class IceMixerFluid(StrEnum):
    """What the ice is melted into (docs/models/ice-mixer.md)."""

    WATER = "water"  # pure ice melts at 0 °C; melt water returns to ice storage
    BRINE = "brine"  # concentrated brine from brine separation is diluted below 0 °C


class HwsTankType(StrEnum):
    TWO_TANK = "two_tank"
    THERMOCLINE = "thermocline"  # one tank, perfect stratification assumed


@dataclass(frozen=True)
class SliderSpec:
    """Range, default and step for a numeric UI input."""

    min: float
    max: float
    default: float
    step: float
    units: str

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max


@dataclass(frozen=True)
class DataCenterTypeInputs:
    """UI ranges/defaults for DataCenterType fields (docs/data-model.md)."""

    t_supply_c: SliderSpec = SliderSpec(5, 80, 40, 1, "°C")  # setpoint
    # Free cooling lets the supply float down to ambient + approach, no lower
    # than this minimum (D-047).
    t_supply_min_c: SliderSpec = SliderSpec(5, 80, 5, 1, "°C")
    t_return_c: SliderSpec = SliderSpec(5, 80, 50, 1, "°C")
    rack_density_kw: SliderSpec = SliderSpec(5, 300, 50, 1, "kW/rack")
    white_space_ratio: SliderSpec = SliderSpec(0.10, 1.00, 0.65, 0.01, "fraction")
    redundancy_x: SliderSpec = SliderSpec(1, 3, 1, 1, "")
    redundancy_y: SliderSpec = SliderSpec(1, 10, 1, 1, "")
    ups_area_sqft_per_kw: SliderSpec = SliderSpec(0, 4, 1.0, 0.1, "sqft/kW")
    generator_area_sqft_per_kw: SliderSpec = SliderSpec(0, 6, 1.5, 0.1, "sqft/kW")
    switchgear_area_sqft_per_kw: SliderSpec = SliderSpec(0, 2, 0.5, 0.1, "sqft/kW")
    cooling_type: CoolingType = CoolingType.DRY


@dataclass(frozen=True)
class DataCenterInputs:
    """UI range/default for per-facility inputs (docs/workflow/01-setup-tabs.md §3.2)."""

    it_load_peak_mw: SliderSpec = SliderSpec(0.1, 2000, 10, 0.1, "MW")


@dataclass(frozen=True)
class SolarPVInputs:
    """Solar PV module inputs (docs/models/solar-pv.md). Ranges follow PVWatts V8;
    defaults are the PVWatts web defaults; size comes from the drawn area."""

    # Capacity = snapped area × density (D-036); kW DC per sqft of land.
    power_density_w_sqft: SliderSpec = SliderSpec(5, 9, 6.5, 0.25, "W/sqft")
    # Default tilt = |site latitude|; 20° is only the fallback without a location.
    tilt_deg: SliderSpec = SliderSpec(0, 90, 20, 1, "°")
    # Default azimuth faces the equator (180° north of it, 0° south of it); 180° is
    # the fallback without a location.
    azimuth_deg: SliderSpec = SliderSpec(0, 359, 180, 1, "°")
    azimuth_southern_hemisphere_deg: float = 0.0
    losses_pct: SliderSpec = SliderSpec(-5, 99, 14.08, 0.01, "%")
    dc_ac_ratio: SliderSpec = SliderSpec(0.5, 2.0, 1.2, 0.05, "")
    gcr: SliderSpec = SliderSpec(0.01, 0.99, 0.4, 0.01, "")
    inv_eff_pct: SliderSpec = SliderSpec(90, 99.5, 96, 0.5, "%")
    array_type: PvArrayType = PvArrayType.FIXED_OPEN_RACK
    module_type: PvModuleType = PvModuleType.STANDARD


@dataclass(frozen=True)
class IceStorageInputs:
    """Ice storage module inputs (docs/models/ice-storage.md). Curve fits are of
    ambient (rejection) temperature t [°C]: y = a·t² + b·t + c, capped at the
    value at minimum compressor discharge pressure (`*_max`)."""

    # Default size follows the data center: 65 TR per MW of IT load (D-042);
    # the slider is logarithmic between these limits.
    ice_maker_size_tr: SliderSpec = SliderSpec(10, 200_000, 650, 1, "TR")
    tr_per_mw_it: float = 65.0
    tank_charge_time_h: SliderSpec = SliderSpec(6, 72, 24, 1, "h")
    # Ice tank at hour 0: empty, so ice + water = one full tank (owner, D-058).
    soc_start_frac: SliderSpec = SliderSpec(0, 1, 0.0, 0.05, "fraction")
    # Water tank (same size as the ice tank) at hour 0: 1 = full of water.
    water_soc_start_frac: SliderSpec = SliderSpec(0, 1, 1.0, 0.05, "fraction")
    # Footprint on the map = tank capacity / energy density (D-041).
    energy_density_kwh_sqft: SliderSpec = SliderSpec(1, 100, 15, 0.5, "kWh_th/sqft")
    cop_max: float = 6.0  # ice-maker COP at min. discharge pressure
    capacity_factor_max: float = 1.23  # thermal capacity / nameplate at min. discharge pressure
    cop_coeff_a: float = 0.0011
    cop_coeff_b: float = -0.1503
    cop_coeff_c: float = 6.562
    capacity_coeff_a: float = -0.001
    capacity_coeff_b: float = -0.0023
    capacity_coeff_c: float = 1.2453


@dataclass(frozen=True)
class PowerGenerationInputs:
    """Transcritical CO2 power cycle on data center waste heat
    (docs/models/power-generation.md, D-045). Scaled in inputs: block area =
    rated MWe × power density."""

    carnot_pct: SliderSpec = SliderSpec(10, 50, 30, 1, "% of Carnot")
    # Rated (generator) output at the max cold-side temperature, as % of the
    # IT load peak, so it follows the IT load (D-063; was kWe, log slider).
    rated_pct_of_it: SliderSpec = SliderSpec(0.5, 150, 2, 0.5, "% of IT load")
    # Design cold-side (condensing) temperature. The UI caps the slider at the
    # free-cooling cutoff (t_supply − t_approach) of the data center type.
    t_cold_max_c: SliderSpec = SliderSpec(0, 80, 10, 0.5, "°C")
    power_density_sqft_mwe: SliderSpec = SliderSpec(1000, 3000, 2000, 50, "sqft/MWe")


@dataclass(frozen=True)
class HotWaterStorageInputs:
    """Hot water (sensible) storage on the data center loop
    (docs/models/hot-water-storage.md, D-046). Scaled in inputs: block sized
    from the tank cylinder(s)."""

    # Tank volume = IT kW × hours × 3600 / ((T_return − T_supply) × cp × rho)
    storage_hours: SliderSpec = SliderSpec(4, 72, 12, 1, "h")
    connection: HwsConnection = HwsConnection.INDIRECT
    tank_type: HwsTankType = HwsTankType.TWO_TANK
    tank_height_m: SliderSpec = SliderSpec(3, 30, 12, 0.5, "m")
    pinch_indirect_c: float = 2.0  # heat exchanger approach; direct = 0
    pinch_direct_c: float = 0.0
    # Clear space around the tank(s) in the default block (each side).
    buffer_ft: float = 20.0


@dataclass(frozen=True)
class BrineProperties:
    """Fits in c = mass fraction of salt (owner, 2026-10-05)."""

    label: str
    # Water activity a_w = a·c³ + b·c² + d·c + e
    aw_coeffs: tuple[float, float, float, float]
    # Freeze point fp = a·c³ + b·c² + d·c + e
    fp_coeffs: tuple[float, float, float, float]
    # Freeze point c = a·t³ + b·t² + d·t + e
    c_coeffs: tuple[float, float, float, float]
    # Density rho = m·c + b [kg/m³]
    rho_coeffs: tuple[float, float]
    # Solvation heat per kg of ice melted into brine at c: h = k·(c/(1 − c))² [kJ/kg]
    h_solv_coeff: float


BRINES: dict[BrineType, BrineProperties] = {
    BrineType.POTASSIUM_ACETATE: BrineProperties(
        label="Potassium acetate",
        aw_coeffs=(1.6292, -2.678, -0.0096, 0.9979),
        fp_coeffs=(-137.95, -173.45, -11.85, -0.2351),
        c_coeffs=(-0.000004, -0.000468, -0.0211, 0.01346),
        rho_coeffs=(642.08, 980.82),
        h_solv_coeff=-64.0,
    ),
}


@dataclass(frozen=True)
class BrineSeparationInputs:
    """Brine separation by single-stage evaporation on data center heat
    (docs/models/brine-separation.md, D-048). Scaled in inputs: one tank."""

    brine_type: BrineType = BrineType.POTASSIUM_ACETATE
    # Concentration range [wt %]: the tank starts at the low end and stops at the high.
    conc_wt_pct: SliderSpec = SliderSpec(0, 50, 20, 1, "wt%")  # default = low end
    conc_high_default_wt_pct: float = 40.0
    concentrate_hours: SliderSpec = SliderSpec(6, 72, 24, 1, "h")
    h_vap_kj_kg: float = 2382.0  # latent heat of water at 50 °C
    pinch_boiler_c: float = 2.0  # brine = hot water − pinch
    pinch_condenser_c: float = 2.0  # condensing ≥ coolant + pinch
    tank_height_m: float = 12.0
    buffer_ft: float = 20.0  # clear space each side of the tank in the default block
    # Antoine constants for water, °C / mmHg, valid 1–100 °C (A cancels out).
    antoine_b: float = 1730.63
    antoine_c: float = 233.426


@dataclass(frozen=True)
class IceProperties:
    """Latent heat of ice vs. melt temperature (owner, Kirchhoff):
    h_f(t) = h_f(0) + (cp_water,avg − cp_ice,avg)·t, each avg of the pure value and
    the fit at t: cp_ice(t) = a·t + b, cp_water(t) = a·t² + b·t + c [kJ/kg·K]."""

    cp_ice_pure_kj_kgk: float = 2.2
    cp_water_pure_kj_kgk: float = 4.18
    cp_ice_coeffs: tuple[float, float] = (0.0067, 2.0725)
    cp_water_coeffs: tuple[float, float, float] = (0.0016, 0.0251, 4.2441)


@dataclass(frozen=True)
class IceMixerInputs:
    """Ice mixer: melts ice from ice storage into water or brine to supply cooling
    (docs/models/ice-mixer.md, D-050). No footprint (equipment in the other blocks)."""

    fluid: IceMixerFluid = IceMixerFluid.WATER
    # Catch-all for imperfectly recuperated streams: real h = ideal h × recup.
    recup_eta_pct: SliderSpec = SliderSpec(50, 90, 70, 1, "%")
    # Mixed temperature = brine freeze point × mix: 100 % (at the incoming brine's
    # freeze point, infinite brine) is impossibly ideal, so the slider stops at 90.
    mix_eta_pct: SliderSpec = SliderSpec(50, 90, 80, 1, "%")


@dataclass(frozen=True)
class GreenhouseInputs:
    """Greenhouse heating load: Q = U·A_cover·(T_set − T_amb) − τ·GHI·A_floor
    (docs/models/greenhouse.md, D-061, D-062). Size = the drawn floor area."""

    # Owner's sliders.
    transmissivity_pct: SliderSpec = SliderSpec(80, 100, 90, 1, "%")  # glass, for GHI
    # Overall U of the covering, from an extension guide's table (owner, D-062).
    u_w_m2k: SliderSpec = SliderSpec(5, 10, 7.5, 0.1, "W/m²K")
    t_set_c: SliderSpec = SliderSpec(15, 40, 20, 0.5, "°C")  # inside air setpoint
    # Glass area / floor area: roof + walls of a gutter-connected house (owner).
    cover_to_floor_ratio: float = 1.3
    # Heating coil (water → greenhouse air): the water leaves it no colder than
    # setpoint + approach, so a source must be warmer than that to give heat
    # (owner, D-064: 10 K, as for the other air coils, cf. t_approach_c).
    coil_approach_c: float = 10.0
    # Shown under the U slider (owner): where typical U-values come from.
    u_guide_url: str = (
        "https://aggie-horticulture.tamu.edu/ornamental/greenhouse-management/greenhouse-heating/"
    )


@dataclass(frozen=True)
class ControlDefaults:
    """State machine THEN values (docs/control.md, D-053, D-054). A state is a
    complete description: anything it doesn't list is off, the IT load runs at
    100 % of plan, and the data center is cooled free when possible, mechanically
    when needed (owner)."""

    it_load_pct: SliderSpec = SliderSpec(0, 100, 100, 1, "%")  # % of the planned load
    # Brine separation "accepts X % of the data center's heat" (number input)
    brine_heat_pct: SliderSpec = SliderSpec(0, 100, 100, 1, "%")
    # Power generation "runs at X % of design" (heat in and power out both capped)
    power_gen_run_pct: SliderSpec = SliderSpec(0, 100, 100, 1, "%")


@dataclass(frozen=True)
class SolverSettings:
    """Hourly module solver (docs/solver.md, D-052, D-054). Each hour the coupled
    modules iterate until no exchanged flow changes; if not settled after
    `stick_after` iterations, each sticky flow is capped at its value closest to
    zero over the last `stick_window` iterations and gets `max_iter − stick_after`
    more. Each iteration moves information one link along a chain, and the
    states now build chains (D-054) up to ~6 links long, so sticking waits for
    6 iterations (was 3) — sticking earlier capped flows that were still
    converging, which is what made them oscillate."""

    stick_after: int = 6
    stick_window: int = 3  # owner: the lowest of the last 3 iterations
    max_iter: int = 12
    # A flow has settled when |new − old| ≤ abs_tol + rel_tol·|old| (kW / kg/s).
    # Coupled tanks (brine return ↔ condenser ↔ ice) converge geometrically, so
    # 1e-9 took ~11 iterations for no practical gain (D-054).
    abs_tol: float = 1e-6
    rel_tol: float = 1e-6


@dataclass(frozen=True)
class RateCategoryDefault:
    name: str
    energy_usd_kwh: float
    demand_usd_kw: float


@dataclass(frozen=True)
class UtilityDefaults:
    """Time-of-use tariff defaults (docs/models/utility.md, D-043). The schedule
    starts all off-peak; the user paints peak/shoulder periods."""

    categories: tuple[RateCategoryDefault, ...] = (
        RateCategoryDefault("Off peak", 0.10, 10.0),
        RateCategoryDefault("Shoulder", 0.15, 10.0),
        RateCategoryDefault("Peak", 0.20, 10.0),
    )
    new_category: RateCategoryDefault = RateCategoryDefault("New rate", 0.12, 10.0)
    # Ranking for colours / "cheapest": energy $/kWh × 100 + demand $/kW.
    energy_weight: float = 100.0
    max_energy_usd_kwh: float = 10.0
    max_demand_usd_kw: float = 1_000.0


@dataclass(frozen=True)
class SizingConstants:
    """Facility area transfer functions (docs/models/sizing.md)."""

    ws_density_slope: float = 0.008  # (kW/sqft) per (kW/rack)
    ws_density_intercept: float = 0.1216  # kW/sqft
    redundancy_adder_per_y: float = 0.10  # fraction per +1 in Y
    chiller_area_dry_sqft_per_kw: float = 0.4
    chiller_area_evap_sqft_per_kw: float = 0.2

    def chiller_area_sqft_per_kw(self, cooling: CoolingType) -> float:
        if cooling is CoolingType.DRY:
            return self.chiller_area_dry_sqft_per_kw
        return self.chiller_area_evap_sqft_per_kw


@dataclass(frozen=True)
class ModelAssumptions:
    """Hourly model constants (docs/models/datacenter-hourly.md)."""

    it_parasitic_frac: float = 0.10
    t_approach_c: float = 10.0  # free cooling if t_amb + approach < t_supply
    t_pinch_c: float = 5.0  # evaporator = t_supply - pinch
    carnot_fraction: float = 0.40
    t_cond_approach_dry_c: float = 10.0  # condenser = t_amb + approach
    t_cond_approach_evap_c: float = 5.0
    cop_min: float = 0.0
    cop_max: float = 10.0
    cop_free_dry: float = 50.0
    cop_free_evap: float = 100.0

    def t_cond_approach_c(self, cooling: CoolingType) -> float:
        if cooling is CoolingType.DRY:
            return self.t_cond_approach_dry_c
        return self.t_cond_approach_evap_c

    def cop_free(self, cooling: CoolingType) -> float:
        if cooling is CoolingType.DRY:
            return self.cop_free_dry
        return self.cop_free_evap


@dataclass(frozen=True)
class NsrdbSettings:
    """NSRDB TMY request + cache settings (docs/integrations/nsrdb-weather.md)."""

    base_url: str = (
        "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download.csv"
    )
    dataset_name: str = "tmy-2024"  # pinned so re-fetched weather is reproducible (D-015)
    interval_min: int = 60
    timeout_s: float = 120.0
    max_attempts: int = 3  # on HTTP 429 / 5xx / timeout
    retry_backoff_s: float = 2.0  # doubles each retry; API allows 1 CSV request/s
    coord_decimals: int = 2  # cache key rounding (~1 km; NSRDB grid is ~4 km)


@dataclass(frozen=True)
class PsychrometricSettings:
    """Wet-bulb derivation (core/weather/psychrometrics.py)."""

    wet_bulb_iterations: int = 40  # bisection; bracket 60 K → < 1e-10 K resolution
    wet_bulb_bracket_k: float = 60.0  # search twb in [tdb - bracket, tdb]


@dataclass(frozen=True)
class FootprintSettings:
    """Facility block placement limits (docs/workflow/01-setup-tabs.md §3.4)."""

    min_aspect: float = 0.1  # length / width
    max_aspect: float = 10.0
    edge_tolerance_m: float = 0.01  # touching the boundary edge counts as inside


@dataclass(frozen=True)
class PersistenceSettings:
    """Autosave history and saved versions (docs/data-model.md → Project file, D-040)."""

    history_min_interval_s: float = 300.0  # at most one automatic snapshot per 5 min
    history_keep: int = 50  # automatic snapshots kept per project (oldest pruned)
    stem_suffix_hex: int = 6  # random suffix making each new project's autosave unique
    sqlite_file: str = "dcs.sqlite"  # local database (no DATABASE_URL), in the data folder


@dataclass(frozen=True)
class SiteAreaSettings:
    """Module areas drawn on the map (core/geometry/areas.py, D-036)."""

    min_piece_m2: float = 1.0  # snapped pieces smaller than this are dropped (slivers)
    overlap_tolerance_m2: float = 0.01  # overlaps below this are rounding, not overlap
    block_gap_m: float = 5.0  # gap when a new block is placed beside the data center
    # "Snap edges to N/S/E/W": free edges rotate to the nearest multiple of this
    # bearing; an edge within `edge_contact_tol_m` of the boundary, a block or
    # another area is not free (D-042).
    compass_step_deg: float = 45.0
    edge_contact_tol_m: float = 0.5
    max_vertex_shift_factor: float = 3.0  # skip a corner that would move > 3× its edges


@dataclass(frozen=True)
class GeocodeSettings:
    """Address → lat/lon: US Census first (exact US street addresses), then Nominatim.

    Nominatim: 1 request/s, identifying user agent required (D-022).
    """

    census_url: str = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
    census_benchmark: str = "Public_AR_Current"
    user_agent: str = "data-center-system (Rebound Technologies)"
    timeout_s: float = 10.0


# Physical / unit constants
KELVIN_OFFSET = 273.15
SQFT_TO_M2 = 0.09290304
KW_PER_MW = 1000.0
KG_PER_TONNE = 1000.0
GAL_PER_KG_WATER = 0.264172  # US gal per kg of liquid water (1 kg ≈ 1 L)
HOURS_PER_YEAR = 8760
HOURS_PER_DAY = 24
PA_PER_MBAR = 100.0
STANDARD_PRESSURE_PA = 101325.0

M_PER_FT = 0.3048
SECONDS_PER_HOUR = 3600.0
WATER_CP_KJ_KGK = 4.18  # water near 45 °C
ICE_LATENT_HEAT_KJ_KG = 330.0  # heat of fusion of pure ice at 0 °C (owner's value)
ICE_PROPS = IceProperties()
WATER_RHO_KG_M3 = 992.0  # water at 40 °C (tank sizing)
KW_PER_TR = 3.516853  # 1 ton of refrigeration = 12,000 BTU/h
KBTU_PER_KWH = 3.412142  # 1 kWh = 3,412.142 Btu
W_M2K_PER_BTU_HFT2F = 5.678263  # U: 1 Btu/h·ft²·°F = 5.678 W/m²K
TYPE_VALUE_DECIMALS = 6  # DataCenterType floats rounded so equal designs compare equal
SQFT_PER_ACRE = 43560.0

NSRDB = NsrdbSettings()
PSYCHRO = PsychrometricSettings()
FOOTPRINT = FootprintSettings()
SITE_AREAS = SiteAreaSettings()
PERSISTENCE = PersistenceSettings()
GEOCODE = GeocodeSettings()

DC_TYPE_INPUTS = DataCenterTypeInputs()
DC_INPUTS = DataCenterInputs()
PV_INPUTS = SolarPVInputs()
ICE_INPUTS = IceStorageInputs()
POWER_GEN_INPUTS = PowerGenerationInputs()
HWS_INPUTS = HotWaterStorageInputs()
BRINE_INPUTS = BrineSeparationInputs()
ICE_MIXER_INPUTS = IceMixerInputs()
GREENHOUSE_INPUTS = GreenhouseInputs()
SOLVER = SolverSettings()
CONTROL = ControlDefaults()
UTILITY = UtilityDefaults()
MONTHS_PER_YEAR = 12
SIZING = SizingConstants()
ASSUMPTIONS = ModelAssumptions()
