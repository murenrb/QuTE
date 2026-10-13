"""Utility time-of-use tariff stored in the project (docs/models/utility.md, D-043).

Rate categories (name, energy $/kWh, demand $/kW) are painted onto a 12 × 24
month-of-year × hour-of-day schedule. Weekends either follow the schedule or
use the cheapest category.
"""

import secrets
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.config.defaults import HOURS_PER_DAY, MONTHS_PER_YEAR, UTILITY, RateCategoryDefault


class WeekendPricing(StrEnum):
    FOLLOW_SCHEDULE = "follow_schedule"
    OFF_PEAK = "off_peak"  # the cheapest category, all weekend hours


class RateCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    energy_usd_kwh: float = Field(ge=0, le=UTILITY.max_energy_usd_kwh)
    demand_usd_kw: float = Field(ge=0, le=UTILITY.max_demand_usd_kw)

    @property
    def total_value(self) -> float:
        """Ranking used for colours and 'cheapest': energy × 100 + demand."""
        return self.energy_usd_kwh * UTILITY.energy_weight + self.demand_usd_kw


def new_category_id() -> str:
    return secrets.token_hex(4)


def _category(d: RateCategoryDefault, cid: str | None = None) -> RateCategory:
    return RateCategory(
        id=cid or new_category_id(),
        name=d.name,
        energy_usd_kwh=d.energy_usd_kwh,
        demand_usd_kw=d.demand_usd_kw,
    )


def _default_categories() -> tuple[RateCategory, ...]:
    ids = ("offpeak", "shoulder", "peak")  # stable ids for the defaults
    return tuple(_category(d, i) for d, i in zip(UTILITY.categories, ids, strict=True))


Schedule = tuple[tuple[str, ...], ...]  # [month 0..11][hour 0..23] → category id


def _default_schedule() -> Schedule:
    return tuple(("offpeak",) * HOURS_PER_DAY for _ in range(MONTHS_PER_YEAR))


class UtilityTariff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    categories: tuple[RateCategory, ...] = Field(default_factory=_default_categories, min_length=1)
    schedule: Schedule = Field(default_factory=_default_schedule)
    weekend: WeekendPricing = WeekendPricing.FOLLOW_SCHEDULE

    @model_validator(mode="after")
    def _valid(self) -> Self:
        ids = [c.id for c in self.categories]
        if len(set(ids)) != len(ids):
            raise ValueError("Rate category ids must be unique")
        if len(self.schedule) != MONTHS_PER_YEAR or any(
            len(row) != HOURS_PER_DAY for row in self.schedule
        ):
            raise ValueError(f"Schedule must be {MONTHS_PER_YEAR} × {HOURS_PER_DAY}")
        unknown = {c for row in self.schedule for c in row} - set(ids)
        if unknown:
            raise ValueError(f"Schedule uses unknown rate categories: {sorted(unknown)}")
        return self

    def category(self, cid: str) -> RateCategory:
        return next(c for c in self.categories if c.id == cid)

    @property
    def cheapest(self) -> RateCategory:
        return min(self.categories, key=lambda c: c.total_value)

    def painted(self, cells: list[tuple[int, int]], cid: str) -> "UtilityTariff":
        """Assign category `cid` to (month index, hour) cells."""
        self.category(cid)  # raises StopIteration if unknown
        rows = [list(r) for r in self.schedule]
        for m, h in cells:
            rows[m][h] = cid
        return self.model_copy(update={"schedule": tuple(tuple(r) for r in rows)})

    def without_category(self, cid: str) -> "UtilityTariff":
        """Remove a category; its cells go to the cheapest remaining one."""
        rest = tuple(c for c in self.categories if c.id != cid)
        if not rest:
            raise ValueError("Keep at least one rate category")
        fallback = min(rest, key=lambda c: c.total_value).id
        schedule = tuple(tuple(fallback if x == cid else x for x in row) for row in self.schedule)
        return UtilityTariff(categories=rest, schedule=schedule, weekend=self.weekend)
