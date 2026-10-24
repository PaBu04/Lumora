"""Flat, vectorised table of every LED in a project - the input for the render engine."""

from dataclasses import dataclass

import numpy as np

from lumora.geometry.sampling import sample_fixture
from lumora.geometry.viewer import viewer_relative, visibility
from lumora.model.project import Project


@dataclass(frozen=True)
class LedTable:
    fixture_ids: list[str]
    fixture_offsets: np.ndarray  # (F + 1,) start of each fixture in the table, last = N
    pos: np.ndarray  # (N, 3) world position in metres
    norm_pos: np.ndarray  # (N, 3) position normalised to the room bounds, 0..1
    fixture_index: np.ndarray  # (N,) index into fixture_ids
    index_in_fixture: np.ndarray  # (N,) data-order index within the fixture
    u: np.ndarray  # (N,) 0..1 along the fixture in data order
    azimuth: np.ndarray  # (N,) degrees, negative = left of the viewer
    elevation: np.ndarray  # (N,) degrees, positive = above eye level
    distance: np.ndarray  # (N,) metres from the viewer
    s: np.ndarray  # (N,) metres along the fixture from its first LED (data order)
    view: np.ndarray  # (N,) 0..1, 1 = in the viewer's field of view, 0 = behind (indirect light)

    @property
    def count(self) -> int:
        return len(self.pos)

    def fixture_slice(self, fixture_id: str) -> slice:
        i = self.fixture_ids.index(fixture_id)
        return slice(int(self.fixture_offsets[i]), int(self.fixture_offsets[i + 1]))


def build_led_table(project: Project) -> LedTable:
    positions = [sample_fixture(f) for f in project.fixtures]
    counts = [len(p) for p in positions]
    offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)

    pos = np.concatenate(positions) if positions else np.zeros((0, 3))
    fixture_index = np.repeat(np.arange(len(counts)), counts).astype(np.int32)
    index_in_fixture = np.concatenate([np.arange(c) for c in counts]).astype(np.int32) if counts else np.zeros(0, np.int32)
    u = np.concatenate([np.arange(c) / max(c - 1, 1) for c in counts]) if counts else np.zeros(0)
    # metres along each fixture: cumulative distance between neighbouring LEDs in data order
    runs = [np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]) for p in positions if len(p)]
    s = np.concatenate(runs) if runs else np.zeros(0)

    lo, hi = (np.asarray(b) for b in project.room.bounds)
    norm_pos = (pos - lo) / np.maximum(hi - lo, 1e-9)

    azimuth, elevation, distance = viewer_relative(pos, project.viewer)
    view = visibility(azimuth, elevation)
    return LedTable(
        fixture_ids=[f.id for f in project.fixtures],
        fixture_offsets=offsets,
        pos=pos.astype(np.float32),
        norm_pos=norm_pos.astype(np.float32),
        fixture_index=fixture_index,
        index_in_fixture=index_in_fixture,
        u=u.astype(np.float32),
        azimuth=azimuth.astype(np.float32),
        elevation=elevation.astype(np.float32),
        distance=distance.astype(np.float32),
        s=s.astype(np.float32),
        view=view,
    )
