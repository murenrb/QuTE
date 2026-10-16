"""Co-located module settings stored in the project (docs/data-model.md → Project file).

Every module falls in one of two map categories (D-041):

- **Scaled in map** (`SitedModuleParams`, e.g. Solar PV): its `area` is drawn on
  the map and its vertices can be dragged; it snaps to the free land inside the
  property (D-036). Active when the area is non-empty.
- **Scaled in inputs** (`BlockModuleParams`, e.g. Ice storage): a rectangular
  block whose area comes from its inputs; dragged, resized (area fixed) and
  rotated like the data center block. It cuts back any drawn area it covers.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config.defaults import (
    ASSUMPTIONS,
    BRINE_INPUTS,
    BRINES,
    DC_INPUTS,
    DC_TYPE_INPUTS,
    GREENHOUSE_INPUTS,
    HWS_INPUTS,
    ICE_INPUTS,
    ICE_MIXER_INPUTS,
    KW_PER_MW,
    KW_PER_TR,
    M_PER_FT,
    POWER_GEN_INPUTS,
    PV_INPUTS,
    SECONDS_PER_HOUR,
    SQFT_TO_M2,
    WATER_CP_KJ_KGK,
    WATER_RHO_KG_M3,
    BrineProperties,
    BrineType,
    HwsConnection,
    HwsTankType,
    IceMixerFluid,
    PvArrayType,
    PvModuleType,
    SliderSpec,
)
from core.domain.brine import rho_brine
from core.domain.site import Area, Footprint


def _field(spec: SliderSpec, description: str) -> Any:
    return Field(default=spec.default, ge=spec.min, le=spec.max, description=description)


class MapScaling(StrEnum):
    MAP = "map"  # scaled in map: drawn area
    INPUTS = "inputs"  # scaled in inputs: block sized by inputs


class SitedModuleParams(BaseModel):
    """Base for *scaled-in-map* modules: placed on the site as a drawn area."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False  # added to the site (Modules tab, D-056); the area is kept if removed
    area: Area = ()

    @property
    def placed(self) -> bool:
        return self.enabled and bool(self.area)


@dataclass(frozen=True)
class ModuleContext:
    """Site facts some module defaults follow (e.g. ice size from IT load)."""

    it_peak_mw: float | None = None
    site_lat: float | None = None
    t_supply_c: float | None = None  # data center cold water
    t_return_c: float | None = None  # data center warm water
    it_parasitic_frac: float | None = None  # heat on top of IT (ModelAssumptions)


class BlockModuleParams(BaseModel):
    """Base for *scaled-in-inputs* modules: a block like the data center's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    footprint: Footprint | None = None  # placed automatically when enabled

    @property
    def block_area_m2(self) -> float:
        """Footprint area set by the inputs (call on resolved params)."""
        raise NotImplementedError

    def resolved(self, ctx: ModuleContext) -> "BlockModuleParams":
        """Params with any site-following defaults filled in."""
        return self

    def default_dims_m(self) -> tuple[float, float] | None:
        """Default block (width E–W, length N–S) in m; None = a square of
        block_area_m2. Call on resolved params."""
        return None

    @property
    def placed(self) -> bool:
        return self.enabled and self.footprint is not None


def map_scaling(params: BaseModel) -> MapScaling | None:
    if isinstance(params, SitedModuleParams):
        return MapScaling.MAP
    if isinstance(params, BlockModuleParams):
        return MapScaling.INPUTS
    return None


_PV = PV_INPUTS


class SolarPVParams(SitedModuleParams):
    """PVWatts V8 inputs; DC size = area × power density (docs/models/solar-pv.md)."""

    power_density_w_sqft: float = _field(_PV.power_density_w_sqft, "kW DC per land area, W/sqft")
    array_type: PvArrayType = _PV.array_type
    module_type: PvModuleType = _PV.module_type
    # None = follow the site latitude (|lat|), the usual fixed-tilt starting point.
    tilt_deg: float | None = Field(
        default=None, ge=_PV.tilt_deg.min, le=_PV.tilt_deg.max, description="None = site latitude"
    )
    # None = face the equator: 180° (south) in the northern hemisphere, 0° (north)
    # in the southern.
    azimuth_deg: float | None = Field(
        default=None,
        ge=_PV.azimuth_deg.min,
        le=_PV.azimuth_deg.max,
        description="None = equator-facing for the site's hemisphere",
    )
    losses_pct: float = _field(_PV.losses_pct, "DC system losses, %")
    dc_ac_ratio: float = _field(_PV.dc_ac_ratio, "DC nameplate / AC inverter rating")
    gcr: float = _field(_PV.gcr, "Ground coverage ratio (row spacing; trackers/backtracking)")
    inv_eff_pct: float = _field(_PV.inv_eff_pct, "Inverter efficiency at rated power, %")
    # Panels on the data center roof too: adds its block area (D-073).
    cover_data_center: bool = _PV.cover_data_center


_ICE = ICE_INPUTS


class IceStorageParams(BlockModuleParams):
    """Ice storage design inputs (docs/models/ice-storage.md). Scaled in inputs:
    its block's area = tank capacity / energy density (D-041)."""

    # None = follow the data center: tr_per_mw_it × IT peak MW (D-042).
    ice_maker_size_tr: float | None = Field(
        default=None,
        ge=_ICE.ice_maker_size_tr.min,
        le=_ICE.ice_maker_size_tr.max,
        description="Ice maker nameplate, TR (None = 65 TR per MW of IT load)",
    )
    tank_charge_time_h: float = _field(_ICE.tank_charge_time_h, "Tank size as hours of nameplate")
    soc_start_frac: float = _field(_ICE.soc_start_frac, "Ice tank state of charge at hour 0")
    water_soc_start_frac: float = _field(
        _ICE.water_soc_start_frac, "Water tank state of charge at hour 0"
    )
    energy_density_kwh_sqft: float = _field(
        _ICE.energy_density_kwh_sqft, "Stored kWh_th per sqft of footprint"
    )
    cop_max: float = Field(default=_ICE.cop_max, gt=0)
    capacity_factor_max: float = Field(default=_ICE.capacity_factor_max, gt=0)
    cop_coeff_a: float = _ICE.cop_coeff_a
    cop_coeff_b: float = _ICE.cop_coeff_b
    cop_coeff_c: float = _ICE.cop_coeff_c
    capacity_coeff_a: float = _ICE.capacity_coeff_a
    capacity_coeff_b: float = _ICE.capacity_coeff_b
    capacity_coeff_c: float = _ICE.capacity_coeff_c

    def resolved(self, ctx: ModuleContext) -> "IceStorageParams":
        if self.ice_maker_size_tr is not None:
            return self
        it_mw = ctx.it_peak_mw if ctx.it_peak_mw is not None else DC_INPUTS.it_load_peak_mw.default
        size = min(
            max(_ICE.tr_per_mw_it * it_mw, _ICE.ice_maker_size_tr.min), _ICE.ice_maker_size_tr.max
        )
        return self.model_copy(update={"ice_maker_size_tr": size})

    @property
    def ice_maker_kwth(self) -> float:
        if self.ice_maker_size_tr is None:
            raise ValueError("Resolve the ice maker size first (IceStorageParams.resolved)")
        return self.ice_maker_size_tr * KW_PER_TR

    @property
    def tank_capacity_kwh(self) -> float:
        return self.ice_maker_kwth * self.tank_charge_time_h

    @property
    def footprint_sqft(self) -> float:
        return self.tank_capacity_kwh / self.energy_density_kwh_sqft

    @property
    def block_area_m2(self) -> float:
        return self.footprint_sqft * SQFT_TO_M2


_PG = POWER_GEN_INPUTS


class PowerGenerationParams(BlockModuleParams):
    """Transcritical CO2 power cycle on data center waste heat
    (docs/models/power-generation.md, D-045). Scaled in inputs: its block's
    area = rated MWe × power density."""

    carnot_pct: float = _field(_PG.carnot_pct, "Cycle efficiency as % of Carnot")
    rated_pct_of_it: float = _field(
        _PG.rated_pct_of_it, "Generator rating at the max cold-side temp, % of the IT load peak"
    )
    # kWe, set by `resolved` from the IT load (derived, so not saved).
    rated_kw: float | None = Field(default=None, gt=0, exclude=True)
    t_cold_max_c: float = _field(
        _PG.t_cold_max_c, "Design (max) cold-side temperature; the generator is sized here"
    )
    power_density_sqft_mwe: float = _field(
        _PG.power_density_sqft_mwe, "Footprint per MWe of rated output"
    )

    def resolved(self, ctx: ModuleContext) -> "PowerGenerationParams":
        if self.rated_kw is not None:
            return self
        it_mw = ctx.it_peak_mw if ctx.it_peak_mw is not None else DC_INPUTS.it_load_peak_mw.default
        rated = self.rated_pct_of_it / 100 * it_mw * KW_PER_MW
        return self.model_copy(update={"rated_kw": rated})

    @property
    def rated_kwe(self) -> float:
        if self.rated_kw is None:
            raise ValueError("Resolve the rating first (PowerGenerationParams.resolved)")
        return self.rated_kw

    @property
    def footprint_sqft(self) -> float:
        return self.rated_kwe / KW_PER_MW * self.power_density_sqft_mwe

    @property
    def block_area_m2(self) -> float:
        return self.footprint_sqft * SQFT_TO_M2


_HWS = HWS_INPUTS


class HotWaterStorageParams(BlockModuleParams):
    """Hot water storage, two tank or thermocline (docs/models/hot-water-storage.md,
    D-046). Scaled in inputs: block from the tank diameter(s) + a buffer."""

    storage_hours: float = _field(_HWS.storage_hours, "Hours of IT heat the tank holds")
    connection: HwsConnection = _HWS.connection
    tank_type: HwsTankType = _HWS.tank_type
    tank_height_m: float = _field(_HWS.tank_height_m, "Tank height (diameter follows)")
    # Derived once per run from the data center (resolved); never saved.
    tank_volume_m3: float | None = Field(default=None, gt=0, exclude=True)

    def resolved(self, ctx: ModuleContext) -> "HotWaterStorageParams":
        """Tank volume = IT kW × (1 + parasitic frac) × hours × 3600
        / ((T_return − T_supply) × cp × rho): the data center's full heat load."""
        it_mw = ctx.it_peak_mw if ctx.it_peak_mw is not None else DC_INPUTS.it_load_peak_mw.default
        t_sup = ctx.t_supply_c if ctx.t_supply_c is not None else DC_TYPE_INPUTS.t_supply_c.default
        t_ret = ctx.t_return_c if ctx.t_return_c is not None else DC_TYPE_INPUTS.t_return_c.default
        para = (
            ctx.it_parasitic_frac
            if ctx.it_parasitic_frac is not None
            else ASSUMPTIONS.it_parasitic_frac
        )
        heat_kw = it_mw * KW_PER_MW * (1 + para)
        heat_kj = heat_kw * self.storage_hours * SECONDS_PER_HOUR
        volume = heat_kj / ((t_ret - t_sup) * WATER_CP_KJ_KGK * WATER_RHO_KG_M3)
        return self.model_copy(update={"tank_volume_m3": volume})

    @property
    def volume_m3(self) -> float:
        if self.tank_volume_m3 is None:
            raise ValueError("Resolve the tank volume first (HotWaterStorageParams.resolved)")
        return self.tank_volume_m3

    @property
    def mass_kg(self) -> float:
        """Water inventory: the cold tank full at the start."""
        return self.volume_m3 * WATER_RHO_KG_M3

    @property
    def t_pinch_c(self) -> float:
        if self.connection is HwsConnection.DIRECT:
            return _HWS.pinch_direct_c
        return _HWS.pinch_indirect_c

    @property
    def n_tanks(self) -> int:
        return 2 if self.tank_type is HwsTankType.TWO_TANK else 1

    @property
    def tank_diameter_m(self) -> float:
        """Each tank holds the full volume (two tank: one cold, one hot)."""
        return math.sqrt(4 * self.volume_m3 / (math.pi * self.tank_height_m))

    def default_dims_m(self) -> tuple[float, float]:
        """Square (thermocline) or 2:1 side by side (two tank), + buffer each side."""
        d, b = self.tank_diameter_m, _HWS.buffer_ft * M_PER_FT
        return self.n_tanks * d + 2 * b, d + 2 * b

    @property
    def block_area_m2(self) -> float:
        w, length = self.default_dims_m()
        return w * length


_BR = BRINE_INPUTS


class BrineSeparationParams(BlockModuleParams):
    """Brine separation by single-stage evaporation (docs/models/brine-separation.md,
    D-048). Scaled in inputs: one tank of height 12 m; square block of the tank
    diameter + 20 ft each side."""

    brine_type: BrineType = _BR.brine_type
    conc_low_wt_pct: float = _field(_BR.conc_wt_pct, "Starting (dilute) concentration, wt%")
    conc_high_wt_pct: float = Field(
        default=_BR.conc_high_default_wt_pct,
        ge=_BR.conc_wt_pct.min,
        le=_BR.conc_wt_pct.max,
        description="Concentration at which it stops taking heat, wt%",
    )
    concentrate_hours: float = _field(
        _BR.concentrate_hours, "Hours of full data center heat to go from low to high"
    )
    # Derived once per run (resolved): brine at the low concentration; never saved.
    brine_mass_kg: float | None = Field(default=None, gt=0, exclude=True)

    @model_validator(mode="after")
    def _range(self) -> "BrineSeparationParams":
        if self.conc_low_wt_pct <= 0:
            raise ValueError("The low concentration must be above 0 wt% (there must be salt)")
        if self.conc_high_wt_pct <= self.conc_low_wt_pct:
            raise ValueError("The high concentration must be above the low concentration")
        return self

    def resolved(self, ctx: ModuleContext) -> "BrineSeparationParams":
        """Salt balance: water removed W = heat × hours × 3600 / h_vap;
        m_brine_dis = W × c_high / (c_high − c_low)."""
        it_mw = ctx.it_peak_mw if ctx.it_peak_mw is not None else DC_INPUTS.it_load_peak_mw.default
        para = (
            ctx.it_parasitic_frac
            if ctx.it_parasitic_frac is not None
            else ASSUMPTIONS.it_parasitic_frac
        )
        heat_kw = it_mw * KW_PER_MW * (1 + para)
        water_kg = heat_kw * self.concentrate_hours * SECONDS_PER_HOUR / _BR.h_vap_kj_kg
        c_lo, c_hi = self.c_low, self.c_high
        return self.model_copy(update={"brine_mass_kg": water_kg * c_hi / (c_hi - c_lo)})

    @property
    def props(self) -> BrineProperties:
        return BRINES[self.brine_type]

    @property
    def c_low(self) -> float:
        return self.conc_low_wt_pct / 100

    @property
    def c_high(self) -> float:
        return self.conc_high_wt_pct / 100

    @property
    def mass_kg(self) -> float:
        if self.brine_mass_kg is None:
            raise ValueError("Resolve the brine mass first (BrineSeparationParams.resolved)")
        return self.brine_mass_kg

    @property
    def tank_volume_m3(self) -> float:
        """The dilute (starting) state is the largest volume."""
        return self.mass_kg / rho_brine(self.c_low, self.props)

    @property
    def tank_diameter_m(self) -> float:
        return math.sqrt(4 * self.tank_volume_m3 / (math.pi * _BR.tank_height_m))

    def default_dims_m(self) -> tuple[float, float]:
        side = self.tank_diameter_m + 2 * _BR.buffer_ft * M_PER_FT
        return side, side

    @property
    def block_area_m2(self) -> float:
        w, length = self.default_dims_m()
        return w * length


_MIX = ICE_MIXER_INPUTS


class IceMixerParams(BaseModel):
    """Ice mixer (docs/models/ice-mixer.md, D-050): melts ice into water or brine
    to supply cooling. No footprint — it is neither scaled in map nor in inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    fluid: IceMixerFluid = _MIX.fluid
    recup_eta_pct: float = _field(_MIX.recup_eta_pct, "Recuperation efficiency, %")
    mix_eta_pct: float = _field(_MIX.mix_eta_pct, "Mixing efficiency, %")

    @property
    def recup_eta(self) -> float:
        return self.recup_eta_pct / 100

    @property
    def mix_eta(self) -> float:
        return self.mix_eta_pct / 100


_GH = GREENHOUSE_INPUTS


class GreenhouseParams(SitedModuleParams):
    """Greenhouse (docs/models/greenhouse.md, D-061). Scaled in map: the drawn
    area is its floor area."""

    transmissivity_pct: float = _field(_GH.transmissivity_pct, "Glass solar transmissivity, %")
    u_w_m2k: float = _field(_GH.u_w_m2k, "Covering U-value, W/m²K")
    t_set_c: float = _field(_GH.t_set_c, "Inside air temperature setpoint, °C")

    @property
    def transmissivity(self) -> float:
        return self.transmissivity_pct / 100


class ModuleSettings(BaseModel):
    """One field per module, keyed by the module's id (e.g. "solar_pv")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    solar_pv: SolarPVParams = SolarPVParams()
    ice_storage: IceStorageParams = IceStorageParams()
    power_generation: PowerGenerationParams = PowerGenerationParams()
    hot_water_storage: HotWaterStorageParams = HotWaterStorageParams()
    brine_separation: BrineSeparationParams = BrineSeparationParams()
    ice_mixer: IceMixerParams = IceMixerParams()
    greenhouse: GreenhouseParams = GreenhouseParams()

    def sited(self) -> dict[str, SitedModuleParams]:
        """Scaled-in-map modules (drawn areas), by key — new ones appear here."""
        return {
            k: v
            for k in type(self).model_fields
            if isinstance(v := getattr(self, k), SitedModuleParams)
        }

    def blocks(self) -> dict[str, BlockModuleParams]:
        """Scaled-in-inputs modules (blocks), by key — new ones appear here."""
        return {
            k: v
            for k in type(self).model_fields
            if isinstance(v := getattr(self, k), BlockModuleParams)
        }

    def enabled_keys(self) -> tuple[str, ...]:
        """Modules added to the site, in field order (D-056)."""
        return tuple(k for k in type(self).model_fields if getattr(self, k).enabled)

    def with_enabled(self, key: str, enabled: bool) -> "ModuleSettings":
        """Add to / remove from the site; the module's inputs (and area or
        block) are kept, so adding it back restores them."""
        params = getattr(self, key)
        return self.model_copy(update={key: params.model_copy(update={"enabled": enabled})})

    def with_area(self, key: str, area: Area) -> "ModuleSettings":
        params = self.sited()[key]
        return self.model_copy(update={key: params.model_copy(update={"area": area})})

    def with_footprint(self, key: str, fp: Footprint | None) -> "ModuleSettings":
        params = self.blocks()[key]
        return self.model_copy(update={key: params.model_copy(update={"footprint": fp})})
