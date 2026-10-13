"""Property boundary measurements (docs/workflow/01-setup-tabs.md §2)."""

import math
from dataclasses import dataclass

from shapely.geometry import Polygon

from core.domain.site import LatLon
from core.geometry.local_frame import XY, LocalFrame


class BoundaryError(ValueError):
    """Boundary is not a valid simple polygon."""


@dataclass(frozen=True)
class BoundaryMetrics:
    area_m2: float
    perimeter_m: float
    # Per vertex, same order as the input ring.
    interior_angles_deg: tuple[float, ...]
    # Segment i runs from vertex i to vertex i+1 (last one closes the ring).
    segment_lengths_m: tuple[float, ...]
    segment_midpoints: tuple[LatLon, ...]
    centroid: LatLon


def clean_ring(points: list[LatLon]) -> tuple[LatLon, ...]:
    """Drop a repeated closing vertex and consecutive duplicates."""
    ring: list[LatLon] = []
    for p in points:
        if not ring or p != ring[-1]:
            ring.append(p)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    return tuple(ring)


def interior_angles_deg(xy: list[XY]) -> list[float]:
    """Interior angle at each vertex, handling reflex (> 180°) corners.

    With the ring oriented counter-clockwise, the interior angle at C is the
    counter-clockwise turn from (next − C) to (prev − C).
    """
    ccw = _signed_area(xy) > 0
    n = len(xy)
    angles = []
    for i in range(n):
        cx, cy = xy[i]
        px, py = xy[i - 1]
        nx, ny = xy[(i + 1) % n]
        if not ccw:
            px, py, nx, ny = nx, ny, px, py
        v1x, v1y, v2x, v2y = px - cx, py - cy, nx - cx, ny - cy
        a = math.degrees(math.atan2(v2x * v1y - v2y * v1x, v2x * v1x + v2y * v1y))
        angles.append(a % 360.0)
    return angles


def _signed_area(xy: list[XY]) -> float:
    n = len(xy)
    return 0.5 * sum(
        xy[i][0] * xy[(i + 1) % n][1] - xy[(i + 1) % n][0] * xy[i][1] for i in range(n)
    )


def boundary_metrics(ring: tuple[LatLon, ...]) -> BoundaryMetrics:
    if len(ring) < 3:
        raise BoundaryError("A boundary needs at least 3 corners")
    frame = LocalFrame(ring[0])
    xy = frame.to_xy(ring)
    poly = Polygon(xy)
    if not poly.is_valid:
        raise BoundaryError("Boundary edges cross each other; redraw it without overlaps")
    n = len(xy)
    lengths = [math.dist(xy[i], xy[(i + 1) % n]) for i in range(n)]
    mids = [
        ((xy[i][0] + xy[(i + 1) % n][0]) / 2, (xy[i][1] + xy[(i + 1) % n][1]) / 2) for i in range(n)
    ]
    c = poly.centroid
    return BoundaryMetrics(
        area_m2=poly.area,
        perimeter_m=sum(lengths),
        interior_angles_deg=tuple(interior_angles_deg(xy)),
        segment_lengths_m=tuple(lengths),
        segment_midpoints=tuple(frame.to_latlon(mids)),
        centroid=frame.to_latlon([(c.x, c.y)])[0],
    )
