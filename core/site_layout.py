"""Site layout rules for the data center block and module areas/blocks (D-036, D-041).

Pure functions on `Project`, so the UI stays thin and this logic is testable.

- Scaled-in-map modules (drawn areas) snap to the free land: inside the
  boundary, outside every block and other drawn areas.
- Blocks (the data center and scaled-in-inputs modules) cut back any drawn area
  they cover, automatically.
- A block overlapping another block or sticking out of the boundary is a
  warning (red on the map), never blocked.
"""

import math
from dataclasses import dataclass

from core.config.defaults import FOOTPRINT, SITE_AREAS, SiteAreaSettings
from core.domain.modules import ModuleContext
from core.domain.site import AreaPolygon, Footprint, LatLon, Ring
from core.geometry.areas import (
    footprint_polygon,
    outside_m2,
    overlap_m2,
    snap_rings,
    snap_to_available_land,
    square_up_rings,
    subtract,
)
from core.geometry.boundary import BoundaryError, boundary_metrics
from core.geometry.footprint import (
    footprint_corners,
    footprint_within_boundary,
    square_footprint,
    with_area,
)
from core.geometry.local_frame import LocalFrame
from core.persistence.project import Project

DATA_CENTER = "data_center"  # owner key of the data center block(s)


@dataclass(frozen=True)
class Block:
    owner: str  # "data_center" or a module key
    footprint: Footprint

    @property
    def polygon(self) -> AreaPolygon:
        return footprint_polygon(footprint_corners(self.footprint))


def blocks(project: Project) -> list[Block]:
    """Every block on the site: the data center(s) and placed scaled-in-inputs modules."""
    out = [Block(DATA_CENTER, dc.footprint) for dc in project.facilities if dc.footprint]
    out += [
        Block(key, params.footprint)
        for key, params in project.modules.blocks().items()
        if params.placed and params.footprint is not None
    ]
    return out


def facility_polygons(project: Project) -> list[AreaPolygon]:
    return [b.polygon for b in blocks(project) if b.owner == DATA_CENTER]


def obstacles_for(project: Project, module_key: str) -> list[AreaPolygon]:
    """What a drawn area must not overlap: every block and every other drawn area."""
    others = [
        poly
        for key, params in project.modules.sited().items()
        if key != module_key and params.placed
        for poly in params.area
    ]
    return [b.polygon for b in blocks(project)] + others


# --- drawn areas (scaled in map) ---------------------------------------------------


def place_module_area(project: Project, module_key: str, drawn: Ring) -> Project:
    """Snap a freshly drawn ring and store it as the module's area.

    Raises core.geometry.areas.AreaError (user-facing) if nothing is left.
    """
    area = snap_to_available_land(
        drawn, project.site.boundary, obstacles_for(project, module_key), SITE_AREAS
    )
    return project.model_copy(update={"modules": project.modules.with_area(module_key, area)})


def reshape_module_area(project: Project, module_key: str, rings: list[Ring]) -> Project:
    """Vertex edit: the edited outlines snap by the same rules as a new drawing."""
    area = snap_rings(rings, project.site.boundary, obstacles_for(project, module_key), SITE_AREAS)
    return project.model_copy(update={"modules": project.modules.with_area(module_key, area)})


def square_up_module_area(project: Project, module_key: str) -> Project:
    """ "Snap edges to N/S/E/W": free edges to compass directions, then the usual
    snapping to the free land (D-042). Raises AreaError if nothing is left."""
    obstacles = obstacles_for(project, module_key)
    current = project.modules.sited()[module_key].area
    rings = square_up_rings(current, project.site.boundary, obstacles, SITE_AREAS)
    area = snap_rings(rings, project.site.boundary, obstacles, SITE_AREAS)
    return project.model_copy(update={"modules": project.modules.with_area(module_key, area)})


def clear_module_area(project: Project, module_key: str) -> Project:
    return project.model_copy(update={"modules": project.modules.with_area(module_key, ())})


# --- blocks (scaled in inputs) -----------------------------------------------------


def set_block_footprint(project: Project, owner: str, fp: Footprint) -> Project:
    if owner == DATA_CENTER:
        if not project.facilities:
            return project
        dc = project.facilities[0].model_copy(update={"footprint": fp})
        return project.model_copy(update={"facilities": (dc, *project.facilities[1:])})
    return project.model_copy(update={"modules": project.modules.with_footprint(owner, fp)})


def _reference_center(project: Project) -> LatLon | None:
    site = project.site
    if len(site.boundary) >= 3:
        try:
            return boundary_metrics(site.boundary).centroid
        except BoundaryError:
            pass
    return site.location


def _shaped_footprint(
    center: LatLon, area_m2: float, dims: tuple[float, float] | None
) -> Footprint:
    if dims is None:
        return square_footprint(center, area_m2)
    return Footprint(center_lat=center[0], center_lon=center[1], width_m=dims[0], length_m=dims[1])


def default_block_footprint(
    project: Project,
    area_m2: float,
    s: SiteAreaSettings = SITE_AREAS,
    dims: tuple[float, float] | None = None,
) -> Footprint | None:
    """A block of `area_m2` beside the data center block (E, W, N, S — the first
    that is inside the boundary and clear of other blocks), else at the site center.

    dims: default (width, length) in m; None = a square."""
    center = _reference_center(project)
    if center is None:
        return None
    dcs = [b.footprint for b in blocks(project) if b.owner == DATA_CENTER]
    if not dcs:
        return _shaped_footprint(center, area_m2, dims)
    dc = dcs[0]
    half = max(dims) / 2 if dims is not None else math.sqrt(area_m2) / 2
    reach = math.hypot(dc.width_m, dc.length_m) / 2 + half + s.block_gap_m
    frame = LocalFrame(dc.center)
    candidates = [
        _shaped_footprint(frame.to_latlon([xy])[0], area_m2, dims)
        for xy in ((reach, 0.0), (-reach, 0.0), (0.0, reach), (0.0, -reach))
    ]
    existing = [b.polygon for b in blocks(project)]
    for fp in candidates:
        poly = footprint_polygon(footprint_corners(fp))
        inside = len(project.site.boundary) < 3 or footprint_within_boundary(
            fp, project.site.boundary, FOOTPRINT
        )
        if inside and overlap_m2((poly,), existing) <= s.overlap_tolerance_m2:
            return fp
    return candidates[0]


def reset_block_shape(project: Project, key: str) -> Project:
    """Give a module block its default shape again, keeping center and rotation
    (e.g. hot water storage switched between two tank and thermocline)."""
    block = project.modules.blocks()[key]
    if block.footprint is None:
        return project
    dims = block.resolved(module_context(project)).default_dims_m()
    if dims is None:
        return project
    fp = block.footprint.model_copy(update={"width_m": dims[0], "length_m": dims[1]})
    return set_block_footprint(project, key, fp)


def module_context(project: Project) -> ModuleContext:
    if not project.facilities:
        return ModuleContext(site_lat=project.site.lat)
    dc = project.facilities[0]
    return ModuleContext(
        it_peak_mw=dc.it_load_peak_mw,
        site_lat=project.site.lat,
        t_supply_c=dc.dc_type.t_supply_c,
        t_return_c=dc.dc_type.t_return_c,
        it_parasitic_frac=project.assumptions.it_parasitic_frac,
    )


def normalize_layout(project: Project, s: SiteAreaSettings = SITE_AREAS) -> Project:
    """Apply the layout rules; idempotent (no change when already consistent).

    1. Enabled blocks get a footprint (placed beside the data center) and follow
       their input-defined area (shape and position kept).
    2. Drawn areas lose whatever any block now covers.
    """
    p = project
    for key, block in p.modules.blocks().items():
        if not block.enabled:
            continue
        resolved = block.resolved(module_context(p))
        area = resolved.block_area_m2
        fp = block.footprint
        if fp is None:
            new = default_block_footprint(p, area, s, resolved.default_dims_m())
        elif not math.isclose(fp.area_m2, area, rel_tol=1e-9):
            new = with_area(fp, area)
        else:
            continue
        if new is not None:
            p = set_block_footprint(p, key, new)

    block_polys = [b.polygon for b in blocks(p)]
    for key, drawn in p.modules.sited().items():
        if drawn.placed and overlap_m2(drawn.area, block_polys) > s.overlap_tolerance_m2:
            p = p.model_copy(
                update={"modules": p.modules.with_area(key, subtract(drawn.area, block_polys, s))}
            )
    return p


@dataclass(frozen=True)
class BlockIssues:
    outside_boundary: bool
    overlaps: tuple[str, ...]  # owners of other blocks it overlaps

    @property
    def any(self) -> bool:
        return self.outside_boundary or bool(self.overlaps)


def block_issues(project: Project, s: SiteAreaSettings = SITE_AREAS) -> dict[str, BlockIssues]:
    """Per block owner: outside the boundary? overlapping which other blocks?"""
    all_blocks = blocks(project)
    boundary = project.site.boundary
    out = {}
    for b in all_blocks:
        outside = len(boundary) >= 3 and not footprint_within_boundary(
            b.footprint, boundary, FOOTPRINT
        )
        overlaps = tuple(
            o.owner
            for o in all_blocks
            if o is not b and overlap_m2((b.polygon,), (o.polygon,)) > s.overlap_tolerance_m2
        )
        out[b.owner] = BlockIssues(outside, overlaps)
    return out


def layout_warnings(project: Project, labels: dict[str, str]) -> list[str]:
    """User-facing layout warnings (labels: owner key → display name)."""

    def name(owner: str) -> str:
        return "data center block" if owner == DATA_CENTER else f"{labels.get(owner, owner)} block"

    warnings = []
    seen_pairs: set[frozenset[str]] = set()
    for owner, issue in block_issues(project).items():
        if issue.outside_boundary:
            warnings.append(f"The {name(owner)} extends outside the property boundary.")
        for other in issue.overlaps:
            pair = frozenset((owner, other))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                warnings.append(f"The {name(owner)} overlaps the {name(other)}.")
    boundary = project.site.boundary
    for key, params in project.modules.sited().items():
        if params.placed and outside_m2(params.area, boundary) > SITE_AREAS.overlap_tolerance_m2:
            label = labels.get(key, key)
            warnings.append(f"Part of the {label} area is outside the property boundary.")
    return warnings
