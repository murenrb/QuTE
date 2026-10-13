"""Site and facility footprint (docs/data-model.md → Site, DataCenter.footprint)."""

from pydantic import BaseModel, ConfigDict, Field

# (lat, lon) in degrees, WGS84.
LatLon = tuple[float, float]
# (south, west, north, east) in degrees.
Bounds = tuple[float, float, float, float]


class Footprint(BaseModel):
    """Rectangular facility block on the map.

    `width_m` runs east–west and `length_m` north–south at `rotation_deg` = 0;
    rotation is clockwise (compass sense). Area = width × length.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)
    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    rotation_deg: float = Field(default=0.0, ge=0, lt=180)

    @property
    def area_m2(self) -> float:
        return self.width_m * self.length_m

    @property
    def center(self) -> LatLon:
        return (self.center_lat, self.center_lon)


Ring = tuple[LatLon, ...]  # open ring: first vertex not repeated


class AreaPolygon(BaseModel):
    """One polygon of a module's area: outer ring plus optional holes (lat, lon)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exterior: Ring
    holes: tuple[Ring, ...] = ()


# A module's area: one or more polygons (snapping can split a drawn shape).
Area = tuple[AreaPolygon, ...]


class Site(BaseModel):
    """Location and property boundary. One contiguous polygon only (D-011)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="Untitled site", min_length=1)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    address: str = ""
    # Open ring of vertices (first vertex not repeated); empty = not drawn yet.
    boundary: tuple[LatLon, ...] = ()
    weather_ref: str | None = None  # weather cache key of the last run
    # View framed on the Location tab (D-027). Locked tabs reopen at exactly
    # map_center + map_zoom (D-031); map_view (bounds) is kept for checks and as
    # a fallback for projects saved before center/zoom were stored.
    map_view: Bounds | None = None
    map_center: LatLon | None = None
    map_zoom: float | None = Field(default=None, ge=0, le=24)

    @property
    def location(self) -> LatLon | None:
        if self.lat is None or self.lon is None:
            return None
        return (self.lat, self.lon)
