"""Facility block geometry (docs/workflow/01-setup-tabs.md §3.4).

The block's area is fixed by sizing; resizing one side sets the other so the
area stays constant.
"""

import math

from shapely.geometry import Polygon

from core.config.defaults import FootprintSettings
from core.domain.site import Footprint, LatLon
from core.geometry.local_frame import LocalFrame


def square_footprint(center: LatLon, area_m2: float, rotation_deg: float = 0.0) -> Footprint:
    side = math.sqrt(area_m2)
    return Footprint(
        center_lat=center[0],
        center_lon=center[1],
        width_m=side,
        length_m=side,
        rotation_deg=rotation_deg,
    )


def clamp_width(width_m: float, area_m2: float, s: FootprintSettings) -> float:
    """Keep length/width within [min_aspect, max_aspect] for this area."""
    w_max = math.sqrt(area_m2 / s.min_aspect)
    w_min = math.sqrt(area_m2 / s.max_aspect)
    return min(max(width_m, w_min), w_max)


def with_width(fp: Footprint, width_m: float, s: FootprintSettings) -> Footprint:
    """Edge drag: set width, length = area / width (area preserved)."""
    w = clamp_width(width_m, fp.area_m2, s)
    return fp.model_copy(update={"width_m": w, "length_m": fp.area_m2 / w})


def with_length(fp: Footprint, length_m: float, s: FootprintSettings) -> Footprint:
    """Set length, width = area / length (area preserved, same aspect limits)."""
    return with_width(fp, fp.area_m2 / length_m, s)


def align_to_nearest_edge(fp: Footprint, boundary: tuple[LatLon, ...]) -> Footprint:
    """Rotate so the block's width axis runs parallel to the closest boundary side.

    Width runs east–west at rotation 0 and rotation is clockwise, so the width
    axis has compass bearing 90° + rotation; matching an edge bearing β gives
    rotation = (β − 90°) mod 180°.
    """
    if len(boundary) < 2:
        return fp
    frame = LocalFrame(fp.center)
    pts = frame.to_xy(list(boundary))
    n = len(pts)

    def distance_to_segment(i: int) -> float:
        (ax, ay), (bx, by) = pts[i], pts[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy or 1.0)))
        return math.hypot(ax + t * dx, ay + t * dy)  # block center is the origin

    i = min(range(n), key=distance_to_segment)
    (ax, ay), (bx, by) = pts[i], pts[(i + 1) % n]
    bearing = math.degrees(math.atan2(bx - ax, by - ay))  # clockwise from north
    return fp.model_copy(update={"rotation_deg": normalize_rotation(bearing - 90.0)})


def edited_footprint(
    center: LatLon, width_m: float, rotation_deg: float, area_m2: float, s: FootprintSettings
) -> Footprint:
    """Footprint from a map edit, re-validated: area forced to the sized area,
    width clamped to the aspect limits, rotation normalized to [0, 180)."""
    w = clamp_width(width_m, area_m2, s)
    return Footprint(
        center_lat=center[0],
        center_lon=center[1],
        width_m=w,
        length_m=area_m2 / w,
        rotation_deg=normalize_rotation(rotation_deg),
    )


def with_area(fp: Footprint, area_m2: float) -> Footprint:
    """New sized area (e.g. IT load changed): keep aspect ratio and placement."""
    k = math.sqrt(area_m2 / fp.area_m2)
    return fp.model_copy(update={"width_m": fp.width_m * k, "length_m": fp.length_m * k})


def normalize_rotation(deg: float) -> float:
    """A rectangle repeats every 180°; store in [0, 180)."""
    return deg % 180.0


def footprint_corners(fp: Footprint) -> list[LatLon]:
    """Corners (lat, lon), clockwise from the rotated north-west corner."""
    frame = LocalFrame(fp.center)
    hw, hl = fp.width_m / 2, fp.length_m / 2
    t = math.radians(fp.rotation_deg)
    cos_t, sin_t = math.cos(t), math.sin(t)
    local = [(-hw, hl), (hw, hl), (hw, -hl), (-hw, -hl)]
    # Clockwise rotation by t: x' = x cos t + y sin t, y' = −x sin t + y cos t
    rotated = [(x * cos_t + y * sin_t, -x * sin_t + y * cos_t) for x, y in local]
    return frame.to_latlon(rotated)


def footprint_within_boundary(
    fp: Footprint, boundary: tuple[LatLon, ...], s: FootprintSettings
) -> bool:
    """True if the whole block is inside the boundary (touching the edge counts)."""
    if len(boundary) < 3:
        return False
    frame = LocalFrame(fp.center)
    block = Polygon(frame.to_xy(footprint_corners(fp)))
    parcel = Polygon(frame.to_xy(list(boundary))).buffer(s.edge_tolerance_m)
    return bool(parcel.covers(block))
