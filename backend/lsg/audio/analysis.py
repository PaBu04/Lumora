"""Offline music analysis: beats, downbeats, onsets, sections and feature curves.

All curves are normalised to 0..1 so effects and the AI can use them without knowing
the loudness of the recording.
"""

import itertools
from pathlib import Path

import librosa
import numpy as np

from lsg.model.song import Analysis, Section

SR = 22050
HOP = 512
FINE_HOP = 128
WAVEFORM_POINTS = 4000
BANDS = {"low": (20, 250), "mid": (250, 2000), "high": (2000, 11000)}


def _normalise(x: np.ndarray, pct: float = 98) -> np.ndarray:
    ref = np.percentile(x, pct) if x.size else 1.0
    return np.clip(x / ref, 0.0, 1.0) if ref > 1e-12 else np.zeros_like(x)


def _round(x, nd: int = 3) -> list[float]:
    return np.round(np.asarray(x, dtype=np.float64), nd).tolist()


def _curve_at(curve: np.ndarray, rate: float, times: np.ndarray) -> np.ndarray:
    return np.interp(times * rate, np.arange(len(curve)), curve, left=0.0, right=0.0)


def _fit_beats(tracked: np.ndarray, pulse: np.ndarray, rate: float, span: tuple[float, float]) -> np.ndarray:
    """Fit a constant-tempo grid to the pulse curve, refining every beat locally.

    librosa's tracker quantises the beat period to whole analysis frames, which makes
    beats drift and jump between on- and off-beat. A fitted grid avoids that; if the
    music has no stable tempo (grid fits clearly worse) the tracked beats are kept.
    """
    if len(tracked) < 8:
        return tracked
    period0 = float(np.polyfit(np.arange(len(tracked)), tracked, 1)[0])
    start, end = span
    best = (-1.0, period0, 0.0)
    for period in period0 * np.linspace(0.97, 1.03, 241):
        phases = np.arange(0.0, period, 0.004)
        n = int((end - start) / period) + 1
        grid = start + phases[:, None] + np.arange(n)[None, :] * period
        scores = _curve_at(pulse, rate, grid).mean(axis=1)
        i = int(np.argmax(scores))
        if scores[i] > best[0]:
            best = (float(scores[i]), period, float(phases[i]))
    score, period, phase = best
    if score < 0.9 * _curve_at(pulse, rate, tracked).mean():
        return tracked

    grid = start + phase + np.arange(int((end - start - phase) / period) + 1) * period
    # nudge each beat to the strongest pulse within +-35 ms
    offsets = np.linspace(-0.035, 0.035, 15)
    cand = grid[:, None] + offsets[None, :]
    vals = _curve_at(pulse, rate, cand) - 0.3 * np.abs(offsets) / 0.035  # prefer staying on the grid
    return grid + offsets[np.argmax(vals, axis=1)]


def double_beats(beats: np.ndarray) -> np.ndarray:
    return np.sort(np.concatenate([beats, beats[:-1] + np.diff(beats) / 2]))


def _octave_correct(beats: np.ndarray, pulse: np.ndarray, rate: float, slow: float = 85.0) -> np.ndarray:
    """Trackers often lock to half the tempo. Below `slow` BPM, take the double tempo when the
    in-between beats are nearly as strong as the beats themselves."""
    if len(beats) < 8:
        return beats
    bpm = 60.0 / float(np.median(np.diff(beats)))
    if bpm >= slow:
        return beats
    doubled = double_beats(beats)
    ratio = _curve_at(pulse, rate, doubled).mean() / (_curve_at(pulse, rate, beats).mean() + 1e-9)
    return doubled if ratio >= 0.8 else beats


def _downbeats(beats: np.ndarray, pulse: np.ndarray, rate: float, low: np.ndarray, beats_per_bar: int = 4) -> np.ndarray:
    """Pick the bar phase whose beats carry the most bass and onset energy."""
    if len(beats) < beats_per_bar:
        return beats[:1]
    strength = _curve_at(pulse, rate, beats) + _curve_at(low, rate, beats)
    scores = [strength[p::beats_per_bar].mean() for p in range(beats_per_bar)]
    return beats[int(np.argmax(scores)) :: beats_per_bar]


def _novelty(features: np.ndarray, kernel: int) -> np.ndarray:
    """Foote novelty: checkerboard kernel slid along the diagonal of the self-similarity matrix."""
    f = features / (np.linalg.norm(features, axis=0, keepdims=True) + 1e-9)
    ssm = f.T @ f
    n = ssm.shape[0]
    half = kernel // 2
    sign = np.sign(np.arange(-half, half) + 0.5)
    k = np.outer(sign, sign) * np.exp(-0.5 * (np.linspace(-2, 2, 2 * half) ** 2))[:, None]
    padded = np.pad(ssm, half, mode="edge")
    return np.array([np.sum(padded[i : i + 2 * half, i : i + 2 * half] * k) for i in range(n)])


def _sections(
    downbeats: np.ndarray,
    duration: float,
    chroma: np.ndarray,
    mfcc: np.ndarray,
    energy: np.ndarray,
    rms: np.ndarray,
    frame_times: np.ndarray,
) -> list[Section]:
    """Segment on bar boundaries, then label by similarity and name by position/energy."""
    bar_frames = librosa.time_to_frames(downbeats, sr=SR, hop_length=HOP)
    bar_frames = bar_frames[bar_frames < chroma.shape[1]]
    if len(bar_frames) < 8:
        return [Section(start=0.0, end=duration, name="verse", label="A", energy=float(rms.mean()))]

    # sync() prepends a segment starting at frame 0: column i starts at seg_starts[i]
    n_frames = chroma.shape[1]
    seg_starts = librosa.util.fix_frames(bar_frames, x_min=0, x_max=n_frames, pad=True)[:-1]
    feats = np.vstack(
        [
            librosa.util.sync(chroma, bar_frames),
            librosa.util.sync(mfcc[1:13], bar_frames) / 50,
            2 * librosa.util.sync(energy, bar_frames),
        ]
    )
    feats = feats - feats.mean(axis=1, keepdims=True)
    nov = _novelty(feats, kernel=8)
    nov = (nov - nov.min()) / (np.ptp(nov) + 1e-9)

    # local novelty peaks at least 4 bars apart, strongest first, roughly one boundary per 15 s
    min_gap = 4
    wanted = max(1, round(duration / 15))
    padded = np.pad(nov, 2, mode="edge")
    peaks = [i for i in range(len(nov)) if nov[i] >= 0.1 and nov[i] == padded[i : i + 5].max()]
    picked: list[int] = []
    for i in sorted(peaks, key=lambda k: -nov[k]):
        if len(picked) >= wanted:
            break
        if i < min_gap or i > len(nov) - min_gap:
            continue
        if all(abs(i - p) >= min_gap for p in picked):
            picked.append(int(i))
    bounds = [0.0, *sorted(float(frame_times[seg_starts[i]]) for i in picked), duration]

    # mean feature vector + energy per section
    vecs, energies = [], []
    for a, b in itertools.pairwise(bounds):
        m = (frame_times >= a) & (frame_times < b)
        sl = np.flatnonzero(m)
        vecs.append(
            np.concatenate([chroma[:, sl].mean(axis=1), mfcc[1:13, sl].mean(axis=1) / 50, 2 * energy[:, sl].mean(axis=1)])
        )
        energies.append(float(rms[sl].mean()) if sl.size else 0.0)

    # greedy clustering by cosine similarity -> letters
    labels: list[str] = []
    reps: list[np.ndarray] = []
    for v in vecs:
        v = v / (np.linalg.norm(v) + 1e-9)
        sims = [float(v @ r) for r in reps]
        if sims and max(sims) > 0.97:
            labels.append(chr(ord("A") + int(np.argmax(sims))))
        else:
            reps.append(v)
            labels.append(chr(ord("A") + len(reps) - 1))

    high = np.percentile(energies, 70) if len(energies) > 2 else max(energies)
    sections = []
    seen_chorus = False
    for i, (a, b) in enumerate(itertools.pairwise(bounds)):
        e = energies[i]
        if i == 0 and e < high and len(bounds) > 3:
            name = "intro"
        elif i == len(bounds) - 2 and e < high and len(bounds) > 3:
            name = "outro"
        elif e >= high:
            name = "chorus"
        elif e < 0.5 * high and 0 < i < len(bounds) - 2:
            name = "break"
        elif seen_chorus and labels.count(labels[i]) == 1 and i < len(bounds) - 2:
            name = "bridge"
        else:
            name = "verse"
        seen_chorus = seen_chorus or name == "chorus"
        sections.append(Section(start=round(a, 3), end=round(b, 3), name=name, label=labels[i], energy=round(e, 3)))
    return sections


def analyse_file(path: Path | str, beat_tracker: str = "librosa") -> Analysis:
    """beat_tracker: "librosa" (built in), "beat_this" (neural model, optional extra) or "auto"."""
    y, _ = librosa.load(path, sr=SR, mono=True)
    note = None
    if beat_tracker in ("beat_this", "auto"):
        from lsg.audio import ml_beats

        if ml_beats.installed():
            try:
                beats, downbeats = ml_beats.track(path)
                if len(beats) >= 8:
                    return analyse_signal(y, beats=beats, downbeats=downbeats, beat_source="beat_this")
                note = "beat_this found too few beats"
            except Exception as exc:
                note = f"beat_this unavailable ({type(exc).__name__}), used built-in tracker"
        elif beat_tracker == "beat_this":
            note = "beat_this is not installed, used built-in tracker"
    result = analyse_signal(y)
    return result.model_copy(update={"beat_note": note}) if note else result


def analyse_signal(
    y: np.ndarray, beats: np.ndarray | None = None, downbeats: np.ndarray | None = None, beat_source: str = "librosa"
) -> Analysis:
    duration = len(y) / SR
    spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    frame_times = librosa.frames_to_time(np.arange(spec.shape[1]), sr=SR, hop_length=HOP)

    rms = _normalise(librosa.feature.rms(S=spec, frame_length=2048, hop_length=HOP)[0])
    bands = {}
    for name, (lo, hi) in BANDS.items():
        sel = (freqs >= lo) & (freqs < hi)
        bands[name] = _normalise(np.log1p(spec[sel].mean(axis=0) * 100))
        # expand the dynamic range a little after log compression
        bands[name] = np.clip((bands[name] - np.percentile(bands[name], 10)) / (1 - np.percentile(bands[name], 10) + 1e-9), 0, 1)

    onset_env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    onset_n = _normalise(onset_env)

    if beats is None:
        _, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=SR, hop_length=HOP, units="frames")
        tracked = frame_times[np.asarray(beat_frames, dtype=int)]

        # fine, bass-weighted onset curve for beat placement
        # (not clipped, so strong kicks keep their weight over hi-hats and off-beat bass)
        full = librosa.onset.onset_strength(y=y, sr=SR, hop_length=FINE_HOP)
        low = librosa.onset.onset_strength(y=y, sr=SR, hop_length=FINE_HOP, fmax=200, n_mels=32)
        full = full / (np.percentile(full, 99) + 1e-9)
        low = low / (np.percentile(low, 99) + 1e-9)
        pulse = full + 1.5 * low
        pulse_rate = SR / FINE_HOP
        active = frame_times[rms > 0.05]
        span = (float(active[0]), float(active[-1])) if active.size else (0.0, duration)
        beats = _fit_beats(tracked, pulse, pulse_rate, span)
        beats = _octave_correct(beats, pulse, pulse_rate)
        downbeats = _downbeats(beats, pulse, pulse_rate, 1.0 * low)
    elif downbeats is None or len(downbeats) == 0:
        downbeats = beats[::4]

    bpm = 60.0 / float(np.polyfit(np.arange(len(beats)), beats, 1)[0]) if len(beats) > 3 else 120.0

    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR, hop_length=HOP, units="frames")
    onsets = frame_times[onset_frames]

    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    n = min(chroma.shape[1], spec.shape[1])
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=spec**2, sr=SR)), n_mfcc=13)
    energy = np.vstack([rms, bands["low"], bands["mid"], bands["high"]])[:, :n]
    sections = _sections(downbeats, duration, chroma[:, :n], mfcc[:, :n], energy, rms[:n], frame_times[:n])

    # peak envelope for the waveform display
    chunks = np.array_split(np.abs(y), min(WAVEFORM_POINTS, max(1, len(y))))
    peaks = np.array([c.max() if c.size else 0.0 for c in chunks])
    peaks = peaks / (peaks.max() + 1e-9)

    return Analysis(
        duration=round(duration, 3),
        bpm=round(bpm, 2),
        beats=_round(beats),
        downbeats=_round(downbeats),
        onsets=_round(onsets),
        sections=sections,
        frame_rate=SR / HOP,
        features={
            "rms": _round(rms),
            "low": _round(bands["low"]),
            "mid": _round(bands["mid"]),
            "high": _round(bands["high"]),
            "onset": _round(onset_n),
        },
        waveform=_round(peaks),
        beat_source=beat_source,
    )


def scale_tempo(analysis: Analysis, factor: float) -> Analysis:
    """Manual tempo correction: factor 2 doubles the beat grid, 0.5 halves it."""
    beats = np.asarray(analysis.beats)
    downbeats = np.asarray(analysis.downbeats)
    if len(beats) < 4 or factor not in (2.0, 0.5):
        raise ValueError("factor must be 2 or 0.5 and the song needs beats")
    if factor == 2.0:
        new_beats = double_beats(beats)
    else:
        # keep the half of the beats that contains the downbeats
        first_db = downbeats[0] if len(downbeats) else beats[0]
        phase = int(np.argmin(np.abs(beats - first_db))) % 2
        new_beats = beats[phase::2]
    start = int(np.argmin(np.abs(new_beats - (downbeats[0] if len(downbeats) else new_beats[0]))))
    start %= 4
    new_downbeats = new_beats[start::4]
    bpm = 60.0 / float(np.polyfit(np.arange(len(new_beats)), new_beats, 1)[0])
    return analysis.model_copy(update={"beats": _round(new_beats), "downbeats": _round(new_downbeats), "bpm": round(bpm, 2)})
