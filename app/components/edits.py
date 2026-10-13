"""Small project edits shared by the tabs and the map handlers."""

from app import state
from core.domain.site import Footprint, LatLon


def set_site(**changes: object) -> None:
    p = state.get_project()
    state.set_project(p.model_copy(update={"site": p.site.model_copy(update=changes)}))


def current_footprint() -> Footprint | None:
    p = state.get_project()
    return p.facilities[0].footprint if p.facilities else None


def set_footprint(fp: Footprint) -> None:
    p = state.get_project()
    if p.facilities:
        dc = p.facilities[0].model_copy(update={"footprint": fp})
        state.set_project(p.model_copy(update={"facilities": (dc, *p.facilities[1:])}))


def move_block(center: LatLon) -> None:
    fp = current_footprint()
    if fp is not None:
        set_footprint(fp.model_copy(update={"center_lat": center[0], "center_lon": center[1]}))
