"""Local metric coordinates around a point (docs/gui.md → Map implementation).

Azimuthal equidistant projection centred on the site: metres, +x east, +y
true north, negligible distortion over a site-sized area (D-018).
"""

from collections.abc import Sequence

from pyproj import Transformer

from core.domain.site import LatLon

XY = tuple[float, float]


class LocalFrame:
    def __init__(self, origin: LatLon) -> None:
        lat0, lon0 = origin
        crs = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs"
        self._fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        self._inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def to_xy(self, points: Sequence[LatLon]) -> list[XY]:
        return [self._fwd.transform(lon, lat) for lat, lon in points]

    def to_latlon(self, points: Sequence[XY]) -> list[LatLon]:
        out = []
        for x, y in points:
            lon, lat = self._inv.transform(x, y)
            out.append((lat, lon))
        return out
