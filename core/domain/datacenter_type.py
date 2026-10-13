"""Reusable data center design template (docs/data-model.md → DataCenterType).

The name is not an input: it is synthesized from the design parameters
(`type_name`), so two types with the same parameters are the same type (D-023).
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from core.config.defaults import DC_TYPE_INPUTS, TYPE_VALUE_DECIMALS, CoolingType, SliderSpec

# v2: `name` became derived (v1 files carried a user-entered name; it is ignored).
SCHEMA_VERSION = 2

COOLING_SHORT = {CoolingType.DRY: "Dry", CoolingType.EVAPORATIVE: "Evap"}


def _field(spec: SliderSpec, description: str) -> Any:
    return Field(default=spec.default, ge=spec.min, le=spec.max, description=description)


_I = DC_TYPE_INPUTS
_FLOAT_FIELDS = (
    "t_supply_min_c",
    "t_supply_c",
    "t_return_c",
    "rack_density_kw",
    "white_space_ratio",
    "ups_area_sqft_per_kw",
    "generator_area_sqft_per_kw",
    "switchgear_area_sqft_per_kw",
)


class DataCenterType(BaseModel):
    """Design parameters shared by every data center of this type.

    Supply = cold water to IT; return = warm water back (see CLAUDE.md rule 8).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = SCHEMA_VERSION
    cooling_type: CoolingType = _I.cooling_type
    t_supply_c: float = _field(_I.t_supply_c, "Cold water supply to IT (setpoint), °C")
    # Free cooling: supply floats at ambient + approach, clamped to [min, setpoint]
    # (D-047). Chillers hold the setpoint.
    t_supply_min_c: float = _field(_I.t_supply_min_c, "Lowest supply in free cooling, °C")
    t_return_c: float = _field(_I.t_return_c, "Warm water return from IT, °C")
    rack_density_kw: float = _field(_I.rack_density_kw, "kW per rack")
    white_space_ratio: float = _field(_I.white_space_ratio, "White space / data hall, 0.10-1")
    redundancy_x: int = _field(_I.redundancy_x, "X in X*N+Y")
    redundancy_y: int = _field(_I.redundancy_y, "Y in X*N+Y")
    ups_area_sqft_per_kw: float = _field(_I.ups_area_sqft_per_kw, "sqft per kW IT")
    generator_area_sqft_per_kw: float = _field(_I.generator_area_sqft_per_kw, "sqft per kW IT")
    switchgear_area_sqft_per_kw: float = _field(_I.switchgear_area_sqft_per_kw, "sqft per kW IT")

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data: Any) -> Any:
        """Accept saved JSON: drop the derived (v2) or user-entered (v1) name."""
        if isinstance(data, dict) and "name" in data:
            data = {k: v for k, v in data.items() if k != "name"}
            data["schema_version"] = SCHEMA_VERSION
        return data

    @field_validator(*_FLOAT_FIELDS)
    @classmethod
    def _round(cls, v: float) -> float:
        """Strip float noise (e.g. slider 1.5000000000000002) so equal designs compare equal."""
        return round(v, TYPE_VALUE_DECIMALS)

    @model_validator(mode="after")
    def _return_warmer_than_supply(self) -> Self:
        if self.t_return_c <= self.t_supply_c:
            raise ValueError(
                f"Return temp ({self.t_return_c} °C) must be warmer than "
                f"supply temp ({self.t_supply_c} °C)"
            )
        if self.t_supply_min_c > self.t_supply_c:
            raise ValueError(
                f"Minimum supply temp ({self.t_supply_min_c} °C) must not exceed the "
                f"supply setpoint ({self.t_supply_c} °C)"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name(self) -> str:
        return type_name(self)

    @property
    def backup_area_sqft_per_kw(self) -> float:
        return (
            self.ups_area_sqft_per_kw
            + self.generator_area_sqft_per_kw
            + self.switchgear_area_sqft_per_kw
        )

    def same_design(self, other: "DataCenterType") -> bool:
        return self.model_dump(exclude={"schema_version"}) == other.model_dump(
            exclude={"schema_version"}
        )


def redundancy_label(x: int, y: int) -> str:
    """X·N + Y as engineers write it: N+1, 2N, 2N+1."""
    n = "N" if x == 1 else f"{x}N"
    return f"{n}+{y}" if y else n


def type_name(t: DataCenterType) -> str:
    """Every input in one concise label, e.g.
    'Dry · 5–40→50 °C · 50 kW/rack · 65% WS · N+1 · UPS/Gen/SWG 1/1.5/0.5 sqft/kW'.
    """
    return " · ".join(
        [
            COOLING_SHORT[t.cooling_type],
            f"{t.t_supply_min_c:g}–{t.t_supply_c:g}→{t.t_return_c:g} °C",
            f"{t.rack_density_kw:g} kW/rack",
            f"{t.white_space_ratio * 100:g}% WS",
            redundancy_label(t.redundancy_x, t.redundancy_y),
            f"UPS/Gen/SWG {t.ups_area_sqft_per_kw:g}/{t.generator_area_sqft_per_kw:g}/"
            f"{t.switchgear_area_sqft_per_kw:g} sqft/kW",
        ]
    )


def type_file_stem(t: DataCenterType) -> str:
    """Unique, file-safe stem, e.g. 'dry_5-40-50c_50kw_ws65_1n1_1-1p5-0p5'."""

    def n(v: float) -> str:
        return f"{v:g}".replace(".", "p").replace("-", "m")

    return "_".join(
        [
            t.cooling_type.value,
            f"{n(t.t_supply_min_c)}-{n(t.t_supply_c)}-{n(t.t_return_c)}c",
            f"{n(t.rack_density_kw)}kw",
            f"ws{n(round(t.white_space_ratio * 100, TYPE_VALUE_DECIMALS))}",
            f"{t.redundancy_x}n{t.redundancy_y}",
            f"{n(t.ups_area_sqft_per_kw)}-{n(t.generator_area_sqft_per_kw)}-"
            f"{n(t.switchgear_area_sqft_per_kw)}",
        ]
    )
