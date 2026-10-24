"""What an effect sees while rendering: the selected LEDs and the musical moment."""

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np

from lumora.audio.features import AudioFeatures, AudioFrame
from lumora.geometry.led_table import LedTable

AXES = ("x", "y", "z", "u", "s", "azimuth", "elevation", "distance", "radial", "angle", "fixture", "view")


def _norm(v: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return ((v - lo) / (hi - lo)).astype(np.float32) if hi - lo > 1e-9 else np.zeros_like(v, dtype=np.float32)


class Spatial:
    """Normalisation ranges shared by all clips so axes mean the same across fixtures."""

    def __init__(self, table: LedTable, room_center: tuple[float, float]):
        self.table = table
        self.center = np.asarray(room_center, dtype=np.float32)
        empty = table.count == 0

        def rng(a: np.ndarray) -> tuple[float, float]:
            return (0.0, 1.0) if empty else (float(a.min()), float(a.max()))

        self.az = rng(table.azimuth)
        self.el = rng(table.elevation)
        self.dist = rng(table.distance)
        rad = np.linalg.norm(table.pos[:, :2] - self.center, axis=1) if not empty else np.zeros(0)
        self.radial_max = float(rad.max()) if not empty and rad.max() > 0 else 1.0
        self.fixture_count = max(1, len(table.fixture_ids))
        self._proj_cache: dict[tuple, tuple[float, float]] = {}

    def projection_range(self, v: tuple[float, float, float]) -> tuple[float, float]:
        if v not in self._proj_cache:
            p = self.table.pos @ np.asarray(v, dtype=np.float32)
            self._proj_cache[v] = (float(p.min()), float(p.max())) if p.size else (0.0, 1.0)
        return self._proj_cache[v]


class LedView:
    """The subset of LEDs a clip targets. Arrays are aligned with `idx`."""

    def __init__(self, table: LedTable, spatial: Spatial, idx: np.ndarray):
        self.table = table
        self.spatial = spatial
        self.idx = idx
        self.n = len(idx)
        self._coord_cache: dict = {}

    @cached_property
    def pos(self) -> np.ndarray:
        return self.table.pos[self.idx]

    @cached_property
    def norm_pos(self) -> np.ndarray:
        return self.table.norm_pos[self.idx]

    @cached_property
    def u(self) -> np.ndarray:
        return self.table.u[self.idx]

    @cached_property
    def s(self) -> np.ndarray:
        return self.table.s[self.idx]

    @cached_property
    def view(self) -> np.ndarray:
        return self.table.view[self.idx]

    @cached_property
    def azimuth(self) -> np.ndarray:
        return self.table.azimuth[self.idx]

    @cached_property
    def elevation(self) -> np.ndarray:
        return self.table.elevation[self.idx]

    @cached_property
    def distance(self) -> np.ndarray:
        return self.table.distance[self.idx]

    @cached_property
    def fixture_index(self) -> np.ndarray:
        return self.table.fixture_index[self.idx]

    @cached_property
    def index_in_fixture(self) -> np.ndarray:
        return self.table.index_in_fixture[self.idx]

    @property
    def x(self) -> np.ndarray:
        return self.pos[:, 0]

    @property
    def y(self) -> np.ndarray:
        return self.pos[:, 1]

    @property
    def z(self) -> np.ndarray:
        return self.pos[:, 2]

    def coord(self, axis) -> np.ndarray:
        """Normalised 0..1 coordinate along an axis name (prefix '-' to reverse) or a direction vector."""
        key = tuple(axis) if isinstance(axis, (list, tuple, np.ndarray)) else axis
        if key in self._coord_cache:
            return self._coord_cache[key]
        if isinstance(key, tuple):
            v = tuple(float(a) for a in key)
            lo, hi = self.spatial.projection_range(v)
            out = _norm(self.pos @ np.asarray(v, dtype=np.float32), lo, hi)
        elif key.startswith("-"):
            out = 1.0 - self.coord(key[1:])
        else:
            s = self.spatial
            match key:
                case "x":
                    out = self.norm_pos[:, 0]
                case "y":
                    out = self.norm_pos[:, 1]
                case "z":
                    out = self.norm_pos[:, 2]
                case "u":
                    out = self.u
                case "s":  # metres, NOT normalised: repeat / scale / wavelength become "per metre"
                    out = self.s
                case "view":
                    out = self.view
                case "azimuth":
                    out = _norm(self.azimuth, *s.az)
                case "elevation":
                    out = _norm(self.elevation, *s.el)
                case "distance":
                    out = _norm(self.distance, *s.dist)
                case "radial":
                    out = (np.linalg.norm(self.pos[:, :2] - s.center, axis=1) / s.radial_max).astype(np.float32)
                case "angle":
                    d = self.pos[:, :2] - s.center
                    out = ((np.arctan2(d[:, 1], d[:, 0]) / (2 * np.pi)) % 1.0).astype(np.float32)
                case "fixture":
                    out = (self.fixture_index / max(s.fixture_count - 1, 1)).astype(np.float32)
                case _:
                    raise ValueError(f"unknown axis {axis!r}; use one of {AXES} or a vector [x, y, z]")
        self._coord_cache[key] = out
        return out


@dataclass
class RenderContext:
    t: float  # song time in seconds
    lt: float  # time since clip start
    duration: float  # clip length
    leds: LedView
    audio: AudioFrame
    features: AudioFeatures
    seed: int
    viewer_pos: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))

    @property
    def progress(self) -> float:
        return min(max(self.lt / self.duration, 0.0), 1.0) if self.duration > 0 else 0.0

    def cycle(self, speed: float, beats: float) -> float:
        """Animation phase in cycles: beat-locked when `beats` > 0 (one cycle per `beats` beats)."""
        if beats and beats > 0:
            start_beat = self.features.beat_position(self.t - self.lt)
            return (self.audio.beat - start_beat) / beats
        return self.lt * speed
