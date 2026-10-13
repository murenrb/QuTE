"""Time-of-use tariff painter: a small custom component (D-043).

Rate rows (colour swatch, name, energy $/kWh, demand $/kW, delete) and a
12 × 24 month × hour table. Click a swatch to pick it, then click or drag over
cells — or click a month/hour header for a whole row/column — to paint. The
front end (plain JS, no build) sends one event per action; Python applies it
to the `UtilityTariff` (the source of truth) and re-renders.
"""

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

from core.domain.utility import UtilityTariff

FRONTEND = Path(__file__).parent / "frontend"
_component = components.declare_component("tariff_editor", path=str(FRONTEND))

# Viridis (dark purple → bright yellow), 9 evenly spaced stops.
VIRIDIS = (
    "#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c",
    "#28ae80", "#5ec962", "#addc30", "#fde725",
)  # fmt: skip


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def viridis(t: float) -> str:
    """Colour at position t ∈ [0, 1] on the viridis scale (linear between stops)."""
    t = min(max(t, 0.0), 1.0) * (len(VIRIDIS) - 1)
    i = min(int(t), len(VIRIDIS) - 2)
    f = t - i
    a, b = _hex_to_rgb(VIRIDIS[i]), _hex_to_rgb(VIRIDIS[i + 1])
    r, g, bl = (round(a[k] + (b[k] - a[k]) * f) for k in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


def category_colors(tariff: UtilityTariff) -> dict[str, str]:
    """Each category's swatch: its total value (energy × 100 + demand) placed
    linearly between the cheapest (dark purple) and the dearest (bright yellow)."""
    values = {c.id: c.total_value for c in tariff.categories}
    lo, hi = min(values.values()), max(values.values())
    span = hi - lo
    return {cid: viridis((v - lo) / span if span > 0 else 0.0) for cid, v in values.items()}


def tariff_editor(tariff: UtilityTariff, *, key: str) -> dict[str, Any] | None:
    colors = category_colors(tariff)
    value: dict[str, Any] | None = _component(
        categories=[
            {
                "id": c.id,
                "name": c.name,
                "energy": c.energy_usd_kwh,
                "demand": c.demand_usd_kw,
                "color": colors[c.id],
            }
            for c in tariff.categories
        ],
        schedule=[list(row) for row in tariff.schedule],
        cheapest=tariff.cheapest.id,
        key=key,
        default=None,
    )
    return value
