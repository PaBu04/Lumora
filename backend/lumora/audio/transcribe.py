"""Polyphonic note transcription with Spotify's Basic Pitch model.

The network (ICASSP 2022 "nmp" model, 230 KB, Apache-2.0, see models/NOTICE-basic-pitch) is run
directly with onnxruntime: the basic-pitch package itself pins an old TensorFlow. Windowing and
note decoding follow basic_pitch.inference / basic_pitch.note_creation.

It hears every note that sounds at the same time (chords, a melody over a pad, arpeggios), which
the single strongest CQT bin per onset in lumora.audio.instruments cannot.
"""

import logging
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL = Path(__file__).parent / "models" / "basic_pitch_nmp.onnx"
SR = 22050
HOP = 256  # model frame hop, 86 frames per second
FPS = SR / HOP
WINDOW = SR * 2 - HOP  # samples per model window
OVERLAP_FRAMES = 30
MIDI_OFFSET = 21  # bin 0 = A0
N_PITCHES = 88
_lock = threading.Lock()


def installed() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return MODEL.is_file()


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])


def _frame_times(n: int) -> np.ndarray:
    """Frame index -> seconds, with Basic Pitch's per-window alignment correction."""
    t = np.arange(n) * HOP / SR
    per_window = SR * 2 // HOP
    offset = (HOP / SR) * (per_window - WINDOW / HOP) + 0.0018
    return t - offset * np.floor(np.arange(n) / per_window)


def activations(y: np.ndarray, sr: int, batch: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """Frame and onset activations (frames x 88 pitches, 0..1) for a mono signal."""
    import librosa

    audio = librosa.resample(np.asarray(y, np.float32), orig_sr=sr, target_sr=SR) if sr != SR else np.asarray(y, np.float32)
    length = len(audio)
    overlap = OVERLAP_FRAMES * HOP
    hop = WINDOW - overlap
    audio = np.concatenate([np.zeros(overlap // 2, np.float32), audio])
    starts = range(0, len(audio), hop)
    windows = np.zeros((len(starts), WINDOW, 1), np.float32)
    for k, i in enumerate(starts):
        w = audio[i : i + WINDOW]
        windows[k, : len(w), 0] = w
    session = _session()
    notes, onsets = [], []
    with _lock:  # one inference at a time keeps the CPU free for playback
        for i in range(0, len(windows), batch):
            _contour, note, onset = session.run(
                ["StatefulPartitionedCall:0", "StatefulPartitionedCall:1", "StatefulPartitionedCall:2"],
                {"serving_default_input_2:0": windows[i : i + batch]},
            )
            notes.append(note)
            onsets.append(onset)
    half = OVERLAP_FRAMES // 2
    frames_total = int(np.floor(length * FPS / SR))

    def unwrap(parts: list[np.ndarray]) -> np.ndarray:
        out = np.concatenate(parts)[:, half:-half, :]
        return out.reshape(-1, out.shape[2])[:frames_total]

    return unwrap(notes), unwrap(onsets)


def _inferred_onsets(onsets: np.ndarray, frames: np.ndarray, n_diff: int = 2) -> np.ndarray:
    """Add onsets where a note's frame activation jumps up (re-struck notes the onset head misses)."""
    diffs = []
    for n in range(1, n_diff + 1):
        padded = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(padded[n:] - padded[:-n])
    diff = np.clip(np.min(diffs, axis=0), 0, None)
    diff[:n_diff] = 0
    diff = onsets.max() * diff / (diff.max() + 1e-9)
    return np.maximum(onsets, diff)


def decode(
    frames: np.ndarray,
    onsets: np.ndarray,
    onset_thresh: float = 0.5,
    frame_thresh: float = 0.3,
    min_len: float = 0.12,
    min_pitch: int = 21,
    max_pitch: int = 108,
    energy_tol: int = 11,
) -> np.ndarray:
    """Note events as rows [start s, end s, MIDI pitch, amplitude 0..1], sorted by start.

    Every onset peak above `onset_thresh` starts a note that lasts while its frame activation stays
    above `frame_thresh` (gaps up to `energy_tol` frames bridged)."""
    from scipy.signal import argrelmax

    frames = frames.copy()
    onsets = onsets.copy()
    lo, hi = max(0, min_pitch - MIDI_OFFSET), min(N_PITCHES, max_pitch - MIDI_OFFSET + 1)
    frames[:, :lo] = frames[:, hi:] = 0
    onsets[:, :lo] = onsets[:, hi:] = 0
    onsets = _inferred_onsets(onsets, frames)
    n = len(frames)
    peaks = np.zeros_like(onsets)
    idx = argrelmax(onsets, axis=0)
    peaks[idx] = onsets[idx]
    t_idx, p_idx = np.nonzero(peaks >= onset_thresh)
    order = np.argsort(-t_idx, kind="stable")  # backwards in time: later notes claim their energy first
    remaining = frames.copy()
    min_frames = round(min_len * FPS)
    times = _frame_times(n + 1)
    out = []
    for start, p in zip(t_idx[order], p_idx[order], strict=True):
        if start >= n - 1:
            continue
        i, k = start + 1, 0
        while i < n - 1 and k < energy_tol:
            k = k + 1 if remaining[i, p] < frame_thresh else 0
            i += 1
        i -= k
        if i - start <= min_frames:
            continue
        remaining[start:i, max(0, p - 1) : p + 2] = 0
        out.append((times[start], times[i], p + MIDI_OFFSET, float(frames[start:i, p].mean())))
    if not out:
        return np.zeros((0, 4))
    notes = np.asarray(out, dtype=float)
    return notes[np.argsort(notes[:, 0], kind="stable")]


def drop_overtones(notes: np.ndarray, together: float = 0.06, ratio: float = 0.65) -> np.ndarray:
    """Remove notes that are only an overtone of a louder note struck with them: an octave, twelfth or
    two octaves higher and clearly weaker. Otherwise they would pose as the top voice."""
    if len(notes) < 2:
        return notes
    keep = np.ones(len(notes), bool)
    starts = notes[:, 0]
    for i, (t, _, p, amp) in enumerate(notes):
        a, b = np.searchsorted(starts, [t - together, t + together])
        for j in range(a, b):
            if j != i and round(p - notes[j, 2]) in (12, 19, 24) and amp < ratio * notes[j, 3]:
                keep[i] = False
                break
    return notes[keep]


def notes(y: np.ndarray, sr: int, **kw) -> np.ndarray:
    """Transcribe a (separated) instrument: rows [start s, end s, MIDI pitch, amplitude]."""
    frames, onsets = activations(y, sr)
    return drop_overtones(decode(frames, onsets, **kw))
