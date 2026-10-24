"""Sync test: a click track plus LED flashes on every beat, to tune audio and controller latency.

The user stands at the viewer position and shifts the latencies until click and flash
coincide. Beats are known exactly, so no audio analysis is involved.
"""

from pathlib import Path

import numpy as np
import soundfile as sf

from lumora.audio.features import AudioFeatures
from lumora.model.show import Clip, Layer, Show
from lumora.model.song import Analysis, Section

SR = 44100
SYNC_SHOW_ID = "__sync__"


def click_track(path: Path, bpm: float = 100.0, seconds: float = 60.0) -> Path:
    """Short clicks on every beat (accent on the bar), written once and reused."""
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * SR)
    out = np.zeros(n, np.float32)
    period = 60.0 / bpm
    length = int(0.03 * SR)
    t = np.arange(length) / SR
    env = np.exp(-t / 0.006)
    for k, beat in enumerate(np.arange(0.0, seconds - 0.1, period)):
        freq = 1760.0 if k % 4 == 0 else 1100.0
        i = int(beat * SR)
        out[i : i + length] += (0.9 * np.sin(2 * np.pi * freq * t) * env)[: n - i]
    sf.write(str(path), np.stack([out, out], axis=1), SR)
    return path


def sync_features(bpm: float, seconds: float) -> AudioFeatures:
    beats = np.arange(0.0, seconds - 0.1, 60.0 / bpm)
    analysis = Analysis(
        duration=seconds,
        bpm=bpm,
        beats=beats.round(4).tolist(),
        downbeats=beats[::4].round(4).tolist(),
        onsets=beats.round(4).tolist(),
        sections=[Section(start=0.0, end=seconds, name="verse", label="A", energy=0.5)],
        frame_rate=10.0,
        features={k: [0.5] * int(seconds * 10) for k in ("rms", "low", "mid", "high", "onset")},
        waveform=[0.0],
    )
    return AudioFeatures(analysis)


def sync_show(seconds: float) -> Show:
    return Show(
        id=SYNC_SHOW_ID,
        name="Sync-Test",
        duration=seconds,
        layers=[
            Layer(
                name="Flash",
                clips=[
                    Clip(
                        start=0,
                        end=seconds,
                        effect="pulse",
                        params={"color": "#ffffff", "trigger": "beat", "decay": 0.05, "brightness": 0.8},
                    ),
                    Clip(
                        start=0,
                        end=seconds,
                        effect="pulse",
                        blend="add",
                        params={"color": "#ff0060", "trigger": "bar", "decay": 0.08, "brightness": 0.6},
                    ),
                ],
            )
        ],
    )
