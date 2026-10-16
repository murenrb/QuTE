"""Module areas: snapping to free land, measurement, layout warnings (D-036)."""

import pytest

from core.config.defaults import KW_PER_TR, SITE_AREAS, SQFT_TO_M2
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.modules import (
    IceStorageParams,
    MapScaling,
    ModuleSettings,
    SitedModuleParams,
    SolarPVParams,
    map_scaling,
)
from core.domain.site import AreaPolygon, LatLon, Site
from core.geometry.areas import (
    AreaError,
    area_m2,
    area_sqft,
    outside_m2,
    overlap_m2,
    snap_to_available_land,
)
from core.geometry.local_frame import LocalFrame
from core.persistence.project import Project
from core.site_layout import (
    DATA_CENTER,
    block_issues,
    blocks,
    clear_module_area,
    facility_polygons,
    layout_warnings,
    module_context,
    normalize_layout,
    obstacles_for,
    place_module_area,
    reshape_module_area,
    set_block_footprint,
    square_up_module_area,
)

ORIGIN: LatLon = (33.45, -112.07)
F = LocalFrame(ORIGIN)


def ring(*xy: tuple[float, float]) -> tuple[LatLon, ...]:
    return tuple(F.to_latlon(list(xy)))


BOUNDARY = ring((0, 0), (200, 0), (200, 100), (0, 100))  # 20,000 m²


def poly(*xy: tuple[float, float]) -> AreaPolygon:
    return AreaPolygon(exterior=ring(*xy))


# --- snapping -----------------------------------------------------------------


def test_inside_area_unchanged() -> None:
    (p,) = snap_to_available_land(
        ring((10, 10), (60, 10), (60, 60), (10, 60)), BOUNDARY, [], SITE_AREAS
    )
    assert area_m2((p,)) == pytest.approx(2500, rel=1e-6)


def test_clipped_to_property_line() -> None:
    drawn = ring((150, 50), (300, 50), (300, 150), (150, 150))  # 3/4 outside
    area = snap_to_available_land(drawn, BOUNDARY, [], SITE_AREAS)
    assert area_m2(area) == pytest.approx(50 * 50, rel=1e-6)
    assert outside_m2(area, BOUNDARY) == pytest.approx(0, abs=1e-6)


def test_obstacle_cut_out_and_split() -> None:
    block = poly((90, -10), (110, -10), (110, 110), (90, 110))  # full-height strip
    drawn = ring((50, 20), (150, 20), (150, 80), (50, 80))
    area = snap_to_available_land(drawn, BOUNDARY, [block], SITE_AREAS)
    assert len(area) == 2  # split in two by the strip
    assert area_m2(area) == pytest.approx(2 * 40 * 60, rel=1e-6)
    assert overlap_m2(area, (block,)) == pytest.approx(0, abs=1e-6)


def test_surrounding_an_obstacle_leaves_a_hole() -> None:
    block = poly((90, 40), (110, 40), (110, 60), (90, 60))
    drawn = ring((50, 20), (150, 20), (150, 80), (50, 80))
    (p,) = snap_to_available_land(drawn, BOUNDARY, [block], SITE_AREAS)
    assert len(p.holes) == 1
    assert area_m2((p,)) == pytest.approx(100 * 60 - 20 * 20, rel=1e-6)


def test_slivers_dropped() -> None:
    drawn = ring((199.5, 10), (260, 10), (260, 60), (199.5, 60))  # 0.5 m × 50 m inside = 25 m²
    assert len(snap_to_available_land(drawn, BOUNDARY, [], SITE_AREAS)) == 1
    tiny = ring((199.99, 10), (260, 10), (260, 60), (199.99, 60))  # 0.5 m² inside
    with pytest.raises(AreaError, match="no free land"):
        snap_to_available_land(tiny, BOUNDARY, [], SITE_AREAS)


@pytest.mark.parametrize(
    ("drawn", "boundary", "match"),
    [
        (ring((300, 300), (400, 300), (400, 400)), BOUNDARY, "no free land"),
        (ring((0, 0), (10, 10), (10, 0), (0, 10)), BOUNDARY, "cross"),
        (ring((0, 0), (10, 0), (10, 10)), (), "property boundary first"),
    ],
)
def test_snap_errors(drawn, boundary, match: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AreaError, match=match):
        snap_to_available_land(drawn, boundary, [], SITE_AREAS)


def test_area_sqft() -> None:
    assert area_sqft((poly((0, 0), (10, 0), (10, 10), (0, 10)),)) == pytest.approx(100 / SQFT_TO_M2)
    assert area_sqft(()) == 0


# --- site layout ----------------------------------------------------------------


def _project_with_block() -> Project:
    from core.geometry.footprint import square_footprint

    center = F.to_latlon([(100, 50)])[0]
    dc = DataCenter(
        dc_type=DataCenterType(), it_load_peak_mw=1, footprint=square_footprint(center, 400.0)
    )
    return Project(
        site=Site(lat=33.45, lon=-112.07, boundary=BOUNDARY),
        facilities=(dc,),
        modules=ModuleSettings().with_enabled("solar_pv", True),  # added on the Modules tab
    )


def test_sited_modules_are_discovered_generically() -> None:
    sited = ModuleSettings().sited()
    assert set(sited) == {"solar_pv", "greenhouse"}
    assert all(isinstance(v, SitedModuleParams) for v in sited.values())


def test_place_module_area_avoids_block_and_clears() -> None:
    project = _project_with_block()
    assert len(obstacles_for(project, "solar_pv")) == 1  # the block
    drawn = ring((50, 20), (150, 20), (150, 80), (50, 80))
    placed = place_module_area(project, "solar_pv", drawn)
    pv = placed.modules.solar_pv
    assert pv.placed and len(pv.area[0].holes) == 1  # block cut out
    assert area_m2(pv.area) == pytest.approx(100 * 60 - 400, rel=1e-6)
    assert not clear_module_area(placed, "solar_pv").modules.solar_pv.placed
    # Other settings are kept when the area changes.
    tilted = placed.model_copy(
        update={"modules": ModuleSettings(solar_pv=pv.model_copy(update={"tilt_deg": 30}))}
    )
    assert clear_module_area(tilted, "solar_pv").modules.solar_pv.tilt_deg == 30


def test_layout_warnings_after_later_edits() -> None:
    project = _project_with_block()
    outside = poly((180, 10), (220, 10), (220, 40), (180, 40))  # boundary moved since drawing
    p = project.model_copy(
        update={"modules": ModuleSettings(solar_pv=SolarPVParams(enabled=True, area=(outside,)))}
    )
    warnings = layout_warnings(p, {"solar_pv": "Solar PV"})
    assert warnings == ["Part of the Solar PV area is outside the property boundary."]
    assert layout_warnings(project, {}) == []  # nothing placed


# --- blocks (scaled in inputs) and their effect on drawn areas (D-041) ---------------


def _with_ice(project: Project, **changes: object) -> Project:
    ice = IceStorageParams(enabled=True, **changes)  # type: ignore[arg-type]
    return project.model_copy(
        update={"modules": project.modules.model_copy(update={"ice_storage": ice})}
    )


def test_categories() -> None:
    m = ModuleSettings()
    assert map_scaling(m.solar_pv) is MapScaling.MAP
    assert map_scaling(m.ice_storage) is MapScaling.INPUTS
    assert map_scaling(m.power_generation) is MapScaling.INPUTS
    assert map_scaling(m.greenhouse) is MapScaling.MAP
    assert set(m.sited()) == {"solar_pv", "greenhouse"}
    assert map_scaling(m.hot_water_storage) is MapScaling.INPUTS
    assert map_scaling(m.brine_separation) is MapScaling.INPUTS
    assert set(m.blocks()) == {
        "ice_storage",
        "power_generation",
        "hot_water_storage",
        "brine_separation",
    }


def test_ice_footprint_from_tank_and_density() -> None:
    ice = IceStorageParams(enabled=True, ice_maker_size_tr=1000, tank_charge_time_h=24)
    assert ice.footprint_sqft == pytest.approx(1000 * KW_PER_TR * 24 / 15)  # 5,627 sqft
    denser = ice.model_copy(update={"energy_density_kwh_sqft": 30})
    assert denser.footprint_sqft == pytest.approx(ice.footprint_sqft / 2)


def test_enabled_block_is_placed_beside_the_data_center() -> None:
    p = normalize_layout(_with_ice(_project_with_block()))
    ice = p.modules.ice_storage.footprint
    assert ice is not None
    resolved = p.modules.ice_storage.resolved(module_context(p))  # 65 TR/MW × 1 MW
    assert ice.area_m2 == pytest.approx(resolved.block_area_m2)
    issues = block_issues(p)
    assert not issues["ice_storage"].any and not issues[DATA_CENTER].any  # clear, inside
    assert normalize_layout(p) == p  # idempotent


def test_disabled_block_not_placed() -> None:
    p = normalize_layout(_project_with_block())
    assert p.modules.ice_storage.footprint is None
    assert [b.owner for b in blocks(p)] == [DATA_CENTER]


def test_block_follows_input_area_keeping_position() -> None:
    p = normalize_layout(_with_ice(_project_with_block()))
    before = p.modules.ice_storage.footprint
    denser = p.modules.ice_storage.model_copy(update={"energy_density_kwh_sqft": 30.0})
    p2 = normalize_layout(
        p.model_copy(update={"modules": p.modules.model_copy(update={"ice_storage": denser})})
    )
    after = p2.modules.ice_storage.footprint
    assert after.area_m2 == pytest.approx(before.area_m2 / 2)
    assert after.center == before.center


def test_block_over_drawn_area_cuts_it_back_and_holes_heal() -> None:
    project = _project_with_block()
    pv_area = (poly((10, 10), (60, 10), (60, 60), (10, 60)),)  # 2,500 m², clear of the DC
    p = project.model_copy(
        update={"modules": ModuleSettings(solar_pv=SolarPVParams(enabled=True, area=pv_area))}
    )
    p = normalize_layout(_with_ice(p))
    # Drag the ice block into the middle of the PV area.
    ice = p.modules.ice_storage.footprint
    center = F.to_latlon([(35, 35)])[0]
    moved = set_block_footprint(
        p, "ice_storage", ice.model_copy(update={"center_lat": center[0], "center_lon": center[1]})
    )
    cut = normalize_layout(moved)
    pv = cut.modules.solar_pv.area
    assert area_m2(pv) == pytest.approx(2500 - ice.area_m2, rel=1e-6)
    assert overlap_m2(pv, [b.polygon for b in blocks(cut)]) == pytest.approx(0, abs=1e-6)
    # Moving the block away again heals the hole it left (D-074).
    away = normalize_layout(set_block_footprint(cut, "ice_storage", ice))
    assert area_m2(away.modules.solar_pv.area) == pytest.approx(2500, rel=1e-6)
    assert not any(q.holes for q in away.modules.solar_pv.area)
    assert normalize_layout(away) == away  # idempotent


def test_notch_on_the_outer_edge_is_not_regrown() -> None:
    project = _project_with_block()
    pv_area = (poly((10, 10), (60, 10), (60, 60), (10, 60)),)
    p = normalize_layout(
        _with_ice(
            project.model_copy(
                update={
                    "modules": ModuleSettings(solar_pv=SolarPVParams(enabled=True, area=pv_area))
                }
            )
        )
    )
    ice = p.modules.ice_storage.footprint
    edge = F.to_latlon([(10, 35)])[0]  # straddling the area's west edge
    moved = set_block_footprint(
        p, "ice_storage", ice.model_copy(update={"center_lat": edge[0], "center_lon": edge[1]})
    )
    cut = normalize_layout(moved)
    notched = area_m2(cut.modules.solar_pv.area)
    assert notched < 2500 - 1
    away = normalize_layout(set_block_footprint(cut, "ice_storage", ice))
    assert area_m2(away.modules.solar_pv.area) == pytest.approx(notched)


def test_hole_around_the_data_center_heals_where_it_moved_out() -> None:
    from core.geometry.footprint import square_footprint

    project = _project_with_block()  # 20 × 20 m block centred at (100, 50)
    drawn = ring((50, 20), (150, 20), (150, 80), (50, 80))
    p = normalize_layout(place_module_area(project, "solar_pv", drawn))
    assert len(p.modules.solar_pv.area[0].holes) == 1
    # Shift the block 10 m east: half of the old hole is free again.
    shifted = F.to_latlon([(110, 50)])[0]
    dc = p.facilities[0].model_copy(update={"footprint": square_footprint(shifted, 400.0)})
    half = normalize_layout(p.model_copy(update={"facilities": (dc,)}))
    area = half.modules.solar_pv.area
    assert area_m2(area) == pytest.approx(100 * 60 - 400, rel=1e-6)  # block still cut out
    assert overlap_m2(area, facility_polygons(half)) < SITE_AREAS.overlap_tolerance_m2
    # Fully out of the area: no hole left.
    gone = F.to_latlon([(180, 50)])[0]
    dc = p.facilities[0].model_copy(update={"footprint": square_footprint(gone, 400.0)})
    out = normalize_layout(p.model_copy(update={"facilities": (dc,)}))
    assert area_m2(out.modules.solar_pv.area) == pytest.approx(100 * 60, rel=1e-6)


def test_hole_around_another_area_heals_when_it_is_cleared() -> None:
    project = _project_with_block()
    p = project.model_copy(update={"modules": project.modules.with_enabled("greenhouse", True)})
    p = place_module_area(p, "greenhouse", ring((20, 20), (40, 20), (40, 40), (20, 40)))
    p = normalize_layout(
        place_module_area(p, "solar_pv", ring((10, 10), (60, 10), (60, 60), (10, 60)))
    )
    assert area_m2(p.modules.solar_pv.area) == pytest.approx(2500 - 400, rel=1e-6)
    healed = normalize_layout(clear_module_area(p, "greenhouse"))
    assert area_m2(healed.modules.solar_pv.area) == pytest.approx(2500, rel=1e-6)


def test_overlapping_blocks_flagged_both_ways() -> None:
    p = normalize_layout(_with_ice(_project_with_block()))
    dc = p.facilities[0].footprint
    on_top = set_block_footprint(
        p,
        "ice_storage",
        p.modules.ice_storage.footprint.model_copy(
            update={"center_lat": dc.center_lat, "center_lon": dc.center_lon}
        ),
    )
    issues = block_issues(on_top)
    assert issues["ice_storage"].overlaps == (DATA_CENTER,)
    assert issues[DATA_CENTER].overlaps == ("ice_storage",)
    warnings = layout_warnings(on_top, {"ice_storage": "Ice storage"})
    assert warnings == ["The data center block overlaps the Ice storage block."]


def test_block_outside_boundary_flagged() -> None:
    p = normalize_layout(_with_ice(_project_with_block()))
    far = F.to_latlon([(500, 500)])[0]
    out = set_block_footprint(
        p,
        "ice_storage",
        p.modules.ice_storage.footprint.model_copy(
            update={"center_lat": far[0], "center_lon": far[1]}
        ),
    )
    assert block_issues(out)["ice_storage"].outside_boundary
    assert "The Ice storage block extends outside the property boundary." in layout_warnings(
        out, {"ice_storage": "Ice storage"}
    )


def test_drawn_area_snaps_around_module_blocks_too() -> None:
    p = normalize_layout(_with_ice(_project_with_block()))
    ice_poly = next(b.polygon for b in blocks(p) if b.owner == "ice_storage")
    placed = place_module_area(p, "solar_pv", BOUNDARY)  # draw over the whole property
    assert overlap_m2(placed.modules.solar_pv.area, (ice_poly,)) == pytest.approx(0, abs=1e-6)


def test_vertex_edit_obeys_the_same_rules() -> None:
    project = _project_with_block()
    square = ring((10, 10), (60, 10), (60, 60), (10, 60))
    p = place_module_area(project, "solar_pv", square)
    # Drag one corner far outside the property and across the data center block.
    edited = [ring((10, 10), (60, 10), (300, 200), (10, 60))]
    reshaped = reshape_module_area(p, "solar_pv", edited)
    area = reshaped.modules.solar_pv.area
    assert outside_m2(area, BOUNDARY) == pytest.approx(0, abs=1e-6)
    assert overlap_m2(area, facility_polygons(reshaped)) == pytest.approx(0, abs=1e-6)
    assert area_m2(area) > 2500  # grew, unlike a block's fixed area
    with pytest.raises(AreaError, match="cross"):
        reshape_module_area(p, "solar_pv", [ring((10, 10), (60, 60), (60, 10), (10, 60))])


# --- "Snap edges to N/S/E/W" (D-042) ----------------------------------------------


def _bearings(area_poly: AreaPolygon) -> list[float]:
    import math

    pts = F.to_xy(area_poly.exterior)
    n = len(pts)
    return [
        round(
            math.degrees(
                math.atan2(pts[(i + 1) % n][1] - pts[i][1], pts[(i + 1) % n][0] - pts[i][0])
            )
            % 180,
            3,
        )
        for i in range(n)
    ]


def _rotated(points: list[tuple[float, float]], deg: float, c=(100.0, 50.0)) -> tuple:  # type: ignore[type-arg]
    import math

    t = math.radians(deg)
    return ring(
        *[
            (
                c[0] + (x - c[0]) * math.cos(t) - (y - c[1]) * math.sin(t),
                c[1] + (x - c[0]) * math.sin(t) + (y - c[1]) * math.cos(t),
            )
            for x, y in points
        ]
    )


def test_free_edges_snap_to_compass_directions() -> None:
    project = Project(site=Site(lat=33.45, lon=-112.07, boundary=BOUNDARY))
    drawn = _rotated([(70, 30), (130, 30), (130, 70), (70, 70)], 7)  # 7° off axis
    p = place_module_area(project, "solar_pv", drawn)
    squared = square_up_module_area(p, "solar_pv").modules.solar_pv.area
    # Bearings measured in a slightly different local frame than the snap used: ±0.01°.
    assert all(min(b % 45, 45 - b % 45) < 0.01 for b in _bearings(squared[0]))
    assert area_m2(squared) == pytest.approx(60 * 40, rel=0.05)


def test_diagonal_edges_snap_to_45() -> None:
    project = Project(site=Site(lat=33.45, lon=-112.07, boundary=BOUNDARY))
    drawn = _rotated([(80, 30), (120, 30), (120, 70), (80, 70)], 40)  # near 45°
    p = place_module_area(project, "solar_pv", drawn)
    squared = square_up_module_area(p, "solar_pv").modules.solar_pv.area
    assert sorted({round(b, 1) for b in _bearings(squared[0])}) == [45.0, 135.0]


def test_edges_against_neighbours_stay_put() -> None:
    project = _project_with_block()  # DC block 20 × 20 m centred at (100, 50)
    # Area touching the block's west side (x = 90) with a skewed free outer edge.
    drawn = ring((60, 40), (90, 40), (90, 60), (55, 62))
    p = place_module_area(project, "solar_pv", drawn)
    squared = square_up_module_area(p, "solar_pv").modules.solar_pv.area
    xs = [x for x, _ in F.to_xy(squared[0].exterior)]
    assert max(xs) == pytest.approx(90, abs=0.05)  # still flush with the block
    assert overlap_m2(squared, facility_polygons(p)) < 0.01  # rounding only
    assert {round(b, 1) for b in _bearings(squared[0])} <= {0.0, 90.0, 180.0}  # squared
