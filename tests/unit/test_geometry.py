import math

import pytest

from core.config.defaults import FOOTPRINT
from core.domain.site import Footprint, LatLon
from core.geometry.boundary import BoundaryError, boundary_metrics, clean_ring, interior_angles_deg
from core.geometry.footprint import (
    align_to_nearest_edge,
    clamp_width,
    edited_footprint,
    footprint_corners,
    footprint_within_boundary,
    normalize_rotation,
    square_footprint,
    with_area,
    with_length,
    with_width,
)
from core.geometry.local_frame import LocalFrame

ORIGIN: LatLon = (33.45, -112.07)


def _ring_from_xy(xy: list[tuple[float, float]]) -> tuple[LatLon, ...]:
    return tuple(LocalFrame(ORIGIN).to_latlon(xy))


RECT_200x100 = _ring_from_xy([(0, 0), (200, 0), (200, 100), (0, 100)])  # metres, CCW


# --- boundary ------------------------------------------------------------------


def test_local_frame_round_trip() -> None:
    f = LocalFrame(ORIGIN)
    pts = [(33.451, -112.071), (33.449, -112.069)]
    back = f.to_latlon(f.to_xy(pts))
    for a, b in zip(pts, back, strict=True):
        assert a == pytest.approx(b, abs=1e-10)


def test_rectangle_metrics() -> None:
    m = boundary_metrics(RECT_200x100)
    assert m.area_m2 == pytest.approx(20_000, rel=1e-6)
    assert m.perimeter_m == pytest.approx(600, rel=1e-6)
    assert m.segment_lengths_m == pytest.approx((200, 100, 200, 100), rel=1e-6)
    assert m.interior_angles_deg == pytest.approx((90, 90, 90, 90), abs=1e-4)
    cx, cy = LocalFrame(ORIGIN).to_xy([m.centroid])[0]
    assert (cx, cy) == pytest.approx((100, 50), abs=1e-3)


@pytest.mark.parametrize("reverse", [False, True], ids=["ccw", "cw"])
def test_l_shape_has_reflex_angle_either_orientation(reverse: bool) -> None:
    xy = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (50.0, 50.0), (50.0, 100.0), (0.0, 100.0)]
    if reverse:
        xy = xy[::-1]
    angles = interior_angles_deg(xy)
    assert sum(angles) == pytest.approx((len(xy) - 2) * 180)
    reflex = xy.index((50.0, 50.0))
    assert angles[reflex] == pytest.approx(270)
    assert all(a == pytest.approx(90) for i, a in enumerate(angles) if i != reflex)


def test_triangle_angles() -> None:
    angles = interior_angles_deg([(0, 0), (1, 0), (0, 1)])
    assert angles == pytest.approx([90, 45, 45])


def test_clean_ring() -> None:
    a, b, c = (1.0, 1.0), (1.0, 2.0), (2.0, 2.0)
    assert clean_ring([a, b, b, c, a]) == (a, b, c)


def test_bowtie_rejected() -> None:
    with pytest.raises(BoundaryError, match="cross"):
        boundary_metrics(_ring_from_xy([(0, 0), (100, 100), (100, 0), (0, 100)]))


def test_too_few_points() -> None:
    with pytest.raises(BoundaryError):
        boundary_metrics(RECT_200x100[:2])


# --- footprint -----------------------------------------------------------------


def _fp_at(x: float, y: float, w: float, length: float, rot: float = 0.0) -> Footprint:
    lat, lon = LocalFrame(ORIGIN).to_latlon([(x, y)])[0]
    return Footprint(center_lat=lat, center_lon=lon, width_m=w, length_m=length, rotation_deg=rot)


def test_square_footprint_area() -> None:
    fp = square_footprint(ORIGIN, 6177.6)
    assert fp.width_m == pytest.approx(fp.length_m)
    assert fp.area_m2 == pytest.approx(6177.6)


def test_with_width_preserves_area() -> None:
    fp = square_footprint(ORIGIN, 10_000)
    wide = with_width(fp, 200, FOOTPRINT)
    assert (wide.width_m, wide.length_m) == pytest.approx((200, 50))
    assert wide.area_m2 == pytest.approx(fp.area_m2)
    assert wide.center == fp.center


def test_width_clamped_to_aspect_limits() -> None:
    area = 10_000.0
    assert clamp_width(1e6, area, FOOTPRINT) == pytest.approx(
        math.sqrt(area / FOOTPRINT.min_aspect)
    )
    assert clamp_width(1e-3, area, FOOTPRINT) == pytest.approx(
        math.sqrt(area / FOOTPRINT.max_aspect)
    )
    fp = with_width(square_footprint(ORIGIN, area), 1e6, FOOTPRINT)
    assert fp.length_m / fp.width_m == pytest.approx(FOOTPRINT.min_aspect)


def test_with_area_keeps_aspect_and_center() -> None:
    fp = with_width(square_footprint(ORIGIN, 10_000), 200, FOOTPRINT)
    bigger = with_area(fp, 40_000)
    assert bigger.area_m2 == pytest.approx(40_000)
    assert bigger.width_m / bigger.length_m == pytest.approx(fp.width_m / fp.length_m)
    assert bigger.center == fp.center


def test_normalize_rotation() -> None:
    assert normalize_rotation(190) == pytest.approx(10)
    assert normalize_rotation(-30) == pytest.approx(150)


def _flat(pts: list[tuple[float, float]]) -> list[float]:
    return [v for p in pts for v in p]


def test_corners_unrotated_and_rotated() -> None:
    f = LocalFrame(ORIGIN)
    fp = _fp_at(0, 0, 40, 20)
    xy = f.to_xy(footprint_corners(fp))
    assert _flat(xy) == pytest.approx(_flat([(-20, 10), (20, 10), (20, -10), (-20, -10)]), abs=1e-3)
    # 90° clockwise: width now runs north–south.
    xy90 = f.to_xy(footprint_corners(fp.model_copy(update={"rotation_deg": 90.0})))
    assert _flat(xy90) == pytest.approx(
        _flat([(10, 20), (10, -20), (-10, -20), (-10, 20)]), abs=1e-3
    )


def test_within_inside() -> None:
    assert footprint_within_boundary(_fp_at(100, 50, 40, 20), RECT_200x100, FOOTPRINT)


def test_within_touching_edge_counts_as_inside() -> None:
    assert footprint_within_boundary(_fp_at(20, 50, 40, 20), RECT_200x100, FOOTPRINT)


def test_within_partially_outside() -> None:
    assert not footprint_within_boundary(_fp_at(190, 50, 40, 20), RECT_200x100, FOOTPRINT)


def test_within_rotated_cases() -> None:
    # 150 × 20 block fits lengthwise along the 200 m side, not rotated 90° in a 100 m depth.
    fp = _fp_at(100, 50, 150, 20)
    assert footprint_within_boundary(fp, RECT_200x100, FOOTPRINT)
    assert not footprint_within_boundary(
        fp.model_copy(update={"rotation_deg": 90.0}), RECT_200x100, FOOTPRINT
    )
    # 45°: half-diagonal extent ≈ (150+20)/2·cos45 ≈ 60 m > 50 m half-depth → outside.
    assert not footprint_within_boundary(
        fp.model_copy(update={"rotation_deg": 45.0}), RECT_200x100, FOOTPRINT
    )


def test_within_no_boundary() -> None:
    assert not footprint_within_boundary(_fp_at(0, 0, 10, 10), (), FOOTPRINT)


def test_with_length_preserves_area() -> None:
    fp = with_length(square_footprint(ORIGIN, 10_000), 200, FOOTPRINT)
    assert (fp.width_m, fp.length_m) == pytest.approx((50, 200))
    assert fp.area_m2 == pytest.approx(10_000)


@pytest.mark.parametrize("edge_deg", [0.0, 25.0, 60.0, 120.0])
def test_align_to_nearest_edge(edge_deg: float) -> None:
    """Parcel rotated by edge_deg; its nearest side is the (rotated) south side."""
    t = math.radians(edge_deg)

    def rot(x: float, y: float) -> tuple[float, float]:  # counter-clockwise by edge_deg
        return (x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t))

    ring = _ring_from_xy([rot(-200, -30), rot(200, -30), rot(200, 300), rot(-200, 300)])
    fp = _fp_at(0, 0, 40, 20, 77.0)
    aligned = align_to_nearest_edge(fp, ring)
    # The south side runs along bearing 90° − edge_deg; width axis bearing = 90° + rotation.
    assert aligned.rotation_deg == pytest.approx((-edge_deg) % 180, abs=1e-6)
    assert (aligned.width_m, aligned.length_m, aligned.center) == (
        fp.width_m,
        fp.length_m,
        fp.center,
    )


def test_edited_footprint_enforces_area_clamp_and_rotation() -> None:
    area = 10_000.0
    fp = edited_footprint(ORIGIN, 120.0, -30.0, area, FOOTPRINT)
    assert fp.area_m2 == pytest.approx(area)
    assert fp.rotation_deg == pytest.approx(150.0)
    wide = edited_footprint(ORIGIN, 1e6, 0.0, area, FOOTPRINT)
    assert wide.length_m / wide.width_m == pytest.approx(FOOTPRINT.min_aspect)
