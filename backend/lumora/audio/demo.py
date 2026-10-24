"""Synthesises a small electronic track with a known tempo and structure.

Used for tests and as built-in demo content when no music has been uploaded yet.
"""

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100

# (name, bars, layers)
DEFAULT_STRUCTURE = [
    ("intro", 8, {"hat", "pad"}),
    ("verse", 8, {"kick", "hat", "bass"}),
    ("chorus", 8, {"kick", "hat", "bass", "snare", "lead"}),
    ("break", 4, {"pad"}),
    ("chorus", 8, {"kick", "hat", "bass", "snare", "lead"}),
    ("outro", 4, {"hat", "pad"}),
]


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)


def _kick(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    f = 50 + 120 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.001, 0.18)


def _snare(n: int, rng) -> np.ndarray:
    t = np.arange(n) / SR
    return (0.6 * rng.standard_normal(n) + 0.4 * np.sin(2 * np.pi * 190 * t)) * _env(n, 0.001, 0.09)


def _hat(n: int, rng) -> np.ndarray:
    noise = rng.standard_normal(n)
    noise = np.diff(noise, prepend=0)  # crude high-pass
    return noise * _env(n, 0.0005, 0.03)


def _tone(freq: float, n: int, decay: float, harmonics: int = 3) -> np.ndarray:
    t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, harmonics + 1))
    return s * _env(n, 0.005, decay)


def make_demo_track(path: Path | str, bpm: float = 124.0, structure=None, seed: int = 7) -> float:
    """Write the track to `path` (wav/flac) and return its duration in seconds."""
    structure = structure or DEFAULT_STRUCTURE
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    total_bars = sum(b for _, b, _ in structure)
    total = int((total_bars * 4 * beat + 1.0) * SR)
    out = np.zeros(total)

    def add(sig: np.ndarray, at: float, gain: float) -> None:
        i = int(at * SR)
        j = min(total, i + len(sig))
        if i < total:
            out[i:j] += gain * sig[: j - i]

    bass_notes = [55.0, 55.0, 65.41, 49.0]  # A1 A1 C2 G1 per bar
    lead_notes = [440.0, 523.25, 659.25, 587.33, 523.25, 440.0, 392.0, 440.0]
    pad_chords = [(220.0, 261.63, 329.63), (196.0, 246.94, 293.66)]

    bar_start = 0.0
    for _, bars, layers in structure:
        for b in range(bars):
            t0 = bar_start + b * 4 * beat
            for k in range(4):
                tb = t0 + k * beat
                if "kick" in layers:
                    add(_kick(int(0.4 * SR)), tb, 0.9)
                if "snare" in layers and k in (1, 3):
                    add(_snare(int(0.25 * SR), rng), tb, 0.45)
                if "hat" in layers:
                    add(_hat(int(0.08 * SR), rng), tb + beat / 2, 0.25)
                if "bass" in layers:
                    add(_tone(bass_notes[b % 4], int(beat * SR), 0.25, 4), tb + beat / 2, 0.35)
                if "lead" in layers:
                    for h in range(2):
                        add(_tone(lead_notes[(k * 2 + h) % 8], int(beat / 2 * SR), 0.12), tb + h * beat / 2, 0.12)
            if "pad" in layers:
                chord = pad_chords[b % 2]
                n = int(4 * beat * SR)
                pad = sum(_tone(f, n, 3.0, 2) for f in chord) * np.minimum(1, np.arange(n) / (0.5 * SR))
                add(pad, t0, 0.08)
        bar_start += bars * 4 * beat

    out /= np.max(np.abs(out)) + 1e-9
    out *= 0.9
    sf.write(str(path), np.stack([out, out], axis=1).astype(np.float32), SR)
    return total / SR
