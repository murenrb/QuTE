"""D-027: the active tab sets the map's tools (docs/gui.md → Map)."""

import pytest
from folium.plugins import Draw

from app.components.map_view import (
    CLICK_OBJECTS,
    MapMode,
    MapView,
    _ArmPolygon,
    build_map,
    build_overlay,
    parse_bounds,
    parse_polygon,
    parse_view,
    polygon_tool_armed,
    returned_objects,
)
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.site import Site
from core.geometry.footprint import square_footprint
from core.persistence.project import Project

VIEW = (33.44, -112.08, 33.46, -112.06)
CENTER, ZOOM = (33.4501, -112.0702), 17.0
RING = ((33.449, -112.071), (33.449, -112.069), (33.451, -112.069), (33.451, -112.071))
LOCKS = ("dragging", "scrollWheelZoom", "doubleClickZoom", "touchZoom", "boxZoom", "keyboard")


def _project(boundary: tuple = (), legacy: bool = False) -> Project:  # type: ignore[type-arg]
    """legacy=True: saved before center/zoom were stored (bounds only)."""
    fp = square_footprint((33.45, -112.07), 2000.0)
    view = {} if legacy else {"map_center": CENTER, "map_zoom": ZOOM}
    return Project(
        site=Site(lat=33.45, lon=-112.07, map_view=VIEW, boundary=boundary, **view),
        facilities=(DataCenter(dc_type=DataCenterType(), it_load_peak_mw=5, footprint=fp),),
    )


def _children(fmap):  # type: ignore[no-untyped-def]
    return list(fmap._children.values())


def _fitted(fmap):  # type: ignore[no-untyped-def]
    return [c for c in _children(fmap) if type(c).__name__ == "FitBounds"]


def test_location_is_free_with_no_tools() -> None:
    fmap = build_map(_project(), MapMode.LOCATION, mount_view=None)
    assert all(fmap.options.get(k, True) is not False for k in LOCKS)
    assert fmap.options.get("zoom_control", True) is not False
    assert not any(isinstance(c, (Draw, _ArmPolygon)) for c in _children(fmap))
    assert returned_objects(MapMode.LOCATION, False) == ["bounds", "center", "zoom", *CLICK_OBJECTS]


def test_location_opens_on_the_mount_view_not_the_live_view() -> None:
    mount = MapView(VIEW, (33.46, -112.05), 15.0)
    fmap = build_map(_project(), MapMode.LOCATION, mount_view=mount)
    assert (tuple(fmap.location), fmap.options["zoom"]) == ((33.46, -112.05), 15.0)
    assert not _fitted(fmap)


@pytest.mark.parametrize("mode", [MapMode.PROPERTY, MapMode.DATA_CENTER, MapMode.MODULES])
def test_other_tabs_are_locked_to_the_saved_view(mode: MapMode) -> None:
    fmap = build_map(_project(RING), mode, mount_view=None)
    assert all(fmap.options[k] is False for k in LOCKS)
    assert fmap.options["zoom_control"] is False
    assert '"zoomControl": false' in fmap.get_root().render()  # what Leaflet receives


@pytest.mark.parametrize("mode", [MapMode.PROPERTY, MapMode.DATA_CENTER, MapMode.MODULES])
def test_locked_tabs_reopen_at_exact_location_center_and_zoom(mode: MapMode) -> None:
    """Regression (D-031): re-fitting bounds rounded down a zoom level (50 %)."""
    fmap = build_map(_project(RING), mode, mount_view=None)
    assert (tuple(fmap.location), fmap.options["zoom"]) == (CENTER, ZOOM)
    assert not _fitted(fmap)


def test_legacy_project_without_center_zoom_falls_back_to_bounds() -> None:
    fmap = build_map(_project(RING, legacy=True), MapMode.PROPERTY, mount_view=None)
    (fit,) = _fitted(fmap)
    assert fit.bounds == [(VIEW[0], VIEW[1]), (VIEW[2], VIEW[3])]


def test_property_polygon_tool_only_and_armed_without_boundary() -> None:
    p = _project()
    assert polygon_tool_armed(MapMode.PROPERTY, p)
    fmap = build_map(p, MapMode.PROPERTY, mount_view=None)
    (draw,) = [c for c in _children(fmap) if isinstance(c, Draw)]
    enabled = {k for k, v in draw.draw_options.items() if v is not False}
    assert enabled == {"polygon"}
    assert any(isinstance(c, _ArmPolygon) for c in _children(fmap))
    assert "new L.Draw.Polygon" in fmap.get_root().render()
    assert returned_objects(MapMode.PROPERTY, True) == ["last_active_drawing", *CLICK_OBJECTS]


def test_property_with_boundary_has_no_tool_until_cleared() -> None:
    p = _project(RING)
    assert not polygon_tool_armed(MapMode.PROPERTY, p)
    fmap = build_map(p, MapMode.PROPERTY, mount_view=None)
    assert not any(isinstance(c, (Draw, _ArmPolygon)) for c in _children(fmap))
    assert returned_objects(MapMode.PROPERTY, False) == CLICK_OBJECTS


def test_data_center_only_clicks_and_modules_nothing() -> None:
    assert returned_objects(MapMode.DATA_CENTER, False) == CLICK_OBJECTS  # edits: map editor
    assert returned_objects(MapMode.MODULES, False) == CLICK_OBJECTS
    for mode in (MapMode.DATA_CENTER, MapMode.MODULES):
        fmap = build_map(_project(RING), mode, mount_view=None)
        assert not any(isinstance(c, (Draw, _ArmPolygon)) for c in _children(fmap))


def test_angle_and_length_labels_only_on_property_tab() -> None:
    def markers(mode: MapMode) -> int:
        fg = build_overlay(_project(RING), mode)
        return sum(type(c).__name__ == "Marker" for c in fg._children.values())

    # Every tab: "Property" + "Data center" object labels; Property tab adds 4 angles + 4 sides.
    assert markers(MapMode.PROPERTY) == 2 + 8
    assert markers(MapMode.DATA_CENTER) == 2
    assert markers(MapMode.LOCATION) == 2


def test_parsers() -> None:
    b = {"_southWest": {"lat": 1.0, "lng": 2.0}, "_northEast": {"lat": 3.0, "lng": 4.0}}
    assert parse_bounds(b) == (1.0, 2.0, 3.0, 4.0)
    assert parse_bounds(None) is None
    feature = {"geometry": {"type": "Polygon", "coordinates": [[[2, 1], [4, 1], [4, 3], [2, 1]]]}}
    assert parse_polygon(feature) == ((1.0, 2.0), (1.0, 4.0), (3.0, 4.0))
    assert parse_polygon({"geometry": {"type": "Point", "coordinates": [0, 0]}}) is None


def test_editor_target_by_tab_and_module() -> None:
    from app.components.map_view import EditorTarget, editor_target
    from core.domain.modules import IceStorageParams, ModuleSettings
    from core.site_layout import normalize_layout

    p = _project(RING)
    assert editor_target(p, MapMode.DATA_CENTER, None) == EditorTarget("block", "data_center")
    assert editor_target(p, MapMode.PROPERTY, None) is None
    assert editor_target(Project(), MapMode.DATA_CENTER, None) is None
    # Drawn area: draw tool until it exists, then the vertex editor.
    assert editor_target(p, MapMode.MODULES, "solar_pv") is None
    assert editor_target(_with_pv_area(p), MapMode.MODULES, "solar_pv") == EditorTarget(
        "polygon", "solar_pv"
    )
    # Block module: block editor once enabled (and placed).
    assert editor_target(p, MapMode.MODULES, "ice_storage") is None
    with_ice = normalize_layout(
        p.model_copy(update={"modules": ModuleSettings(ice_storage=IceStorageParams(enabled=True))})
    )
    assert editor_target(with_ice, MapMode.MODULES, "ice_storage") == EditorTarget(
        "block", "ice_storage"
    )


def test_block_colors() -> None:
    from app.components.map_view import BLOCK_OK_COLOR, BLOCK_OUTSIDE_COLOR, block_color
    from app.components.modules import COLORS
    from core.site_layout import BlockIssues

    ok, bad = BlockIssues(False, ()), BlockIssues(False, ("data_center",))
    assert block_color("data_center", {"data_center": ok}) == BLOCK_OK_COLOR
    assert block_color("ice_storage", {"ice_storage": ok}) == COLORS["ice_storage"]
    assert block_color("ice_storage", {"ice_storage": bad}) == BLOCK_OUTSIDE_COLOR
    assert block_color("data_center", {"data_center": BlockIssues(True, ())}) == BLOCK_OUTSIDE_COLOR


def test_parse_polygon_edit() -> None:
    from app.components.footprint_editor import parse_polygon_edit

    ev = {"kind": "polygon", "event_id": "e1", "rings": [[[1, 2], [1, 3], [2, 3]]]}
    assert parse_polygon_edit(ev) == ("e1", [((1.0, 2.0), (1.0, 3.0), (2.0, 3.0))])
    assert parse_polygon_edit({**ev, "kind": "block"}) is None
    assert parse_polygon_edit({**ev, "rings": [[[1, 2], [1, 3]]]}) is None
    assert parse_polygon_edit(None) is None


def test_parse_edit_revalidates_in_python() -> None:
    from app.components.footprint_editor import parse_edit

    area = 10_000.0
    event = {
        "center_lat": 33.45,
        "center_lon": -112.07,
        "width_m": 250.0,
        "length_m": 999.0,  # ignored: Python recomputes length from the sized area
        "rotation_deg": 190.0,
        "event_id": "abc",
    }
    event_id, fp = parse_edit(event, area)  # type: ignore[misc]
    assert event_id == "abc"
    assert fp.area_m2 == pytest.approx(area)
    assert fp.width_m == pytest.approx(250.0)
    assert fp.rotation_deg == pytest.approx(10.0)
    assert parse_edit(None, area) is None
    assert parse_edit({"event_id": "x"}, area) is None
    assert parse_edit({**event, "center_lat": 200}, area) is None


def test_parse_view() -> None:
    out = {
        "bounds": {"_southWest": {"lat": 1.0, "lng": 2.0}, "_northEast": {"lat": 3.0, "lng": 4.0}},
        "center": {"lat": 2.0, "lng": 3.0},
        "zoom": 17,
    }
    assert parse_view(out) == MapView((1.0, 2.0, 3.0, 4.0), (2.0, 3.0), 17.0)
    assert parse_view({**out, "zoom": None}) is None
    assert parse_view({**out, "bounds": None}) is None


@pytest.mark.parametrize("mode", list(MapMode))
def test_black_outline_on_every_tab(mode: MapMode) -> None:
    from app.components.style import MAP_OUTLINE, MAP_OUTLINE_CSS

    html = build_map(_project(RING), mode, mount_view=None).get_root().render()
    assert MAP_OUTLINE_CSS in html and MAP_OUTLINE == "#000000"


def test_editor_outline_matches() -> None:
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "app/components/footprint_editor/frontend"
    assert "var(--map-outline, #000000)" in (frontend / "index.html").read_text()
    assert '"--map-outline", a.colors.outline' in (frontend / "main.js").read_text()


def _with_pv_area(p: Project) -> Project:
    from core.domain.modules import ModuleSettings, SolarPVParams
    from core.domain.site import AreaPolygon

    area = (AreaPolygon(exterior=RING[:3], holes=()),)
    return p.model_copy(
        update={"modules": ModuleSettings(solar_pv=SolarPVParams(enabled=True, area=area))}
    )


def test_modules_tab_polygon_tool_for_selected_module() -> None:
    no_boundary = _project()
    with_boundary = _project(RING)
    assert not polygon_tool_armed(MapMode.MODULES, no_boundary, "solar_pv")  # nothing to snap to
    assert not polygon_tool_armed(MapMode.MODULES, with_boundary, None)  # no module selected
    assert polygon_tool_armed(MapMode.MODULES, with_boundary, "solar_pv")
    assert not polygon_tool_armed(MapMode.MODULES, _with_pv_area(with_boundary), "solar_pv")
    fmap = build_map(with_boundary, MapMode.MODULES, mount_view=None, module="solar_pv")
    assert all(fmap.options[k] is False for k in LOCKS)  # still locked
    (draw,) = [c for c in _children(fmap) if isinstance(c, Draw)]
    assert {k for k, v in draw.draw_options.items() if v is not False} == {"polygon"}
    assert any(isinstance(c, _ArmPolygon) for c in _children(fmap))
    assert returned_objects(MapMode.MODULES, True) == ["last_active_drawing", *CLICK_OBJECTS]


@pytest.mark.parametrize("mode", list(MapMode))
def test_module_areas_drawn_on_every_tab(mode: MapMode) -> None:
    from app.components.modules import COLORS

    fg = build_overlay(_with_pv_area(_project(RING)), mode)
    fills = [
        c.options.get("fillColor") for c in fg._children.values() if type(c).__name__ == "Polygon"
    ]
    assert COLORS["solar_pv"] in fills


# --- labels and click-to-select (D-042) --------------------------------------------


def test_object_labels_upper_left_in_outline_color() -> None:
    from app.components.map_view import BLOCK_OK_COLOR, LABEL_FONT_PX, upper_left
    from app.components.modules import COLORS

    p = _with_pv_area(_project(RING))
    fg = build_overlay(p, MapMode.MODULES)
    html = (
        fg.get_root().render()
        if False
        else "".join(
            c.icon.options.get("html", "") if hasattr(c, "icon") else ""
            for c in fg._children.values()
            if type(c).__name__ == "Marker"
        )
    )
    rendered = [
        (c.location, c.icon.options["html"])
        for c in fg._children.values()
        if type(c).__name__ == "Marker"
    ]
    texts = {h.split(">")[1].split("<")[0]: (loc, h) for loc, h in rendered}
    assert set(texts) == {"Property", "Data center", "Solar PV"}
    assert f"color:{BLOCK_OK_COLOR}" in texts["Data center"][1]
    assert f"color:{COLORS['solar_pv']}" in texts["Solar PV"][1]
    assert all(f"font-size:{LABEL_FONT_PX}px" in h for _, h in rendered) and LABEL_FONT_PX <= 10
    assert html  # labels rendered
    # Upper-left corner of an axis-aligned square = north-west corner.
    sq = [(33.0, -112.0), (33.0, -111.99), (33.01, -111.99), (33.01, -112.0)]
    assert upper_left(sq) == (33.01, -112.0)
    assert tuple(texts["Property"][0]) == upper_left(list(RING))


def test_click_on_object_selects_its_tab() -> None:
    from app import state
    from app.components.map_view import clicked_owner, selection_for

    p = _with_pv_area(_project(RING))
    out = {"last_object_clicked_tooltip": "Solar PV", "last_object_clicked": {"lat": 1, "lng": 2}}
    event_id, owner = clicked_owner(p, out)  # type: ignore[misc]
    assert owner == "solar_pv" and "solar_pv" in event_id
    assert selection_for(owner) == (state.Tab.MODULES, "solar_pv")
    out_dc = {
        "last_object_clicked_tooltip": "Data center",
        "last_object_clicked": {"lat": 1, "lng": 2},
    }
    assert clicked_owner(p, out_dc)[1] == "data_center"  # type: ignore[index]
    assert selection_for("data_center") == (state.Tab.DATA_CENTER, None)
    assert clicked_owner(p, {"last_object_clicked_tooltip": "Nothing"}) is None
    assert clicked_owner(p, {}) is None


def test_parse_select() -> None:
    from app.components.footprint_editor import parse_select

    assert parse_select({"kind": "select", "owner": "ice_storage", "event_id": "e"}) == (
        "e",
        "ice_storage",
    )
    assert parse_select({"kind": "block", "owner": "x", "event_id": "e"}) is None
    assert parse_select(None) is None
