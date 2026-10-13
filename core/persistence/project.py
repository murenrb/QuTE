"""Project file: everything needed to restore a session (docs/data-model.md → Project file).

Weather and results are not stored; they are re-fetched / re-run on load.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.config.defaults import KW_PER_MW, POWER_GEN_INPUTS, ModelAssumptions
from core.domain.control import ControlSettings
from core.domain.datacenter import DataCenter
from core.domain.modules import ModuleSettings
from core.domain.site import Site
from core.domain.utility import UtilityTariff

PROJECT_SCHEMA_VERSION = 6


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Solar PV became area-sized (D-036): drop the old on/off flag and kW size;
    the area starts empty, so PV is off until an area is drawn."""
    pv = dict(data.get("modules", {}).get("solar_pv", {}))
    for old in ("enabled", "system_capacity_kw"):
        pv.pop(old, None)
    if "modules" in data:
        data = {**data, "modules": {**data["modules"], "solar_pv": pv}}
    return data


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """Ice storage defaults changed (D-042): the old default size (1,000 TR) now
    follows the IT load (65 TR/MW), and tank time must be 6–72 h (old default 1 h
    → new default 24 h)."""
    ice = dict(data.get("modules", {}).get("ice_storage", {}))
    if not ice:
        return data
    if ice.get("ice_maker_size_tr") == 1000:
        ice.pop("ice_maker_size_tr")
    if float(ice.get("tank_charge_time_h", 24)) < 6:
        ice["tank_charge_time_h"] = 24.0
    return {**data, "modules": {**data["modules"], "ice_storage": ice}}


# from_version → function upgrading the raw dict to from_version + 1.
def _v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Modules are added to the site explicitly (D-056): drawn-area modules got
    an `enabled` flag, on wherever an area was already drawn."""
    modules = dict(data.get("modules", {}))
    pv = dict(modules.get("solar_pv", {}))
    if not modules or "enabled" in pv:
        return data
    pv["enabled"] = bool(pv.get("area"))
    return {**data, "modules": {**modules, "solar_pv": pv}}


def _v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    """The greenhouse's U-value is an input (D-062): the wind speed input of
    its first version (convection films) is gone; U starts at its default."""
    modules = dict(data.get("modules", {}))
    gh = dict(modules.get("greenhouse", {}))
    if "wind_m_s" not in gh:
        return data
    gh.pop("wind_m_s")
    return {**data, "modules": {**modules, "greenhouse": gh}}


def _v5_to_v6(data: dict[str, Any]) -> dict[str, Any]:
    """Power generation's rating is a % of the IT load (D-063): a saved kWe
    rating becomes that % of the first facility's IT peak (no rating saved =
    it followed the IT load at the default %)."""
    modules = dict(data.get("modules", {}))
    pg = dict(modules.get("power_generation", {}))
    if "rated_kw" not in pg:
        return data
    rated_kw = pg.pop("rated_kw")
    facilities = data.get("facilities") or [{}]
    it_mw = facilities[0].get("it_load_peak_mw")
    if rated_kw is not None and it_mw:
        spec = POWER_GEN_INPUTS.rated_pct_of_it
        pct = round(rated_kw / (it_mw * KW_PER_MW) * 100, 6)  # no float noise on the slider
        pg["rated_pct_of_it"] = min(max(pct, spec.min), spec.max)
    return {**data, "modules": {**modules, "power_generation": pg}}


MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
}


class ProjectFileError(ValueError):
    """Project file can't be read. `str(e)` is user-facing."""


class Project(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = PROJECT_SCHEMA_VERSION
    site: Site = Site()
    facilities: tuple[DataCenter, ...] = ()
    modules: ModuleSettings = ModuleSettings()  # additive: older files load with defaults
    utility: UtilityTariff = Field(default_factory=UtilityTariff)  # additive (D-043)
    control: ControlSettings = ControlSettings()  # state machine; additive (D-053)
    assumptions: ModelAssumptions = Field(default_factory=ModelAssumptions)
    step: str = "location"  # workspace tab to reopen on (D-025)

    @property
    def name(self) -> str:
        return self.site.name


def to_json(p: Project) -> str:
    return p.model_dump_json(indent=2) + "\n"


def from_json(text: str | bytes) -> Project:
    """Parse, migrate old schema versions, validate."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProjectFileError(f"Not a valid project file (bad JSON: {e})") from e
    if not isinstance(data, dict):
        raise ProjectFileError("Not a valid project file (expected a JSON object)")
    data = migrate(data)
    try:
        return Project.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise ProjectFileError(f"Project file is invalid at {where!r}: {first['msg']}") from e


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema_version", 1)
    if not isinstance(version, int) or version < 1:
        raise ProjectFileError(f"Unknown project schema_version {version!r}")
    if version > PROJECT_SCHEMA_VERSION:
        raise ProjectFileError(
            f"Project was saved by a newer version of this app (schema {version}; "
            f"this app reads up to {PROJECT_SCHEMA_VERSION})"
        )
    while version < PROJECT_SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data


def inputs_hash(p: Project) -> str:
    """Fingerprint of everything that changes model results.

    Excludes the workspace tab, site name/address, weather_ref and the map view, so
    results only re-run when an engineering input changed.
    """
    data = p.model_dump(mode="json", exclude={"step"})
    for k in ("name", "address", "weather_ref", "map_view", "map_center", "map_zoom"):
        data["site"].pop(k, None)
    blob = json.dumps(data, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()
