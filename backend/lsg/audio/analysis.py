"""Offline music analysis: beats, downbeats, onsets, sections, feature curves and - from the
separated instruments - instrument tracks (drum hits, bass / vocal / lead notes, fills,
build-ups, drops; see lsg.audio.instruments).

All curves are normalised to 0..1 so effects and the AI can use them without knowing
the loudness of the recording.
"""

import itertools
from collections.abc import Callable
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


def _meter(beats: np.ndarray, pulse: np.ndarray, rate: float, low: np.ndarray) -> int:
    """3 or 4 beats per bar: the grouping whose strongest beat stands out most clearly."""
    if len(beats) < 24:
        return 4
    strength = _curve_at(pulse, rate, beats) + _curve_at(low, rate, beats)

    def contrast(m: int) -> float:
        scores = np.array([strength[p::m].mean() for p in range(m)])
        return float(scores.max() / (scores.mean() + 1e-9))

    return 3 if contrast(3) > 1.15 * contrast(4) else 4


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


Progress = Callable[[str, float], None]


def analyse_file(
    path: Path | str,
    beat_tracker: str = "librosa",
    stems: str = "auto",
    progress: Progress | None = None,
    keep_tempo: Analysis | None = None,
) -> Analysis:
    """beat_tracker: "librosa" (built in), "beat_this" (neural model, optional extra) or "auto".
    stems: "auto" (Hybrid Demucs when installed, else an approximation), "demucs", "approx" or "off".
    keep_tempo: an earlier analysis whose (hand-corrected) beat grid is kept."""

    def step(stage: str, f: float = 0.0) -> None:
        if progress:
            progress(stage, f)

    step("Audio laden")
    y, _ = librosa.load(path, sr=SR, mono=True)
    notes: list[str] = []
    beats = downbeats = None
    source = "librosa"
    keep = keep_tempo is not None and len(keep_tempo.beats) >= 8
    if keep:
        beats, downbeats = np.asarray(keep_tempo.beats), np.asarray(keep_tempo.downbeats)
        source = keep_tempo.beat_source
    elif beat_tracker in ("beat_this", "auto"):
        from lsg.audio import ml_beats

        if ml_beats.installed():
            step("Beats erkennen", 0.05)
            try:
                b, d = ml_beats.track(path)
                if len(b) >= 8:
                    beats, downbeats, source = b, d, "beat_this"
                else:
                    notes.append("beat_this found too few beats")
            except Exception as exc:
                notes.append(f"beat_this unavailable ({type(exc).__name__}), used built-in tracker")
        elif beat_tracker == "beat_this":
            notes.append("beat_this is not installed, used built-in tracker")

    separated, stem_mode = None, None
    if stems != "off":
        from lsg.audio import stems as stem_sep

        if stems in ("auto", "demucs") and stem_sep.installed():
            step("Instrumente trennen", 0.1)
            try:
                separated = stem_sep.separate(path, SR, lambda f: step("Instrumente trennen", 0.1 + 0.7 * f))
                stem_mode = "demucs"
            except Exception as exc:
                notes.append(f"instrument separation failed ({type(exc).__name__}: {exc}), approximated")
        if separated is None:
            step("Instrumente schätzen", 0.5)
            separated, stem_mode = stem_sep.approximate(y, SR), "approx"

    step("Analysieren", 0.85)
    result = analyse_signal(y, beats=beats, downbeats=downbeats, beat_source=source, stems=separated)
    update: dict = {"stems": stem_mode}
    if keep:
        update |= {"bpm": keep_tempo.bpm, "beats_edited": keep_tempo.beats_edited, "beats_per_bar": keep_tempo.beats_per_bar}
    if notes:
        update["beat_note"] = "; ".join(notes)
    return result.model_copy(update=update)


def _mark_drops(sections: list[Section], tracks: dict, duration: float) -> list[Section]:
    """Strong drops become section boundaries. A drop with a build-up before it gets a "build"
    section leading into it and opens a section called "drop"."""
    drops = [e for e in tracks.get("drop", []) if e[1] >= 0.8]
    if not drops:
        return sections
    builds = {round(b[0] + b[2], 1): b[0] for b in tracks.get("build", [])}
    cuts = {s.start for s in sections}
    names: dict[float, str] = {}
    fixed: set[float] = {0.0}

    def place(t: float, name: str, snap: float) -> None:
        near = [c for c in cuts if c not in fixed and abs(c - t) < snap]
        for c in near:
            cuts.discard(c)
        cuts.add(t)
        fixed.add(t)
        names[t] = name

    for e in drops:
        t = round(e[0], 3)
        b = builds.get(round(e[0], 1))
        place(t, "drop" if b is not None else "", 3.0)
        if b is not None and e[0] - b >= 3.0:
            place(round(b, 3), "build", 2.0)
            for c in [c for c in cuts if b + 0.01 < c < t - 0.01]:  # the build-up is one section
                cuts.discard(c)
    bounds = [*sorted(c for c in cuts if c < duration), duration]
    out = []
    for a, b in itertools.pairwise(bounds):
        if b - a < 0.5:
            continue
        parent = next((s for s in sections if s.start <= a + 0.01 < s.end), sections[-1])
        out.append(Section(start=a, end=b, name=names.get(a) or parent.name, label=parent.label, energy=parent.energy))
    return out


def analyse_signal(
    y: np.ndarray,
    beats: np.ndarray | None = None,
    downbeats: np.ndarray | None = None,
    beat_source: str = "librosa",
    stems: dict[str, np.ndarray] | None = None,
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
        meter = _meter(beats, pulse, pulse_rate, 1.0 * low)
        downbeats = _downbeats(beats, pulse, pulse_rate, 1.0 * low, meter)
    elif downbeats is None or len(downbeats) == 0:
        downbeats = beats[::4]
    beats_per_bar = 4
    if len(downbeats) > 2 and len(beats) > 8:
        per_bar = np.median(np.diff(downbeats)) / np.median(np.diff(beats))
        beats_per_bar = int(min(7, max(2, round(per_bar))))

    bpm = 60.0 / float(np.polyfit(np.arange(len(beats)), beats, 1)[0]) if len(beats) > 3 else 120.0

    tracks: dict[str, list[list[float]]] = {}
    curves: dict[str, np.ndarray] = {}
    if stems is not None:
        from lsg.audio.instruments import analyse_stems

        tracks, curves = analyse_stems(stems, y, SR, HOP, np.asarray(beats), np.asarray(downbeats), bands["low"], bands["high"])
        drum_hits = {k: np.asarray([e[0] for e in tracks.get(k, [])]) for k in ("kick", "snare", "hihat")}
    else:
        from lsg.audio.drums import detect as detect_drums

        drum_hits = detect_drums(spec, freqs, SR / HOP)

    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR, hop_length=HOP, units="frames")
    onsets = frame_times[onset_frames]

    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
    n = min(chroma.shape[1], spec.shape[1])
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(librosa.feature.melspectrogram(S=spec**2, sr=SR)), n_mfcc=13)
    energy = np.vstack([rms, bands["low"], bands["mid"], bands["high"]])[:, :n]
    sections = _sections(downbeats, duration, chroma[:, :n], mfcc[:, :n], energy, rms[:n], frame_times[:n])
    if tracks:
        sections = _mark_drops(sections, tracks, round(duration, 3))

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
            **{k: _round(np.pad(v[: len(rms)], (0, max(0, len(rms) - len(v)))), 2) for k, v in curves.items()},
        },
        waveform=_round(peaks),
        beat_source=beat_source,
        drums={k: _round(v) for k, v in drum_hits.items()},
        version=2 if tracks else 1,
        beats_per_bar=beats_per_bar,
        tracks=tracks,
    )


def set_bpm(analysis: Analysis, bpm: float) -> Analysis:
    """Manual tempo: an even beat grid at exactly `bpm`, aligned to the detected beats.

    The phase is the circular mean of the detected beats on the new grid, the bar start
    the grid beat closest to the first detected downbeat."""
    if not 30.0 <= bpm <= 300.0:
        raise ValueError("bpm must be between 30 and 300")
    beats = np.asarray(analysis.beats, dtype=float)
    period = 60.0 / bpm
    if len(beats):
        ang = 2 * np.pi * (beats % period) / period
        phase = (np.angle(np.mean(np.exp(1j * ang))) % (2 * np.pi)) / (2 * np.pi) * period
    else:
        phase = 0.0
    new_beats = np.arange(phase, analysis.duration, period)
    if len(new_beats) == 0:
        raise ValueError("song too short for this tempo")
    ref = analysis.downbeats[0] if analysis.downbeats else new_beats[0]
    m = analysis.beats_per_bar
    start = int(np.argmin(np.abs(new_beats - ref))) % m
    return analysis.model_copy(
        update={
            "beats": _round(new_beats),
            "downbeats": _round(new_beats[start::m]),
            "bpm": round(float(bpm), 2),
            "beats_edited": True,
        }
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
    m = analysis.beats_per_bar
    start = int(np.argmin(np.abs(new_beats - (downbeats[0] if len(downbeats) else new_beats[0]))))
    start %= m
    new_downbeats = new_beats[start::m]
    bpm = 60.0 / float(np.polyfit(np.arange(len(new_beats)), new_beats, 1)[0])
    return analysis.model_copy(
        update={"beats": _round(new_beats), "downbeats": _round(new_downbeats), "bpm": round(bpm, 2), "beats_edited": True}
    )
