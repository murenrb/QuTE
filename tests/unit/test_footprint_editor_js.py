"""The browser editor's geometry (frontend/geometry.js) must agree with Python.

Python (core/geometry/footprint.py) is the source of truth and re-validates
every edit; this keeps the live preview honest. Runs geometry.js under Node;
skipped if Node isn't installed.
"""

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from core.config.defaults import FOOTPRINT
from core.domain.site import Footprint, LatLon
from core.geometry.footprint import footprint_corners, footprint_within_boundary
from core.geometry.local_frame import LocalFrame

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY_JS = ROOT / "app/components/footprint_editor/frontend/geometry.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")

ORIGIN: LatLon = (33.45, -112.07)
DEG_PER_CM = 1e-7  # ≈ 1 cm of latitude


def _js(calls: list[dict[str, Any]]) -> list[Any]:
    script = (
        f"const G = require({json.dumps(str(GEOMETRY_JS))});"
        "const calls = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(calls.map(c => G[c.fn](...c.args))));"
    )
    out = subprocess.run(
        [NODE or "node", "-e", script],
        input=json.dumps(calls),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(out.stdout)


def _fp(
    x: float = 0, y: float = 0, w: float = 100, length: float = 50, rot: float = 0
) -> Footprint:
    lat, lon = LocalFrame(ORIGIN).to_latlon([(x, y)])[0]
    return Footprint(center_lat=lat, center_lon=lon, width_m=w, length_m=length, rotation_deg=rot)


def _local(fp_or_pt: Any, origin: LatLon) -> tuple[float, float]:
    return LocalFrame(origin).to_xy([fp_or_pt])[0]


@pytest.mark.parametrize("rot", [0.0, 30.0, 90.0, 137.5])
def test_corners_match_python(rot: float) -> None:
    fp = _fp(12, -7, 120, 40, rot)
    (js,) = _js([{"fn": "corners", "args": [fp.model_dump()]}])
    for (plat, plon), (jlat, jlon) in zip(footprint_corners(fp), js, strict=True):
        assert jlat == pytest.approx(plat, abs=DEG_PER_CM)
        assert jlon == pytest.approx(plon, abs=DEG_PER_CM)


@pytest.mark.parametrize(
    ("edge", "rot"), [("e", 0), ("w", 0), ("n", 0), ("s", 0), ("e", 40), ("n", 125)]
)
def test_resize_edge_keeps_area_and_opposite_edge(edge: str, rot: float) -> None:
    fp = _fp(w=100, length=50, rot=rot)
    # Pull the dragged edge 20 m outward along its own axis.
    local = {"e": (70, 0), "w": (-70, 0), "n": (0, 45), "s": (0, -45)}[edge]
    t = math.radians(rot)
    east = local[0] * math.cos(t) + local[1] * math.sin(t)
    north = -local[0] * math.sin(t) + local[1] * math.cos(t)
    pointer = LocalFrame(fp.center).to_latlon([(east, north)])[0]
    (out,) = _js([{"fn": "resizeEdge", "args": [fp.model_dump(), edge, list(pointer), 0.1, 10]}])
    new = Footprint(**{k: out[k] for k in Footprint.model_fields})
    assert new.area_m2 == pytest.approx(fp.area_m2, rel=1e-12)
    assert new.rotation_deg == fp.rotation_deg
    if edge in "ew":
        assert new.width_m == pytest.approx(120, abs=1e-3)  # opposite edge fixed: 50 + 70 (±1 mm)
    else:
        assert new.length_m == pytest.approx(70, abs=1e-3)  # 25 + 45 (±1 mm)
    # The opposite edge's midpoint did not move.
    opposite = {"e": "w", "w": "e", "n": "s", "s": "n"}[edge]
    before, after = _js(
        [{"fn": "handles", "args": [fp.model_dump(), 0]}, {"fn": "handles", "args": [out, 0]}]
    )
    assert after[opposite] == pytest.approx(before[opposite], abs=DEG_PER_CM)


def test_resize_clamped_to_aspect_limits() -> None:
    fp = _fp(w=100, length=100)
    far = LocalFrame(fp.center).to_latlon([(5000, 0)])[0]
    (out,) = _js([{"fn": "resizeEdge", "args": [fp.model_dump(), "e", list(far), 0.1, 10]}])
    assert out["length_m"] / out["width_m"] == pytest.approx(FOOTPRINT.min_aspect)


def test_rotate_to_pointer_and_snap() -> None:
    fp = _fp()
    pointer = LocalFrame(fp.center).to_latlon(
        [(math.sin(math.radians(37)), math.cos(math.radians(37)))]
    )[0]
    free, snapped, behind = _js(
        [
            {"fn": "rotateTo", "args": [fp.model_dump(), list(pointer), None]},
            {"fn": "rotateTo", "args": [fp.model_dump(), list(pointer), 15]},
            {
                "fn": "rotateTo",
                "args": [
                    fp.model_dump(),
                    list(LocalFrame(fp.center).to_latlon([(0, -1)])[0]),
                    None,
                ],
            },
        ]
    )
    assert free["rotation_deg"] == pytest.approx(37, abs=1e-4)
    assert snapped["rotation_deg"] == pytest.approx(30)
    assert behind["rotation_deg"] == pytest.approx(0)  # 180° ≡ 0° for a rectangle


RECT = tuple(LocalFrame(ORIGIN).to_latlon([(0, 0), (200, 0), (200, 100), (0, 100)]))
L_SHAPE = tuple(
    LocalFrame(ORIGIN).to_latlon([(0, 0), (200, 0), (200, 50), (100, 50), (100, 100), (0, 100)])
)


@pytest.mark.parametrize(
    ("ring", "fp"),
    [
        (RECT, _fp(100, 50, 40, 20)),  # inside
        (RECT, _fp(20, 50, 40, 20)),  # touching the west edge
        (RECT, _fp(190, 50, 40, 20)),  # partly outside
        (RECT, _fp(100, 50, 150, 20, 90)),  # rotated out of the 100 m depth
        (RECT, _fp(100, 50, 150, 20, 45)),  # rotated, corners out
        (L_SHAPE, _fp(120, 60, 80, 60)),  # all corners in? no — notch cuts in
        (L_SHAPE, _fp(50, 50, 60, 60)),  # inside the L's tall arm
    ],
)
def test_inside_boundary_matches_python(ring: tuple[LatLon, ...], fp: Footprint) -> None:
    (js,) = _js(
        [{"fn": "insideBoundary", "args": [fp.model_dump(), [list(p) for p in ring], 0.01]}]
    )
    assert js == footprint_within_boundary(fp, ring, FOOTPRINT)


def test_concave_notch_detected_even_with_corners_inside() -> None:
    # Block spans the L's notch: all 4 corners lie inside the parcel, but the
    # notch corner cuts into the block, so it is NOT inside.
    ring = tuple(
        LocalFrame(ORIGIN).to_latlon(
            [(0, 0), (200, 0), (200, 100), (110, 100), (100, 40), (90, 100), (0, 100)]
        )
    )
    fp = _fp(100, 70, 60, 20)
    (js,) = _js(
        [{"fn": "insideBoundary", "args": [fp.model_dump(), [list(p) for p in ring], 0.01]}]
    )
    assert js is False
    assert footprint_within_boundary(fp, ring, FOOTPRINT) is False


@pytest.mark.parametrize(
    ("b_xy", "rot_b"),
    [
        ((30, 0), 0.0),  # overlapping
        ((50, 0), 0.0),  # touching edge → not an overlap
        ((80, 0), 0.0),  # separated
        ((48, 0), 45.0),  # rotated, corner pokes in
        ((70, 0), 45.0),  # rotated, clear
    ],
)
def test_block_overlap_matches_python(b_xy: tuple[float, float], rot_b: float) -> None:
    """Live red for block-on-block overlap agrees with the Python check (shapely)."""
    from core.config.defaults import SITE_AREAS
    from core.geometry.areas import footprint_polygon, overlap_m2

    a = _fp(0, 0, 50, 50)
    b = _fp(b_xy[0], b_xy[1], 50, 50, rot_b)
    ca, cb = footprint_corners(a), footprint_corners(b)
    (js,) = _js(
        [{"fn": "convexOverlap", "args": [[list(c) for c in ca], [list(c) for c in cb], 0.01]}]
    )
    py = (
        overlap_m2((footprint_polygon(ca),), (footprint_polygon(cb),))
        > SITE_AREAS.overlap_tolerance_m2
    )
    assert js == py
