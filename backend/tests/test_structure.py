"""Song form: section boundaries on phrases, labels for repeated parts, intensity and peak."""

import numpy as np

from lumora.audio import structure
from lumora.model.song import Section


def _presence(parts: list[tuple[int, list[float]]]) -> np.ndarray:
    return np.vstack([np.tile(v, (bars, 1)) for bars, v in parts])


QUIET = [0.0, 0.0, 0.0, 0.5, 0.3, 0.0, 0.2]
VERSE = [0.4, 0.5, 0.8, 0.5, 0.7, 0.5, 0.3]
LOUD = [0.8, 0.8, 0.3, 0.7, 1.0, 0.9, 0.7]


def test_boundaries_follow_the_instrumentation_on_phrases():
    p = _presence([(8, QUIET), (16, VERSE), (8, LOUD), (8, VERSE)])
    chords = np.zeros((len(p), 12))
    assert structure.boundaries(p, chords, {}, phase=0) == [0, 8, 24, 32]
    # a change one bar off the phrase grid still lands on a boundary, but no section is cut in a build-up
    assert structure.boundaries(p, chords, {}, phase=0, blocked=set(range(20, 28))) == [0, 8, 32]


def test_labels_and_rating():
    vecs = [np.array(v) for v in (QUIET, VERSE, LOUD, QUIET, VERSE, LOUD)]
    labels = structure._labels(structure.similarity(vecs))
    assert labels == ["A", "B", "C", "A", "B", "C"]
    rated = structure.rate_sections(
        [Section(start=i, end=i + 1, name="verse", label="A", energy=e) for i, e in enumerate((0.2, 0.5, 0.9, 0.9, 0.3))]
    )
    assert [s.intensity for s in rated] == [1, 3, 5, 5, 2]
    assert [s.peak for s in rated] == [False, False, False, True, False]  # the later of two equal climaxes
