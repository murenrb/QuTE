"""Module areas drawn on the map: snapping and measurement (D-036).

A user may draw a module's area across the property line or over other areas;
on closing it is snapped to the available land: clipped to the property
boundary, minus the data center block and every other module's area. The
result can be several polygons, some with holes.
"""

import math
from collections.abc import Iterable, Sequence

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.config.defaults import SQFT_TO_M2, SiteAreaSettings
from core.domain.site import Area, AreaPolygon, LatLon, Ring
from core.geometry.local_frame import LocalFrame


class AreaError(ValueError):
    """The drawn area can't be placed. `str(e)` is user-facing."""


def _to_shape(frame: LocalFrame, poly: AreaPolygon) -> Polygon:
    return Polygon(frame.to_xy(poly.exterior), [frame.to_xy(h) for h in poly.holes])


def _from_shape(frame: LocalFrame, geom: BaseGeometry, min_m2: float) -> Area:
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    out = []
    for p in parts:
        if not isinstance(p, Polygon) or p.is_empty or p.area < min_m2:
            continue
        p = p.simplify(0.01)  # drop collinear vertices left by the clipping
        exterior = tuple(frame.to_latlon(list(p.exterior.coords)[:-1]))
        holes = tuple(tuple(frame.to_latlon(list(r.coords)[:-1])) for r in p.interiors)
        out.append(AreaPolygon(exterior=exterior, holes=holes))
    return tuple(out)


def snap_to_available_land(
    drawn: Ring,
    boundary: Ring,
    obstacles: Iterable[AreaPolygon],
    s: SiteAreaSettings,
) -> Area:
    """Drawn ring ∩ property boundary − obstacles, in lat/lon polygons."""
    return snap_rings([drawn], boundary, obstacles, s)


def snap_rings(
    rings: Sequence[Ring],
    boundary: Ring,
    obstacles: Iterable[AreaPolygon],
    s: SiteAreaSettings,
) -> Area:
    """Union of the rings (a drawn or vertex-edited area) snapped to the free land."""
    if not rings or any(len(r) < 3 for r in rings):
        raise AreaError("An area needs at least 3 corners")
    if len(boundary) < 3:
        raise AreaError("Draw the property boundary first (Property tab)")
    frame = LocalFrame(boundary[0])
    parts = [Polygon(frame.to_xy(r)) for r in rings]
    if not all(p.is_valid for p in parts):
        raise AreaError("The area's edges cross each other; redraw it without overlaps")
    shape = unary_union(parts)
    land = Polygon(frame.to_xy(boundary)).buffer(0)
    blocked = unary_union([_to_shape(frame, o) for o in obstacles])
    snapped = shape.intersection(land).difference(blocked)
    area = _from_shape(frame, snapped, s.min_piece_m2)
    if not area:
        raise AreaError("That area has no free land inside the property; draw it again")
    return area


def subtract(
    area: Sequence[AreaPolygon], obstacles: Sequence[AreaPolygon], s: SiteAreaSettings
) -> Area:
    """Area minus obstacles (a block placed over a drawn area cuts it back, D-041)."""
    if not area or not obstacles:
        return tuple(area)
    frame = LocalFrame(area[0].exterior[0])
    shape = unary_union([_to_shape(frame, p) for p in area])
    blocked = unary_union([_to_shape(frame, o) for o in obstacles])
    return _from_shape(frame, shape.difference(blocked), s.min_piece_m2)


def heal_holes(
    area: Sequence[AreaPolygon], obstacles: Sequence[AreaPolygon], s: SiteAreaSettings
) -> Area:
    """Fill the parts of the area's holes no obstacle covers any more (D-074).

    A hole is where the area was snapped around a block or another area; when
    that object moves away (or shrinks, or is removed) the freed land rejoins
    the area. Notches cut into the outer edge are not regrown. Slivers narrower
    than 2 × `heal_sliver_m` (rounding along an obstacle's edge) are ignored, so
    an area with nothing to heal comes back unchanged.
    """
    if not area or not any(p.holes for p in area):
        return tuple(area)
    frame = LocalFrame(area[0].exterior[0])
    shape = unary_union([_to_shape(frame, p) for p in area])
    filled = unary_union([Polygon(frame.to_xy(p.exterior)) for p in area])
    freed = filled.difference(shape)
    if obstacles:
        freed = freed.difference(unary_union([_to_shape(frame, o) for o in obstacles]))
    r = s.heal_sliver_m
    freed = freed.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")
    if freed.is_empty or freed.area < s.min_piece_m2:
        return tuple(area)
    return _from_shape(frame, shape.union(freed.intersection(filled)), s.min_piece_m2)


def square_up_rings(
    area: Sequence[AreaPolygon],
    boundary: Ring,
    obstacles: Sequence[AreaPolygon],
    s: SiteAreaSettings,
) -> list[Ring]:
    """Outlines with every *free* edge turned to the nearest compass direction
    (N/S/E/W or the 45° between them), rotating about its midpoint (D-042).

    An edge is fixed (unchanged) if it lies along the property boundary, a block
    or another module's area. New corners are where neighbouring edge lines
    meet; a corner whose lines are parallel, or that would move more than
    `max_vertex_shift_factor` × its edges, stays where it was. Holes are not
    returned — re-snapping recreates them around obstacles.
    """
    if not area:
        return []
    frame = LocalFrame(area[0].exterior[0])
    fixed_lines = (
        [LineString(frame.to_xy(list(boundary)) + frame.to_xy([boundary[0]]))]
        if len(boundary) >= 3
        else []
    )
    fixed_lines += [_to_shape(frame, o).exterior for o in obstacles]
    fixed = unary_union(fixed_lines) if fixed_lines else None
    step = math.radians(s.compass_step_deg)

    rings: list[Ring] = []
    for poly in area:
        pts = frame.to_xy(poly.exterior)
        n = len(pts)
        lines = []  # per edge i (pts[i] → pts[i+1]): (point, unit direction, length)
        for i in range(n):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % n]
            length = math.hypot(bx - ax, by - ay) or 1e-9
            mid = ((ax + bx) / 2, (ay + by) / 2)
            # Fixed only if the whole edge lies along a neighbour (both ends and the
            # midpoint within tolerance) — a sliver touching one at a point is free.
            free = fixed is None or any(
                fixed.distance(Point(q)) > s.edge_contact_tol_m for q in ((ax, ay), mid, (bx, by))
            )
            ang = math.atan2(by - ay, bx - ax)
            if free:
                ang = round(ang / step) * step
                lines.append((mid, (math.cos(ang), math.sin(ang)), length))
            else:
                lines.append(((ax, ay), ((bx - ax) / length, (by - ay) / length), length))
        new_pts = []
        for i in range(n):
            (p1, d1, l1), (p2, d2, l2) = lines[i - 1], lines[i]
            cross = d1[0] * d2[1] - d1[1] * d2[0]
            corner = pts[i]
            if abs(cross) > 1e-9:
                t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
                cand = (p1[0] + t * d1[0], p1[1] + t * d1[1])
                if math.dist(cand, pts[i]) <= s.max_vertex_shift_factor * max(l1, l2):
                    corner = cand
            new_pts.append(corner)
        rings.append(tuple(frame.to_latlon(new_pts)))
    return rings


def area_m2(area: Sequence[AreaPolygon]) -> float:
    if not area:
        return 0.0
    frame = LocalFrame(area[0].exterior[0])
    return float(sum(_to_shape(frame, p).area for p in area))


def area_sqft(area: Sequence[AreaPolygon]) -> float:
    return area_m2(area) / SQFT_TO_M2


def footprint_polygon(corners: list[LatLon]) -> AreaPolygon:
    """The data center block as an obstacle polygon."""
    return AreaPolygon(exterior=tuple(corners))


def overlap_m2(a: Sequence[AreaPolygon], b: Sequence[AreaPolygon]) -> float:
    """Overlapping area of two areas (for layout warnings after later edits)."""
    if not a or not b:
        return 0.0
    frame = LocalFrame(a[0].exterior[0])
    sa = unary_union([_to_shape(frame, p) for p in a])
    sb = unary_union([_to_shape(frame, p) for p in b])
    return float(sa.intersection(sb).area)


def outside_m2(area: Sequence[AreaPolygon], boundary: Ring) -> float:
    """Area lying outside the property boundary (after the boundary changed)."""
    if not area or len(boundary) < 3:
        return 0.0
    frame = LocalFrame(boundary[0])
    shape = unary_union([_to_shape(frame, p) for p in area])
    return float(shape.difference(Polygon(frame.to_xy(boundary)).buffer(0)).area)
