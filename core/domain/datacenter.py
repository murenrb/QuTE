"""A specific data center: type + IT load + placed footprint (docs/data-model.md → DataCenter)."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config.defaults import HOURS_PER_DAY, KW_PER_MW
from core.domain.datacenter_type import DataCenterType
from core.domain.site import Footprint


class DataCenter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dc_type: DataCenterType
    it_load_peak_mw: float = Field(gt=0)
    # 24 hourly values in kW; None = constant at peak (Step 1 default).
    it_profile_daily_kw: tuple[float, ...] | None = None
    footprint: Footprint | None = None  # None until placed on the map

    @model_validator(mode="after")
    def _profile_valid(self) -> Self:
        p = self.it_profile_daily_kw
        if p is None:
            return self
        if len(p) != HOURS_PER_DAY:
            raise ValueError(f"Daily IT profile needs {HOURS_PER_DAY} values, got {len(p)}")
        if min(p) < 0 or max(p) > self.it_load_peak_kw * (1 + 1e-9):
            raise ValueError("Daily IT profile values must be between 0 and peak IT load")
        return self

    @property
    def it_load_peak_kw(self) -> float:
        return self.it_load_peak_mw * KW_PER_MW

    @property
    def daily_profile_kw(self) -> tuple[float, ...]:
        """Hourly IT load for one day; constant at peak unless a profile is set."""
        if self.it_profile_daily_kw is None:
            return (self.it_load_peak_kw,) * HOURS_PER_DAY
        return self.it_profile_daily_kw
