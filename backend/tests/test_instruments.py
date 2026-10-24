"""Instrument tracks from separated stems, and the effects that follow them."""

import numpy as np
import pytest

from lsg.audio.analysis import analyse_file
from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import build_led_table
from lsg.model.show import Clip, Layer, Show
from lsg.model.song import Analysis, Section
from lsg.render.engine import Renderer, dynamics_gain


def test_demo_tracks(demo_analysis):
    _, a = demo_analysis
    assert a.version == 2 and a.stems == "approx"
    f = AudioFeatures(a)
    kicks = f.tracks["kick"]
    assert len(kicks.times) >= 25 and np.all(np.diff(kicks.times) > 0)
    assert np.all((kicks.strength > 0) & (kicks.strength <= 1))
    # SHORT_STRUCTURE: 2 bars intro without bass, then a bass line on every beat
    bass = f.tracks["bass"]
    assert len(bass.times) >= 15 and bass.times.min() > 3.5
    assert np.all(bass.pitch[bass.pitch > 0] < 60)  # bass notes are low
    lo, hi = f.pitch_range("bass")
    assert lo < hi
    # the drums are silent in the intro
    assert f.level("drums", 1.0) < 0.2 < f.level("drums", 10.0)
    assert f.level("density", 1.0) < f.level("density", 18.0)


def test_drops_and_build_ups(tmp_path):
    from lsg.audio.demo import make_demo_track

    path = tmp_path / "full.wav"
    make_demo_track(path, bpm=124)
    a = analyse_file(path, stems="approx")
    bar = 4 * 60 / 124
    drops = [e[0] for e in a.tracks["drop"] if e[1] >= 0.8]
    # the beat comes in after the intro (8 bars) and after the break (bar 28)
    assert any(abs(d - 8 * bar) < 0.1 for d in drops)
    assert any(abs(d - 28 * bar) < 0.1 for d in drops)
    assert a.tracks["build"] == []  # nothing rises in the demo
    assert any(e[0] < 1 and e[2] > 10 for e in a.tracks["no_drums"])  # intro without drums


def _analysis_with(tracks: dict, duration: float = 20.0) -> Analysis:
    n = int(duration * 10)
    return Analysis(
        version=2,
        duration=duration,
        bpm=120,
        beats=list(np.arange(0, duration, 0.5)),
        downbeats=list(np.arange(0, duration, 2.0)),
        onsets=[],
        sections=[Section(start=0, end=duration, name="verse", label="A", energy=0.5)],
        frame_rate=10.0,
        features={
            **{k: [0.5] * n for k in ("rms", "low", "mid", "high", "onset")},
            "loudness": [0.2] * (n // 2) + [1.0] * (n - n // 2),
        },
        waveform=[0.0],
        tracks=tracks,
    )


def _render(project, clip: Clip, analysis: Analysis, t: float, **show) -> np.ndarray:
    s = Show(name="t", layers=[Layer(clips=[clip])], **show)
    return Renderer(project, build_led_table(project), s, AudioFeatures(analysis)).render(t)


def test_once_is_a_single_cue(project):
    a = _analysis_with({})
    clip = Clip(start=5, end=8, effect="pulse", params={"trigger": "once", "decay": 0.5, "color": "#ffffff"})
    assert _render(project, clip, a, 5.01).max() > 0.95
    assert _render(project, clip, a, 6.5).max() < 0.1  # faded, no second flash
    assert _render(project, clip, a, 4.9).max() == 0


def test_velocity_makes_quiet_hits_dimmer(project):
    a = _analysis_with({"snare": [[2.0, 1.0, 0, 0], [4.0, 0.2, 0, 0]]})
    clip = Clip(start=0, end=10, effect="pulse", params={"trigger": "snare", "decay": 0.3, "velocity": 1.0})
    loud, quiet = _render(project, clip, a, 2.01).max(), _render(project, clip, a, 4.01).max()
    assert loud > 0.9 and quiet < 0.3


def test_sustain_holds_while_the_note_sounds(project):
    a = _analysis_with({"vocal": [[2.0, 1.0, 1.5, 64], [6.0, 1.0, 0.0, 64]]})
    clip = Clip(start=0, end=10, effect="pulse", params={"trigger": "vocal", "decay": 0.2, "sustain": True})
    assert _render(project, clip, a, 3.3).max() > 0.95  # still sounding
    assert _render(project, clip, a, 4.5).max() < 0.05


def test_notes_follow_the_pitch(project):
    a = _analysis_with({"bass": [[1.0, 1.0, 0.5, 40], [3.0, 1.0, 0.5, 52], [5.0, 1.0, 0.5, 64]]})
    table = build_led_table(project)
    north = table.fixture_slice("north")
    clip = Clip(
        start=0, end=10, effect="notes", params={"track": "bass", "axis": "u", "width": 0.1}, target={"fixtures": ["north"]}
    )

    def peak_u(t):
        f = _render(project, clip, a, t)[north].max(axis=1)
        return table.u[north][int(np.argmax(f))]

    low, high = peak_u(1.2), peak_u(5.2)
    assert low < 0.3 and high > 0.7
    assert _render(project, clip, a, 9.0).max() < 0.01


def test_hits_placed_by_pitch(project):
    a = _analysis_with({"lead": [[1.0, 1.0, 0, 40], [3.0, 1.0, 0, 80]]})
    table = build_led_table(project)
    clip = Clip(
        start=0,
        end=10,
        effect="hits",
        params={"trigger": "lead", "place": "pitch", "count": 1, "size": 6},
        target={"fixtures": ["north"]},
    )
    north = table.fixture_slice("north")
    lit_low = np.flatnonzero(_render(project, clip, a, 1.02)[north].max(axis=1) > 0.3)
    lit_high = np.flatnonzero(_render(project, clip, a, 3.02)[north].max(axis=1) > 0.3)
    assert lit_low.size and lit_high.size and lit_low.mean() < lit_high.mean()


def test_rise_builds_up(project):
    a = _analysis_with({})
    clip = Clip(start=2, end=10, effect="rise", params={"flicker": 0.0, "axis": "z"})
    early, late = _render(project, clip, a, 3.0), _render(project, clip, a, 9.9)
    assert early.mean() < 0.1 < late.mean()


def test_sweep_once_crosses_the_room_over_the_clip(project):
    a = _analysis_with({})
    table = build_led_table(project)
    clip = Clip(start=0, end=4, effect="sweep", params={"trigger": "once", "axis": "x", "width": 0.2, "tail": 0})
    xs = table.pos[:, 0]

    def centre(t):
        lv = _render(project, clip, a, t).max(axis=1)
        return float((xs * lv).sum() / lv.sum())

    assert centre(1.0) < centre(2.0) < centre(3.0)


def test_dynamics_darkens_quiet_passages(project):
    a = _analysis_with({})
    clip = Clip(start=0, end=20, effect="solid", params={"color": "#ffffff"})
    quiet, loud = _render(project, clip, a, 5.0, dynamics=0.8), _render(project, clip, a, 15.0, dynamics=0.8)
    assert quiet.max() == pytest.approx(dynamics_gain(0.2, 0.8), abs=0.01) and quiet.max() < 0.3
    assert loud.max() == pytest.approx(1.0)
    assert _render(project, clip, a, 5.0).max() == pytest.approx(1.0)  # off by default


def test_instrument_audio_sources(project):
    a = _analysis_with({})
    a.features["vocals"] = [0.0] * 100 + [1.0] * 100
    clip = Clip(start=0, end=20, effect="solid", params={"brightness": {"audio": "vocals", "min": 0, "max": 1}})
    assert _render(project, clip, a, 5.0).max() == 0
    assert _render(project, clip, a, 15.0).max() == pytest.approx(1.0)


@pytest.mark.ml
def test_demucs_separates_the_demo(demo_analysis):
    from lsg.audio import stems

    if not stems.installed():
        pytest.skip("torch / torchaudio not installed")
    path, _ = demo_analysis
    out = stems.separate(path, 22050)
    assert set(out) == {"drums", "bass", "vocals", "other"}
    rms = {k: float(np.sqrt(np.mean(v**2))) for k, v in out.items()}
    assert rms["drums"] > rms["vocals"] and rms["bass"] > rms["vocals"]


def _tone(midi: float, seconds: float, sr: int = 22050) -> np.ndarray:
    """A piano-ish note: a few harmonics with a decaying envelope."""
    t = np.arange(int(seconds * sr)) / sr
    f = 440.0 * 2 ** ((midi - 69) / 12)
    y = sum(np.sin(2 * np.pi * f * h * t) / h for h in (1, 2, 3, 4))
    return (y * np.exp(-t * 1.5) * np.minimum(1, t / 0.005)).astype(np.float32)


def test_transcription_hears_chords_and_melody():
    from lsg.audio import transcribe
    from lsg.audio.instruments import _melody, _note_events

    if not transcribe.installed():
        pytest.skip("onnxruntime not installed")
    sr = 22050
    y = np.zeros(sr * 5, np.float32)
    y[sr // 2 : sr * 2] += _tone(60, 1.5) + _tone(64, 1.5) + _tone(67, 1.5)  # C major chord
    for k, m in enumerate((72, 74, 76)):  # then a short melody
        a = int((2.5 + 0.6 * k) * sr)
        y[a : a + int(0.5 * sr)] += _tone(m, 0.5)
    notes = transcribe.notes(y / 4, sr)
    first = {int(n[2]) for n in notes if n[0] < 0.8}
    assert {60, 64, 67} <= first, notes
    later = [int(n[2]) for n in notes if n[0] > 2.3 and n[2] >= 70]
    assert later[:3] == [72, 74, 76], notes
    # the melody is the top voice; the chord below the middle of the range is accompaniment
    keys = _note_events(notes, np.ones(1000, np.float32), 200.0, 0.0)
    melody = _melody(keys)
    assert [int(p) for p in melody[:, 3]] == [72, 74, 76]


def test_six_stems_give_piano_and_guitar_tracks():
    from lsg.audio import transcribe
    from lsg.audio.instruments import analyse_stems

    if not transcribe.installed():
        pytest.skip("onnxruntime not installed")
    sr, hop, seconds = 22050, 512, 12
    n = sr * seconds
    rng = np.random.default_rng(3)
    piano = np.zeros(n, np.float32)
    for k, m in enumerate([60, 64, 67, 72] * 5):
        a = int((0.5 + 0.5 * k) * sr)
        piano[a : a + int(0.45 * sr)] += 0.3 * _tone(m, 0.45)
    stems = {
        "drums": (rng.standard_normal(n) * 0.001).astype(np.float32),
        "bass": np.zeros(n, np.float32),
        "vocals": np.zeros(n, np.float32),
        "other": np.zeros(n, np.float32),
        "piano": piano,
        "guitar": np.zeros(n, np.float32),
    }
    mix = sum(stems.values())
    beats = np.arange(0, seconds, 0.5)
    rate = sr / hop
    flat = np.zeros(int(seconds * rate) + 1, np.float32)
    tracks, curves, _ = analyse_stems(stems, mix, sr, hop, beats, beats[::4], flat, flat)
    pitches = {int(e[3]) for e in tracks["piano"]}
    assert {60, 64, 67, 72} <= pitches and tracks["guitar"] == []
    assert len(tracks["keys"]) >= len(tracks["piano"]) - 2  # the piano is still part of the keys
    assert curves["piano"].max() > 0.5 and curves["guitar"].max() == 0
