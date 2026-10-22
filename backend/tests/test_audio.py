import numpy as np
import pytest

from lsg.audio.features import AudioFeatures
from lsg.audio.library import SongLibrary


def test_analysis_finds_tempo_and_beats(demo_analysis):
    _, a = demo_analysis
    assert a.bpm == pytest.approx(120, abs=0.5)
    beats = np.asarray(a.beats)
    # beats sit on the kick grid (0.5 s), not on the off-beat hats
    err = ((beats / 0.5 + 0.5) % 1 - 0.5) * 0.5
    assert np.median(np.abs(err)) < 0.04
    assert len(a.downbeats) >= 6
    assert set(a.features) == {"rms", "low", "mid", "high", "onset"}
    assert all(0 <= v <= 1 for v in a.features["rms"])
    assert a.sections[0].start == 0 and a.sections[-1].end == pytest.approx(a.duration)


def test_features_lookup(demo_analysis):
    _, a = demo_analysis
    f = AudioFeatures(a)
    b = a.beats[5]
    assert f.beat_position(b) == pytest.approx(5)
    assert f.beat_position((a.beats[5] + a.beats[6]) / 2) == pytest.approx(5.5)
    fr = f.frame(b + 0.1)
    assert fr.since_beat == pytest.approx(0.1, abs=1e-6)
    assert 0 <= fr.beat_phase < 1
    assert len(f.recent("beat", b, 1.01)) >= 2


def test_features_without_analysis():
    f = AudioFeatures(None, duration=10)
    fr = f.frame(1.25)
    assert fr.beat == pytest.approx(2.5)  # 120 bpm fallback
    assert fr.low == 0
    assert len(f.recent("beat", 2.0, 1.0)) == 3


def test_library_roundtrip(tmp_path, demo_analysis):
    path, _ = demo_analysis
    lib = SongLibrary(tmp_path)
    song = lib.add_file(path, title="Demo", artist="LSG")
    assert song.duration > 10 and song.status == "pending"
    assert [s.id for s in lib.list()] == [song.id]
    done = lib.analyse(song.id)
    assert done.status == "done"
    assert lib.analysis(song.id).bpm == pytest.approx(120, abs=0.5)
    lib.delete(song.id)
    assert lib.list() == []


def test_library_rejects_bad_files(tmp_path):
    import io

    lib = SongLibrary(tmp_path)
    with pytest.raises(ValueError):
        lib.add(io.BytesIO(b"nope"), "x.txt")
    with pytest.raises(ValueError):
        lib.add(io.BytesIO(b"not audio"), "x.mp3")
    assert lib.list() == []


def test_title_parsing(tmp_path, demo_analysis):
    path, _ = demo_analysis
    lib = SongLibrary(tmp_path)
    with open(path, "rb") as fh:
        s = lib.add(fh, "Daft Punk - One More Time.wav")
    assert (s.artist, s.title) == ("Daft Punk", "One More Time")


def test_sections_match_the_track_structure(tmp_path):
    from lsg.audio.analysis import analyse_file
    from lsg.audio.demo import DEFAULT_STRUCTURE, make_demo_track

    path = tmp_path / "full.wav"
    make_demo_track(path, bpm=124)
    a = analyse_file(path)
    bar = 4 * 60 / 124
    expected, acc = [], 0
    for _, bars, _ in DEFAULT_STRUCTURE[:-1]:
        acc += bars
        expected.append(acc * bar)
    found = [s.start for s in a.sections[1:]]
    assert len(found) == len(expected)
    assert np.allclose(found, expected, atol=0.1)
    assert [s.name for s in a.sections] == ["intro", "verse", "chorus", "break", "chorus", "outro"]
    assert a.sections[2].label == a.sections[4].label  # both choruses sound alike


def test_tempo_correction(demo_analysis):
    from lsg.audio.analysis import scale_tempo

    _, a = demo_analysis
    doubled = scale_tempo(a, 2.0)
    assert doubled.bpm == pytest.approx(2 * a.bpm, rel=0.01)
    assert len(doubled.beats) == 2 * len(a.beats) - 1
    assert np.min(np.abs(np.asarray(doubled.downbeats) - a.downbeats[0])) < 1e-6
    back = scale_tempo(doubled, 0.5)
    assert back.bpm == pytest.approx(a.bpm, rel=0.01)
    assert set(np.round(a.downbeats, 3)) <= set(np.round(back.beats, 3))


def test_exact_bpm_keeps_the_beat_phase(demo_analysis):
    from lsg.audio.analysis import set_bpm

    _, a = demo_analysis
    nudged = set_bpm(a, round(a.bpm, 1) + 0.1)
    assert nudged.bpm == pytest.approx(round(a.bpm, 1) + 0.1)
    gaps = np.diff(nudged.beats)
    assert np.allclose(gaps, 60 / nudged.bpm, atol=0.002)  # even grid
    # still on the detected beats (the demo has a steady tempo)
    near = [np.min(np.abs(np.asarray(nudged.beats) - b)) for b in a.beats[:8]]
    assert max(near) < 0.03
    assert np.min(np.abs(np.asarray(nudged.downbeats) - a.downbeats[0])) < 0.03
    with pytest.raises(ValueError):
        set_bpm(a, 10)


def test_neural_beat_tracker_is_used_when_available(demo_analysis, monkeypatch):
    from lsg.audio import ml_beats
    from lsg.audio.analysis import analyse_file

    path, _ = demo_analysis
    grid = np.arange(0.25, 18.0, 0.5)
    monkeypatch.setattr(ml_beats, "installed", lambda: True)
    monkeypatch.setattr(ml_beats, "track", lambda p: (grid, grid[::4]))
    a = analyse_file(path, "auto")
    assert a.beat_source == "beat_this" and a.beat_note is None
    assert a.beats[:3] == pytest.approx([0.25, 0.75, 1.25]) and a.bpm == pytest.approx(120, abs=0.01)
    assert a.downbeats[1] == pytest.approx(2.25)


def test_neural_beat_tracker_falls_back(demo_analysis, monkeypatch):
    from lsg.audio import ml_beats
    from lsg.audio.analysis import analyse_file

    path, _ = demo_analysis

    def broken(p):
        raise OSError("HTTP Error 503")

    monkeypatch.setattr(ml_beats, "installed", lambda: True)
    monkeypatch.setattr(ml_beats, "track", broken)
    a = analyse_file(path, "beat_this")
    assert a.beat_source == "librosa" and "OSError" in a.beat_note
    assert a.bpm == pytest.approx(120, abs=0.5)
    monkeypatch.setattr(ml_beats, "installed", lambda: False)
    assert "not installed" in analyse_file(path, "beat_this").beat_note
    assert analyse_file(path, "librosa").beat_note is None
