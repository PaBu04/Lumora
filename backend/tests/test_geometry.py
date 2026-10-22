import math

import numpy as np
import pytest

from lsg.geometry.sampling import curve_length, fixture_led_count, sample_fixture
from lsg.geometry.viewer import viewer_relative
from lsg.model.fixture import (
    ArcGeometry,
    BezierGeometry,
    CircleGeometry,
    Fixture,
    MatrixGeometry,
    PolylineGeometry,
)
from lsg.model.viewer import Viewer


def spacing(pos: np.ndarray) -> np.ndarray:
    return np.linalg.norm(np.diff(pos, axis=0), axis=1)


def test_polyline_count_and_spacing_follow_density():
    f = Fixture(geometry=PolylineGeometry(points=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]), leds_per_meter=60)
    pos = sample_fixture(f)
    assert len(pos) == 120
    # LEDs are centred: half a pitch from the start
    np.testing.assert_allclose(pos[0], (1 / 120, 0, 0), atol=1e-9)
    # equal spacing along the path (the LED pair straddling the corner is shorter in a straight line)
    d = spacing(pos)
    assert np.allclose(np.delete(d, 59), 1 / 60)


def test_led_count_overrides_density():
    f = Fixture(geometry=PolylineGeometry(points=[(0, 0, 0), (2, 0, 0)]), led_count=10)
    assert fixture_led_count(f) == 10
    np.testing.assert_allclose(spacing(sample_fixture(f)), 0.2)


def test_reverse_flips_data_order():
    geom = PolylineGeometry(points=[(0, 0, 0), (1, 0, 0)])
    fwd = sample_fixture(Fixture(geometry=geom, led_count=5))
    rev = sample_fixture(Fixture(geometry=geom, led_count=5, reverse=True))
    np.testing.assert_allclose(rev, fwd[::-1])


def test_straight_bezier_matches_line():
    geom = BezierGeometry(points=[(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)])
    assert curve_length(geom) == pytest.approx(3.0)


def test_bezier_quarter_circle_length():
    k = 0.5522847498  # standard cubic approximation of a quarter circle
    geom = BezierGeometry(points=[(1, 0, 0), (1, k, 0), (k, 1, 0), (0, 1, 0)])
    assert curve_length(geom) == pytest.approx(math.pi / 2, rel=1e-3)


def test_bezier_needs_3k_plus_1_points():
    with pytest.raises(ValueError):
        BezierGeometry(points=[(0, 0, 0)] * 5)


def test_arc_points_lie_on_circle():
    geom = ArcGeometry(center=(1, 1, 2), radius=0.5, start_deg=0, sweep_deg=180)
    pos = sample_fixture(Fixture(geometry=geom, led_count=30))
    r = np.linalg.norm(pos - (1, 1, 2), axis=1)
    np.testing.assert_allclose(r, 0.5, atol=1e-4)
    np.testing.assert_allclose(pos[:, 2], 2)
    assert curve_length(geom) == pytest.approx(math.pi * 0.5, rel=1e-4)


def test_circle_is_closed_and_evenly_spaced():
    pos = sample_fixture(Fixture(geometry=CircleGeometry(center=(0, 0, 1), radius=1), led_count=12))
    gaps = np.append(spacing(pos), np.linalg.norm(pos[0] - pos[-1]))
    np.testing.assert_allclose(gaps, gaps[0], rtol=1e-3)


def test_vertical_circle_uses_its_plane():
    geom = CircleGeometry(center=(0, 0, 1), radius=1, normal=(1, 0, 0), reference=(0, 0, 1))
    pos = sample_fixture(Fixture(geometry=geom, led_count=8))
    np.testing.assert_allclose(pos[:, 0], 0, atol=1e-12)
    np.testing.assert_allclose(pos[0], (0, 0, 2))


def test_matrix_serpentine_order():
    geom = MatrixGeometry(origin=(0, 0, 0), col_dir=(1, 0, 0), row_dir=(0, 1, 0), cols=3, rows=2, pitch=1)
    f = Fixture(geometry=geom)
    assert fixture_led_count(f) == 6
    pos = sample_fixture(f)
    expected = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1)]
    np.testing.assert_allclose(pos[:, :2], expected)


def test_matrix_column_major_progressive():
    geom = MatrixGeometry(
        origin=(0, 0, 0),
        col_dir=(1, 0, 0),
        row_dir=(0, 1, 0),
        cols=2,
        rows=2,
        pitch=1,
        serpentine=False,
        column_major=True,
    )
    pos = sample_fixture(Fixture(geometry=geom))
    np.testing.assert_allclose(pos[:, :2], [(0, 0), (0, 1), (1, 0), (1, 1)])


def test_viewer_relative_directions():
    viewer = Viewer(position=(0, 0, 1.6), yaw_deg=0)
    pts = np.array([(5, 0, 1.6), (0, -5, 1.6), (0, 5, 1.6), (5, 0, 6.6), (-5, 0, 1.6)])
    az, el, dist = viewer_relative(pts, viewer)
    np.testing.assert_allclose(az[:3], [0, 90, -90], atol=1e-9)  # ahead, right, left
    assert el[3] == pytest.approx(45)
    assert abs(az[4]) == pytest.approx(180)
    np.testing.assert_allclose(dist[:3], 5)


def test_viewer_yaw_rotates_frame():
    viewer = Viewer(position=(0, 0, 0), yaw_deg=90)  # looking along +y
    az, _, _ = viewer_relative(np.array([(0, 3, 0), (3, 0, 0)]), viewer)
    np.testing.assert_allclose(az, [0, 90], atol=1e-9)  # +x is now on the right
