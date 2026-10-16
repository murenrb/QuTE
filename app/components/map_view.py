"""Site map whose tools are set by the active tab (docs/gui.md → Map, D-027, D-041).

| tab         | pan/zoom | tools                                          | returns           |
|-------------|----------|------------------------------------------------|-------------------|
| location    | free     | none                                           | view              |
| property    | locked   | polygon only, armed if no boundary             | finished polygon  |
| data_center | locked   | block editor: the data center                  | block edit        |
| modules     | locked   | selected module: draw tool (no area yet),      | polygon / edits   |
|             |          | vertex editor (drawn area) or block editor     |                   |

The block and vertex editors are the custom component in
app/components/footprint_editor; otherwise the folium map is used. Drawn areas
and blocks show on every tab in their registry colors; blocks turn red when
they overlap another block or leave the boundary.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import folium
from branca.element import MacroElement
from folium.plugins import Draw
from jinja2 import Template
from streamlit_folium import st_folium

from app import state
from app.components.footprint_editor import (
    map_editor,
    parse_edit,
    parse_polygon_edit,
    parse_select,
)
from app.components.modules import COLORS as MODULE_COLORS
from app.components.modules import LABELS as MODULE_LABELS
from app.components.style import BORDER, INK, MAP_OUTLINE, MAP_OUTLINE_CSS
from core.config.defaults import M_PER_FT
from core.domain.site import AreaPolygon, Bounds, Footprint, LatLon, Ring
from core.geometry.areas import area_m2
from core.geometry.boundary import BoundaryError, boundary_metrics, clean_ring
from core.geometry.footprint import footprint_corners
from core.geometry.local_frame import LocalFrame
from core.persistence.project import Project
from core.site_layout import DATA_CENTER, BlockIssues, block_issues, blocks

TILES = "Esri.WorldGrayCanvas"  # greyscale, no API key (CartoDB now needs one — D-019)
TILES_NATIVE_MAX_ZOOM = 16  # upscaled beyond this
MAX_ZOOM = 20
DEFAULT_CENTER: LatLon = (39.5, -98.35)  # contiguous US
DEFAULT_ZOOM = 4
SITE_ZOOM = 16
MAP_HEIGHT_PX = 700  # inputs panel follows it (was 560; +25 %, owner)
BOUNDARY_COLOR = "#4a4a4a"  # non-facility map data stays grey
BLOCK_OK_COLOR = "#2a78d6"
BLOCK_OUTSIDE_COLOR = "#e34948"
_LABEL_CSS = (
    f"font-size:11px;color:{INK};background:rgba(255,255,255,0.85);border:1px solid {BORDER};"
    "padding:0 3px;white-space:nowrap;transform:translate(-50%,-50%);display:inline-block;"
    "font-family:Arial,Helvetica,sans-serif"
)
_LOCKED = {
    "dragging": False,
    "scrollWheelZoom": False,
    "doubleClickZoom": False,
    "touchZoom": False,
    "boxZoom": False,
    "keyboard": False,
    "zoom_control": False,
}


class MapMode(StrEnum):
    LOCATION = "location"
    PROPERTY = "property"
    DATA_CENTER = "data_center"
    UTILITY = "utility"  # locked, display only
    MODULES = "modules"
    CONTROL = "control"  # locked, display only


@dataclass(frozen=True)
class MapEvents:
    drawn_ring: tuple[LatLon, ...] | None = None  # polygon finished on the Property tab
    # From the map editor: (event id, owner, footprint) / (event id, owner, outlines)
    block_edit: tuple[str, str, Footprint] | None = None
    polygon_edit: tuple[str, str, list[Ring]] | None = None
    select: tuple[str, str] | None = None  # (event id, owner) of a clicked object
    view: "MapView | None" = None  # current view on the Location tab


@dataclass(frozen=True)
class MapView:
    """A map view as the user framed it: exact center + zoom, plus its bounds."""

    bounds: Bounds
    center: LatLon
    zoom: float


def saved_view(project: Project) -> MapView | None:
    site = project.site
    if site.map_view is None or site.map_center is None or site.map_zoom is None:
        return None
    return MapView(site.map_view, site.map_center, site.map_zoom)


class _ArmPolygon(MacroElement):  # type: ignore[misc]
    """Start the Leaflet.Draw polygon tool as soon as the map is ready."""

    _template = Template(
        """
        {% macro script(this, kwargs) %}
        {{ this._parent.get_name() }}.whenReady(function () {
            new L.Draw.Polygon({{ this._parent.get_name() }}, {
                allowIntersection: false, showArea: true,
                shapeOptions: {color: "{{ this.color }}", weight: 2, fillOpacity: 0.05}
            }).enable();
        });
        {% endmacro %}
        """
    )

    def __init__(self, color: str) -> None:
        super().__init__()
        self._name = "ArmPolygon"
        self.color = color


def area_rings(poly: AreaPolygon) -> list[list[LatLon]]:
    """Leaflet polygon rings: exterior first, then holes."""
    return [list(poly.exterior), *[list(h) for h in poly.holes]]


# Clicking a labelled object (block or module area) selects it (D-042).
CLICK_OBJECTS = ["last_object_clicked", "last_object_clicked_tooltip"]
LABEL_FONT_PX = 10
_MAP_LABEL_CSS = (
    "font-size:{px}px;color:{color};font-family:Arial,Helvetica,sans-serif;white-space:nowrap;"
    "text-shadow:0 0 2px #fff,0 0 2px #fff,0 0 2px #fff;transform:translate(3px,2px);"
    "pointer-events:none"
)
PROPERTY_LABEL = "Property"


def returned_objects(mode: MapMode, arm_polygon: bool) -> list[str]:
    if mode is MapMode.LOCATION:
        return ["bounds", "center", "zoom", *CLICK_OBJECTS]
    if mode in (MapMode.PROPERTY, MapMode.MODULES):
        return (["last_active_drawing"] if arm_polygon else []) + CLICK_OBJECTS
    return CLICK_OBJECTS  # block/vertex edits come from the map editor, not folium


def upper_left(points: list[LatLon]) -> LatLon:
    """The point nearest the screen's upper-left (max north − east, local metres)."""
    frame = LocalFrame(points[0])
    xy = frame.to_xy(points)
    i = max(range(len(xy)), key=lambda k: xy[k][1] - xy[k][0])
    return points[i]


def map_label(text: str, color: str) -> folium.DivIcon:
    style = _MAP_LABEL_CSS.format(px=LABEL_FONT_PX, color=color)
    return folium.DivIcon(
        html=f'<div style="{style}">{text}</div>', icon_size=(0, 0), icon_anchor=(0, 0)
    )


def owner_label(project: Project, owner: str) -> str:
    if owner == DATA_CENTER:
        return "Data center"
    return MODULE_LABELS.get(owner, owner)


def selection_for(owner: str) -> "tuple[state.Tab, str | None]":
    """Tab (and module) a click on this object opens."""
    if owner == DATA_CENTER:
        return state.Tab.DATA_CENTER, None
    return state.Tab.MODULES, owner


def polygon_tool_armed(mode: MapMode, project: Project, module: str | None = None) -> bool:
    """Property: until a boundary exists. Modules: the selected sited module has
    no area yet and there is a boundary to snap it to."""
    has_boundary = len(project.site.boundary) >= 3
    if mode is MapMode.PROPERTY:
        return not has_boundary
    if mode is MapMode.MODULES and module is not None:
        params = project.modules.sited().get(module)
        return params is not None and not params.placed and has_boundary
    return False


def build_map(
    project: Project, mode: MapMode, mount_view: MapView | None, module: str | None = None
) -> folium.Map:
    """Base map for a mode. `mount_view` = the view the Location map opens on.

    Locked tabs open at exactly the saved center + zoom (D-031): re-fitting the
    saved bounds could round down a whole zoom level (50 %) if the panel is a
    pixel smaller. Bounds are only fitted for older projects without center/zoom.
    """
    site = project.site
    free = mode is MapMode.LOCATION
    view = mount_view if free else saved_view(project)
    fit = None if view is not None or free else site.map_view
    center = view.center if view else (site.location or DEFAULT_CENTER)
    zoom = view.zoom if view else (SITE_ZOOM if site.location else DEFAULT_ZOOM)
    fmap = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles=None,
        control_scale=True,
        max_zoom=MAX_ZOOM,
        **({} if free else _LOCKED),
    )
    folium.TileLayer(TILES, max_native_zoom=TILES_NATIVE_MAX_ZOOM, max_zoom=MAX_ZOOM).add_to(fmap)
    fmap.get_root().header.add_child(folium.Element(f"<style>{MAP_OUTLINE_CSS}</style>"))
    if fit is not None:
        s, w, n, e = fit
        fmap.fit_bounds([(s, w), (n, e)])
    if polygon_tool_armed(mode, project, module):
        Draw(
            draw_options={
                "polygon": {"allowIntersection": False, "showArea": True},
                "polyline": False,
                "rectangle": False,
                "circle": False,
                "marker": False,
                "circlemarker": False,
            },
            edit_options={"edit": False, "remove": False},
        ).add_to(fmap)
        _ArmPolygon(MODULE_COLORS.get(module or "", BOUNDARY_COLOR)).add_to(fmap)
    return fmap


def _label(text: str) -> folium.DivIcon:
    return folium.DivIcon(html=f'<div style="{_LABEL_CSS}">{text}</div>', icon_size=(0, 0))


def build_overlay(project: Project, mode: MapMode) -> folium.FeatureGroup:
    """Site data drawn on top; changes between reruns without remounting the map."""
    fg = folium.FeatureGroup(name="site")
    site = project.site
    ring = site.boundary
    if len(ring) >= 3:
        folium.Polygon(
            list(ring), color=BOUNDARY_COLOR, weight=2, fill=True, fill_opacity=0.04
        ).add_to(fg)
        folium.Marker(
            upper_left(list(ring)), icon=map_label(PROPERTY_LABEL, BOUNDARY_COLOR)
        ).add_to(fg)
        if mode is MapMode.PROPERTY:
            try:
                m = boundary_metrics(ring)
            except BoundaryError:
                m = None
            if m is not None:
                for vertex, angle in zip(ring, m.interior_angles_deg, strict=True):
                    folium.Marker(vertex, icon=_label(f"{angle:.0f}°")).add_to(fg)
                for mid, length in zip(m.segment_midpoints, m.segment_lengths_m, strict=True):
                    folium.Marker(mid, icon=_label(f"{length / M_PER_FT:,.0f} ft")).add_to(fg)
    if site.location is not None and mode is MapMode.LOCATION:
        folium.CircleMarker(
            site.location, radius=5, color=BOUNDARY_COLOR, fill=True, fill_opacity=1
        ).add_to(fg)

    for key, params in project.modules.sited().items():
        if not params.placed:  # removed from the site: its area is kept, not shown
            continue
        color = MODULE_COLORS.get(key, BOUNDARY_COLOR)
        for poly in params.area:
            folium.Polygon(
                area_rings(poly),
                color=color,
                weight=1.5,
                fill=True,
                fill_color=color,
                fill_opacity=0.3,
                tooltip=owner_label(project, key),
            ).add_to(fg)
        if params.area:
            biggest = max(params.area, key=lambda p: area_m2((p,)))
            label_at = upper_left(list(biggest.exterior))
            folium.Marker(label_at, icon=map_label(owner_label(project, key), color)).add_to(fg)

    issues = block_issues(project)
    for b in blocks(project):
        color = block_color(b.owner, issues)
        corners = footprint_corners(b.footprint)
        folium.Polygon(
            corners,
            color=color,
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.35,
            tooltip=owner_label(project, b.owner),
        ).add_to(fg)
        folium.Marker(
            upper_left(corners), icon=map_label(owner_label(project, b.owner), color)
        ).add_to(fg)
        pv = project.modules.solar_pv
        if b.owner == DATA_CENTER and pv.placed and pv.cover_data_center:
            pv_color = MODULE_COLORS.get("solar_pv", BOUNDARY_COLOR)
            folium.Polygon(  # PV on the roof (D-073): dashed PV outline inside the block
                corners, color=pv_color, weight=2, dash_array="6 4", fill=False
            ).add_to(fg)
    return fg


def clicked_owner(project: Project, out: dict[str, Any]) -> tuple[str, str] | None:
    """(event id, owner) when the user clicked a labelled object on the folium map."""
    tooltip, where = out.get("last_object_clicked_tooltip"), out.get("last_object_clicked")
    if not tooltip or not where:
        return None
    owners = {owner_label(project, b.owner): b.owner for b in blocks(project)}
    owners |= {owner_label(project, k): k for k, p in project.modules.sited().items() if p.placed}
    owner = owners.get(str(tooltip).strip())
    if owner is None:
        return None
    return f"click:{owner}:{where.get('lat')}:{where.get('lng')}", owner


def block_color(owner: str, issues: dict[str, BlockIssues]) -> str:
    """Red when outside the boundary or overlapping another block (warning only)."""
    issue = issues.get(owner)
    if issue is not None and issue.any:
        return BLOCK_OUTSIDE_COLOR
    return BLOCK_OK_COLOR if owner == DATA_CENTER else MODULE_COLORS.get(owner, BLOCK_OK_COLOR)


@dataclass(frozen=True)
class EditorTarget:
    mode: str  # "block" or "polygon"
    owner: str  # "data_center" or a module key


def editor_target(project: Project, mode: MapMode, module: str | None) -> EditorTarget | None:
    """Which object the map editor edits (None → plain folium map) — D-041."""
    if mode is MapMode.DATA_CENTER and project.facilities and project.facilities[0].footprint:
        return EditorTarget("block", DATA_CENTER)
    if mode is MapMode.MODULES and module is not None:
        block = project.modules.blocks().get(module)
        if block is not None and block.placed:
            return EditorTarget("block", module)
        drawn = project.modules.sited().get(module)
        if drawn is not None and drawn.placed:
            return EditorTarget("polygon", module)
    return None


def _render_editor(project: Project, target: EditorTarget, version: int) -> MapEvents:
    issues = block_issues(project)
    all_blocks = blocks(project)
    edited = next((b for b in all_blocks if b.owner == target.owner), None)
    others = []  # other blocks: read-only, labelled, clickable (selects them)
    for b in all_blocks:
        if b.owner == target.owner and target.mode == "block":
            continue
        corners = footprint_corners(b.footprint)
        others.append(
            {
                "corners": [list(c) for c in corners],
                "color": block_color(b.owner, issues),
                "owner": b.owner,
                "label": owner_label(project, b.owner),
                "label_at": list(upper_left(corners)),
            }
        )
    areas = []  # other drawn areas: read-only, labelled (biggest piece), clickable
    for key, params in project.modules.sited().items():
        if key == target.owner or not params.placed:
            continue
        biggest = max(params.area, key=lambda p: area_m2((p,)))
        for poly in params.area:
            areas.append(
                {
                    "rings": area_rings(poly),
                    "color": MODULE_COLORS.get(key, BOUNDARY_COLOR),
                    "owner": key,
                    "label": owner_label(project, key) if poly is biggest else "",
                    "label_at": list(upper_left(list(poly.exterior))),
                }
            )
    edit_color = (
        BLOCK_OK_COLOR
        if target.owner == DATA_CENTER
        else MODULE_COLORS.get(target.owner, BLOCK_OK_COLOR)
    )
    pieces = []
    if target.mode == "polygon":
        pieces = [
            {
                "exterior": [list(v) for v in p.exterior],
                "holes": [[list(v) for v in h] for h in p.holes],
            }
            for p in project.modules.sited()[target.owner].area
        ]
    value = map_editor(
        project,
        mode=target.mode,
        target=target.owner,
        view=saved_view(project),
        key=f"map_editor_{target.mode}_{target.owner}_{version}",
        height=MAP_HEIGHT_PX,
        colors={
            "ok": edit_color,
            "edit": edit_color,
            "outside": BLOCK_OUTSIDE_COLOR,
            "boundary": BOUNDARY_COLOR,
            "outline": MAP_OUTLINE,
        },
        footprint=edited.footprint if edited is not None and target.mode == "block" else None,
        label=owner_label(project, target.owner),
        property_label={"text": PROPERTY_LABEL, "at": list(upper_left(list(project.site.boundary)))}
        if len(project.site.boundary) >= 3
        else None,
        pieces=pieces,
        others=others,
        areas=areas,
        max_native_zoom=TILES_NATIVE_MAX_ZOOM,
        max_zoom=MAX_ZOOM,
        fallback_zoom=SITE_ZOOM,
    )
    selected = parse_select(value)
    if selected is not None:
        return MapEvents(select=selected)
    if target.mode == "block" and edited is not None:
        parsed = parse_edit(value, edited.footprint.area_m2)
        return MapEvents(block_edit=(parsed[0], target.owner, parsed[1]) if parsed else None)
    parsed_poly = parse_polygon_edit(value)
    return MapEvents(
        polygon_edit=(parsed_poly[0], target.owner, parsed_poly[1]) if parsed_poly else None
    )


def render_site_map(project: Project, mode: MapMode, module: str | None = None) -> MapEvents:
    version = state.map_version()
    target = editor_target(project, mode, module)
    if target is not None:
        return _render_editor(project, target, version)

    armed = polygon_tool_armed(mode, project, module)
    mount_view = state.mount_view(version, saved_view(project))
    out: dict[str, Any] | None = st_folium(
        build_map(project, mode, mount_view, module),
        key=f"site_map_{mode}_{module if mode is MapMode.MODULES else ''}_{version}",
        height=MAP_HEIGHT_PX,
        use_container_width=True,
        feature_group_to_add=build_overlay(project, mode),
        returned_objects=returned_objects(mode, armed),
    )
    if not out:
        return MapEvents()
    return MapEvents(
        drawn_ring=parse_polygon(out.get("last_active_drawing")) if armed else None,
        view=parse_view(out) if mode is MapMode.LOCATION else None,
        select=clicked_owner(project, out),
    )


def parse_polygon(feature: Any) -> tuple[LatLon, ...] | None:
    geom = (feature or {}).get("geometry") or {}
    if geom.get("type") != "Polygon" or not geom.get("coordinates"):
        return None
    ring = clean_ring([(float(lat), float(lon)) for lon, lat in geom["coordinates"][0]])
    return ring if len(ring) >= 3 else None


def parse_view(out: dict[str, Any]) -> MapView | None:
    bounds = parse_bounds(out.get("bounds"))
    c, z = out.get("center"), out.get("zoom")
    try:
        center = (float(c["lat"]), float(c["lng"]))  # type: ignore[index]
        zoom = float(z)  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return None
    return MapView(bounds, center, zoom) if bounds is not None else None


def parse_bounds(b: Any) -> Bounds | None:
    try:
        sw, ne = b["_southWest"], b["_northEast"]
        return (float(sw["lat"]), float(sw["lng"]), float(ne["lat"]), float(ne["lng"]))
    except (KeyError, TypeError, ValueError):
        return None
