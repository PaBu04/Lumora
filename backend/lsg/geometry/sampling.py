"""Turn fixture geometry into LED world positions.

Curves are tessellated into a dense polyline and LEDs are placed at equal arc-length
spacing, centred on the strip: LED i of N sits at s = (i + 0.5) * L / N.
Closed curves (circles) place LED i at s = i * L / N so the ring has no gap.
Positions are returned in data order (index 0 = first LED after the controller).
"""

import math

import numpy as np

from lsg.model.fixture import (
    ArcGeometry,
    BezierGeometry,
    CircleGeometry,
    Fixture,
    MatrixGeometry,
    PolylineGeometry,
)

BEZIER_STEPS_PER_SEGMENT = 256
ARC_STEPS_PER_DEGREE = 2


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("zero-length direction vector")
    return v / n


def _plane_basis(normal, reference) -> tuple[np.ndarray, np.ndarray]:
    """Orthonormal (u, v) spanning the plane perpendicular to `normal`, u along `reference`."""
    n = _unit(normal)
    if reference is None:
        # pick the world axis least aligned with the normal
        reference = np.eye(3)[int(np.argmin(np.abs(n)))]
    r = np.asarray(reference, dtype=np.float64)
    u = r - np.dot(r, n) * n
    u = _unit(u)
    v = np.cross(n, u)
    return u, v


def _bezier_points(geom: BezierGeometry) -> np.ndarray:
    pts = np.asarray(geom.points, dtype=np.float64)
    t = np.linspace(0.0, 1.0, BEZIER_STEPS_PER_SEGMENT + 1)[:, None]
    parts = []
    for k in range(0, len(pts) - 1, 3):
        p0, p1, p2, p3 = pts[k : k + 4]
        seg = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3
        parts.append(seg if not parts else seg[1:])
    return np.concatenate(parts)


def _arc_points(center, radius, normal, reference, start_deg: float, sweep_deg: float) -> np.ndarray:
    u, v = _plane_basis(normal, reference)
    steps = max(8, int(abs(sweep_deg) * ARC_STEPS_PER_DEGREE))
    a = np.radians(start_deg + np.linspace(0.0, sweep_deg, steps + 1))[:, None]
    return np.asarray(center, dtype=np.float64) + radius * (np.cos(a) * u + np.sin(a) * v)


def curve_polyline(geom) -> tuple[np.ndarray, bool]:
    """Dense polyline approximating the geometry and whether it is closed."""
    if isinstance(geom, PolylineGeometry):
        return np.asarray(geom.points, dtype=np.float64), False
    if isinstance(geom, BezierGeometry):
        return _bezier_points(geom), False
    if isinstance(geom, ArcGeometry):
        return _arc_points(geom.center, geom.radius, geom.normal, geom.reference, geom.start_deg, geom.sweep_deg), False
    if isinstance(geom, CircleGeometry):
        return _arc_points(geom.center, geom.radius, geom.normal, geom.reference, geom.start_deg, 360.0), True
    raise TypeError(f"{type(geom).__name__} is not a curve")


def curve_length(geom) -> float:
    pts, _ = curve_polyline(geom)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def _sample_at(pts: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Points at arc lengths `s` along the polyline `pts`."""
    seg_len = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    idx = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(seg_len) - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(seg_len[idx] > 0, (s - cum[idx]) / seg_len[idx], 0.0)
    return pts[idx] + frac[:, None] * (pts[idx + 1] - pts[idx])


def _matrix_points(geom: MatrixGeometry) -> np.ndarray:
    origin = np.asarray(geom.origin, dtype=np.float64)
    cd, rd = _unit(geom.col_dir), _unit(geom.row_dir)
    outer, inner = (geom.cols, geom.rows) if geom.column_major else (geom.rows, geom.cols)
    out = []
    for o in range(outer):
        line = range(inner)
        if geom.serpentine and o % 2 == 1:
            line = reversed(line)
        for i in line:
            r, c = (i, o) if geom.column_major else (o, i)
            out.append(origin + geom.pitch * (c * cd + r * rd))
    return np.asarray(out)


def fixture_led_count(fixture: Fixture) -> int:
    geom = fixture.geometry
    if isinstance(geom, MatrixGeometry):
        return geom.cols * geom.rows
    if fixture.led_count is not None:
        return fixture.led_count
    return max(1, math.floor(curve_length(geom) * fixture.leds_per_meter + 1e-6))


def sample_fixture(fixture: Fixture) -> np.ndarray:
    """LED positions (N, 3) in data order."""
    geom = fixture.geometry
    if isinstance(geom, MatrixGeometry):
        pos = _matrix_points(geom)
    else:
        pts, closed = curve_polyline(geom)
        length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        n = fixture_led_count(fixture)
        step = length / n
        s = np.arange(n) * step if closed else (np.arange(n) + 0.5) * step
        pos = _sample_at(pts, s)
    return pos[::-1].copy() if fixture.reverse else pos
