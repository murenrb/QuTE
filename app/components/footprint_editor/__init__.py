"""Site map editor: a small custom Streamlit component (D-030, D-041).

Leaflet map locked to the saved view, two modes:
- block: the data center or a scaled-in-inputs module block (drag body = move,
  drag edge = area-locked resize, drag knob = rotate, Shift snaps 15°); red over
  other blocks or outside the boundary.
- polygon: a scaled-in-map module area with a handle at every corner.
The front end (frontend/*.js, plain JS, no build step) sends the edit on
release; it is re-validated here with the Python geometry (source of truth).
"""

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components
import xyzservices.providers as xyz
from pydantic import ValidationError

from core.config.defaults import FOOTPRINT
from core.domain.site import Footprint, Ring
from core.geometry.footprint import edited_footprint
from core.persistence.project import Project

FRONTEND = Path(__file__).parent / "frontend"
_component = components.declare_component("footprint_editor", path=str(FRONTEND))
_TILES = xyz.Esri.WorldGrayCanvas


def map_editor(
    project: Project,
    *,
    mode: str,  # "block" or "polygon"
    target: str,  # owner key: "data_center" or a module key
    view: Any,
    key: str,
    height: int,
    colors: dict[str, str],
    max_native_zoom: int,
    max_zoom: int,
    fallback_zoom: int,
    footprint: Footprint | None = None,  # block mode
    pieces: list[dict[str, Any]] | None = None,  # polygon mode: [{exterior, holes}]
    others: list[dict[str, Any]] | None = None,  # other blocks: [{corners, color}]
    areas: list[dict[str, Any]] | None = None,  # other drawn areas: [{rings, color}]
    label: str = "",  # label of the edited object
    property_label: dict[str, Any] | None = None,  # {text, at}
) -> dict[str, Any] | None:
    """Render the editor; return the raw edit event from the browser (or None)."""
    site = project.site
    fallback = list(site.location) if site.location else [0.0, 0.0]
    value: dict[str, Any] | None = _component(
        mode=mode,
        target=target,
        footprint=footprint.model_dump() if footprint else None,
        pieces=pieces or [],
        others=others or [],
        areas=areas or [],
        boundary=[list(p) for p in site.boundary],
        # Exact center + zoom from the Location tab (D-031); bounds only as a
        # fallback for older projects.
        center=list(view.center) if view else None,
        zoom=view.zoom if view else None,
        view=list(site.map_view) if site.map_view else None,
        fallback_center=list(footprint.center) if footprint else fallback,
        tiles_url=_TILES.build_url(),
        attribution=_TILES.html_attribution,
        max_native_zoom=max_native_zoom,
        max_zoom=max_zoom,
        fallback_zoom=fallback_zoom,
        min_aspect=FOOTPRINT.min_aspect,
        max_aspect=FOOTPRINT.max_aspect,
        edge_tolerance_m=FOOTPRINT.edge_tolerance_m,
        overlap_tolerance_m=FOOTPRINT.edge_tolerance_m,
        colors=colors,
        label=label,
        property_label=property_label,
        label_font_px=10,
        height=height,
        key=key,
        default=None,
    )
    return value


def parse_edit(value: Any, area_m2: float) -> tuple[str, Footprint] | None:
    """Block edit → (event_id, validated footprint) with the area forced to `area_m2`."""
    if not isinstance(value, dict) or "event_id" not in value:
        return None
    if value.get("kind", "block") != "block":
        return None
    try:
        fp = edited_footprint(
            (float(value["center_lat"]), float(value["center_lon"])),
            float(value["width_m"]),
            float(value["rotation_deg"]),
            area_m2,
            FOOTPRINT,
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
    return str(value["event_id"]), fp


def parse_select(value: Any) -> tuple[str, str] | None:
    """Click on another object → (event_id, owner)."""
    if not isinstance(value, dict) or value.get("kind") != "select":
        return None
    owner, event_id = value.get("owner"), value.get("event_id")
    if not isinstance(owner, str) or not isinstance(event_id, str):
        return None
    return event_id, owner


def parse_polygon_edit(value: Any) -> tuple[str, list[Ring]] | None:
    """Vertex edit → (event_id, outlines as lat/lon rings), or None if unusable."""
    if not isinstance(value, dict) or value.get("kind") != "polygon" or "event_id" not in value:
        return None
    try:
        rings = [tuple((float(v[0]), float(v[1])) for v in r) for r in value["rings"]]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not rings or any(len(r) < 3 for r in rings):
        return None
    return str(value["event_id"]), rings
