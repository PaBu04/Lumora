"""Instrument tracks: what each instrument does, as timed events and loudness curves.

Computed from the separated stems (lsg.audio.stems). Event tracks:
  kick, snare, hihat, crash   drum hits with velocity (from the drum stem, so fills and rolls
                              come out as they are played, not on a grid)
  bass                        bass notes: onset, velocity, length, pitch
  vocal                       sung notes / syllables with pitch
  phrase                      sung passages (start, length)
  keys                        every note of the rest (keys, synths, guitars ...), polyphonic: a chord is
                              several events at once (Basic Pitch transcription, lsg.audio.transcribe)
  lead                        the melody of the rest: its top voice (without the transcription model:
                              the strongest note per onset)
  fill                        drum fills and rolls: clearly more drum hits than usual
  build                       build-ups that lead into a drop (rising energy / drum density)
  drop                        moments where the music comes back in hard
  no_drums                    passages without drums
Every event is [time s, strength 0..1, duration s (0 = a hit), pitch (MIDI note, 0 = none)].

Curves (0..1 at the analysis frame rate): drums, bass, vocals, other (stem loudness), density
(drum hits per second relative to the busiest part of the song), tension (rises through
build-ups, back to 0 at the drop) and loudness (smoothed loudness of the whole mix).
"""

import logging

import numpy as np

from lsg.audio.drums import _flux, pick_peaks

log = logging.getLogger(__name__)

TRACKS = (
    "kick", "snare", "hihat", "crash", "bass", "vocal", "phrase", "keys", "lead", "fill", "build", "drop", "no_drums",
)  # fmt: skip
CURVES = ("drums", "bass", "vocals", "other", "density", "tension", "loudness")
STEM_RANGE_DB = 30.0  # a stem this far below its loudest part counts as silent


def _smooth(x: np.ndarray, rate: float, seconds: float) -> np.ndarray:
    w = max(1, round(seconds * rate))
    k = np.hanning(2 * w + 1)
    k /= k.sum()
    return np.convolve(np.pad(x, w, mode="edge"), k, mode="valid")


def _envelope(y: np.ndarray, hop: int, mix_ref_db: float) -> np.ndarray:
    """Stem loudness 0..1 on a dB scale. Referenced to the stem's own loud parts, but never more
    than 20 dB below the mix, so a stem that is (nearly) empty stays near 0."""
    import librosa

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    db = 20 * np.log10(rms + 1e-9)
    ref = max(float(np.percentile(db, 99)), mix_ref_db - 20.0)
    return np.clip((db - (ref - STEM_RANGE_DB)) / STEM_RANGE_DB, 0.0, 1.0).astype(np.float32)


def _events(times, strength, duration=None, pitch=None) -> list[list[float]]:
    n = len(times)
    d = np.zeros(n) if duration is None else duration
    p = np.zeros(n) if pitch is None else pitch
    return [
        [round(float(times[i]), 3), round(float(strength[i]), 2), round(float(d[i]), 3), round(float(p[i]), 1)] for i in range(n)
    ]


def _drum_hits(y: np.ndarray, sr: int, hop: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Kick / snare / hihat / crash with velocity on the isolated drum stem. Without the rest of
    the mix the gaps between hits can be short, so snare rolls and fast hi-hats come through.

    A kick is a rise in the sub band. Snares and claps are told from the click of a kick by
    their noisy tail (1-5 kHz still sounding 50-120 ms later); hi-hats are short top-end hits
    that are not just the click of a kick; a crash is a strong top-end hit that rings on.
    """
    import librosa

    rate = sr / hop
    spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    n = spec.shape[1]

    def level(lo: float, hi: float) -> np.ndarray:
        sel = (freqs >= lo) & (freqs < hi)
        return spec[sel].mean(axis=0) if sel.any() else np.zeros(n)

    def tail(curve: np.ndarray, frames: np.ndarray, a: int, b: int) -> np.ndarray:
        ref = np.percentile(curve, 99) + 1e-12
        return np.array([curve[min(n - 1, f + a) : min(n, f + b)].mean() if f + a < n else 0.0 for f in frames]) / ref

    kick_t, kick_v = pick_peaks(_flux(spec, freqs, 30, 150), rate, 0.09, strength=0.45, velocity=True)
    noise, top = level(1000, 5000), level(7000, 16000)

    onset = librosa.onset.onset_strength(S=librosa.amplitude_to_db(spec, ref=np.max), sr=sr, hop_length=hop)
    cand = pick_peaks(onset, rate, 0.05, strength=0.08)
    frames = np.round(cand * rate).astype(int)
    sn_tail = tail(noise, frames, 2, 5)
    is_snare = sn_tail >= 0.15
    snare_t = cand[is_snare]
    snare_v = np.clip(sn_tail[is_snare] / (np.percentile(sn_tail[is_snare], 90) + 1e-9), 0, 1) if is_snare.any() else snare_t

    hat_t, hat_v = pick_peaks(_flux(spec, freqs, 7000, 20000), rate, 0.05, sensitivity=0.8, strength=0.2, velocity=True)
    if len(hat_t):
        hat_tail = tail(top, np.round(hat_t * rate).astype(int), 2, 5)
        others = np.sort(np.concatenate([kick_t, snare_t]))
        near = np.zeros(len(hat_t), bool)
        if len(others):
            j = np.clip(np.searchsorted(others, hat_t), 1, len(others) - 1)
            near = np.minimum(np.abs(others[j] - hat_t), np.abs(others[j - 1] - hat_t)) < 0.04
        keep = ~near | (hat_tail >= 0.3)
        hat_t, hat_v = hat_t[keep], hat_v[keep]

    crash_t, crash_v = pick_peaks(_flux(spec, freqs, 4000, 20000), rate, 0.8, strength=0.5, velocity=True)
    if len(crash_t):
        f = np.round(crash_t * rate).astype(int)
        peak = np.array([top[i : i + 3].max() if i < n else 0.0 for i in f])
        ring = tail(top, f, round(0.25 * rate), round(0.6 * rate)) * (np.percentile(top, 99) + 1e-12)
        keep = (peak >= np.percentile(top, 90)) & (ring >= 0.5 * peak)
        crash_t, crash_v = crash_t[keep], crash_v[keep]
    return {"kick": (kick_t, kick_v), "snare": (snare_t, snare_v), "hihat": (hat_t, hat_v), "crash": (crash_t, crash_v)}


def _pitched_notes(
    y: np.ndarray,
    sr: int,
    hop: int,
    env: np.ndarray,
    fmin: float,
    min_strength: float,
    min_gap: float,
    active: np.ndarray | None = None,
):
    """Onsets of a pitched stem with velocity (stem loudness), length and pitch (strongest
    CQT note with its harmonics, MIDI)."""
    import librosa

    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, fmin=fmin * 0.9, fmax=min(8000, fmin * 64))
    rate = sr / hop
    times, _ = pick_peaks(onset, rate, min_gap, sensitivity=1.0, strength=0.12, velocity=True)
    if len(times) == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    cqt = np.abs(librosa.cqt(y, sr=sr, hop_length=hop, fmin=fmin, n_bins=60, bins_per_octave=12))
    # harmonic sum: a note's octave and fifth above support it (bass overtones are often loud)
    score = cqt.copy()
    score[:-12] += 0.5 * cqt[12:]
    score[:-19] += 0.3 * cqt[19:]
    midi0 = librosa.hz_to_midi(fmin)
    n = min(len(env), cqt.shape[1])
    frames = np.round(times * rate).astype(int)
    strength, pitch, dur = [], [], []
    for k, f in enumerate(frames):
        a, b = f + 1, min(n, f + 6)
        if a >= b:
            strength.append(0.0)
            pitch.append(0.0)
            dur.append(0.0)
            continue
        peak = float(env[f:b].max())
        strength.append(peak)
        pitch.append(midi0 + float(np.argmax(score[:, a:b].mean(axis=1))))
        # the note lasts until the stem falls clearly below its attack or the next onset
        nxt = frames[k + 1] if k + 1 < len(frames) else n
        end = min(nxt, n, f + round(4 * rate))
        below = np.flatnonzero(env[b:end] < 0.6 * peak)
        dur.append(((b + below[0]) if below.size else end) / rate - times[k])
    s, p, d = np.asarray(strength), np.asarray(pitch), np.asarray(dur)
    keep = s >= min_strength
    if active is not None:
        keep &= active[np.clip(frames, 0, len(active) - 1)]
    return times[keep], s[keep], d[keep], p[keep]


def _regions(mask: np.ndarray, rate: float, min_len: float, max_gap: float) -> list[tuple[float, float]]:
    """Runs of True as (start, end) seconds; gaps shorter than max_gap are bridged."""
    idx = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(np.int8), [0]])))
    runs = [(a / rate, b / rate) for a, b in zip(idx[::2], idx[1::2], strict=True)]
    merged: list[list[float]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= max_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= min_len]


def _phrases(env: np.ndarray, rate: float) -> list[tuple[float, float, float]]:
    """Sung passages: hysteresis on the vocal loudness."""
    on, out = False, np.zeros(len(env), bool)
    for i, v in enumerate(_smooth(env, rate, 0.08)):
        on = v > 0.45 if not on else v > 0.3
        out[i] = on
    return [(a, b, float(env[round(a * rate) : round(b * rate)].mean())) for a, b in _regions(out, rate, 0.5, 0.35)]


def _hit_rate(times: list[np.ndarray], weights: list[float], n: int, rate: float, seconds: float = 1.0) -> np.ndarray:
    x = np.zeros(n, np.float32)
    for ts, w in zip(times, weights, strict=True):
        i = np.round(np.asarray(ts) * rate).astype(int)
        np.add.at(x, i[(i >= 0) & (i < n)], w)
    return _smooth(x, rate, seconds) * rate  # weighted hits per second


def _fills(all_hits: np.ndarray, beats: np.ndarray) -> list[tuple[float, float, float]]:
    """Beats with clearly more drum hits than the song usually has: fills and rolls."""
    if len(beats) < 8 or len(all_hits) == 0:
        return []
    counts = np.histogram(all_hits, bins=beats)[0]
    typical = float(np.median(counts[counts > 0])) if (counts > 0).any() else 0.0
    busy = counts >= max(typical * 1.8, typical + 2, 4)
    out = []
    for a, b in _regions(busy, 1.0, 1.0, 1.0):  # in beat indices
        ia, ib = int(a), int(b)
        rate = counts[ia:ib].mean() / max(typical, 1.0)
        out.append((float(beats[ia]), float(beats[ib] - beats[ia]), float(min(1.0, (rate - 1) / 3))))
    return out


def _drops(
    loud: np.ndarray,
    bass: np.ndarray,
    drums: np.ndarray,
    low: np.ndarray,
    kick_rate: np.ndarray,
    rate: float,
    marks: np.ndarray,
) -> list[tuple[float, float]]:
    """Bar starts where the bottom end comes in hard: bass, kick and low end clearly stronger right
    after than right before (in EDM the build before a drop is often just as loud overall)."""
    w, gap = round(2.0 * rate), round(0.05 * rate)
    level = float(np.percentile(loud, 50))
    beat_kicks = max(float(np.percentile(kick_rate, 95)), 0.5)  # kick rate of a full beat
    found: list[tuple[float, float]] = []
    for t in marks:
        i = round(t * rate)
        if i - w < 0 or i + w > len(loud):
            continue

        def jump(c: np.ndarray, i: int = i) -> float:
            return float(c[i + gap : i + w].mean() - c[i - w : i - gap].mean())

        score = jump(bass) + 0.6 * min(1.0, jump(kick_rate) / beat_kicks) + 0.5 * jump(low)
        if score >= 0.45 and loud[i : i + w].mean() >= level:
            found.append((float(t), float(min(1.0, score / 1.2))))
    # one drop per 8 s, the strongest wins
    found.sort(key=lambda d: -d[1])
    picked: list[tuple[float, float]] = []
    for t, sc in found:
        if all(abs(t - p) >= 8.0 for p, _ in picked):
            picked.append((t, sc))

    # the 2 s windows find the passage; the exact beat is where bass and drums jump most sharply
    short = round(0.45 * rate)

    def sharp(t: float) -> float:
        i = round(t * rate)
        if i - short < 0 or i + short > len(bass):
            return -1.0
        return float(
            bass[i : i + short].mean()
            - bass[i - short : i].mean()
            + 0.5 * (drums[i : i + short].mean() - drums[i - short : i].mean())
        )

    refined = []
    for t, sc in picked:
        near = marks[np.abs(marks - t) <= 1.0]
        refined.append((float(max(near, key=sharp)) if len(near) else t, sc))
    return sorted(refined)


def _build(drop: float, loud: np.ndarray, density: np.ndarray, high: np.ndarray, rate: float, bar: float):
    """Build-up before a drop: the longest stretch (2-8 bars) right before it in which loudness, drum
    density or the treble rise steadily and clearly. The last second before the drop is left out
    (smoothed curves already lean towards the drop there). Returns (start, strength) or None."""
    end = round((drop - 1.0) * rate)
    for bars in (8, 4, 2):
        start = drop - bars * bar
        if start < 0 or bars * bar > 20:
            continue
        a = round(start * rate)
        if end - a < 4 * rate / 2:
            continue
        x = np.linspace(0, 1, end - a)
        rises = []
        for c in (loud, density, high):
            seg = c[a:end]
            q = max(1, len(seg) // 4)
            if seg[-q:].mean() - seg[:q].mean() < 0.12:
                continue
            rises.append(float(np.corrcoef(x, seg)[0, 1]))
        if rises and max(rises) >= 0.6:
            return (start, max(rises))  # longest first
    return None


def _transcribe(y: np.ndarray, sr: int, lo: str, hi: str) -> np.ndarray | None:
    """Polyphonic notes of a stem (rows start, end, pitch, amplitude), or None without the model."""
    import librosa

    from lsg.audio import transcribe

    if not transcribe.installed():
        return None
    try:
        return transcribe.notes(y, sr, min_pitch=int(librosa.note_to_midi(lo)), max_pitch=int(librosa.note_to_midi(hi)))
    except Exception:
        log.exception("note transcription failed")
        return None


def _note_events(notes: np.ndarray, env: np.ndarray, rate: float, min_strength: float) -> np.ndarray:
    """Transcribed notes -> rows [time, strength, duration, pitch]. Strength mixes how loud the stem
    is at the note (quiet passages stay quiet) with how clearly the model heard the note."""
    if len(notes) == 0:
        return np.zeros((0, 4))
    n = len(env)
    i = np.clip(np.round(notes[:, 0] * rate).astype(int), 0, n - 1)
    peak = np.maximum.reduce([env[np.clip(i + k, 0, n - 1)] for k in range(0, 5)])
    amp = notes[:, 3] / (np.percentile(notes[:, 3], 95) + 1e-9)
    strength = np.clip(peak * (0.55 + 0.45 * np.clip(amp, 0, 1)), 0, 1)
    rows = np.column_stack([notes[:, 0], strength, notes[:, 1] - notes[:, 0], notes[:, 2]])
    return rows[strength >= min_strength]


def _melody(keys: np.ndarray, together: float = 0.05) -> np.ndarray:
    """Top voice: the highest note of every group of notes struck together, cut where the next one
    starts. Groups that stay below the middle of the instrument's range are accompaniment."""
    if len(keys) == 0:
        return keys
    mid = float(np.median(keys[:, 3]))
    out: list[np.ndarray] = []
    i = 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and keys[j + 1, 0] - keys[i, 0] <= together:
            j += 1
        group = keys[i : j + 1]
        top = group[np.argmax(group[:, 3])].copy()
        if top[3] >= mid:
            if out and out[-1][0] + out[-1][2] > top[0]:
                out[-1][2] = max(0.03, top[0] - out[-1][0])
            out.append(top)
        i = j + 1
    return np.asarray(out)


def _repitch(t: np.ndarray, p: np.ndarray, notes: np.ndarray | None, keep_octave: bool = False) -> np.ndarray:
    """Take the pitch of each onset from the transcription where it heard a note there. `keep_octave`:
    ignore answers that only move the note by octaves (the CQT finds a bass fundamental more reliably)."""
    if notes is None or len(notes) == 0 or len(t) == 0:
        return p
    out = p.copy()
    starts = notes[:, 0]
    for k, tk in enumerate(t):
        a, b = np.searchsorted(starts, [tk - 0.08, tk + 0.12])
        near = notes[a:b]
        if len(near) == 0:  # a note struck before and still sounding
            sounding = notes[max(0, a - 16) : a]
            near = sounding[sounding[:, 1] > tk + 0.03]
        if len(near):
            pitch = near[np.argmax(near[:, 3]), 2]
            if not (keep_octave and abs(pitch - p[k]) % 12 < 0.5):
                out[k] = pitch
    return out


def _no_drums(drums: np.ndarray, rate: float) -> list[tuple[float, float]]:
    return _regions(_smooth(drums, rate, 0.5) < 0.25, rate, 2.0, 0.5)


def analyse_stems(
    stems: dict[str, np.ndarray],
    y: np.ndarray,
    sr: int,
    hop: int,
    beats: np.ndarray,
    downbeats: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
) -> tuple[dict[str, list[list[float]]], dict[str, np.ndarray]]:
    """Event tracks and curves (see module doc). `low` / `high`: the mix band curves (0..1)."""
    import librosa

    rate = sr / hop
    mix_rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    n = len(mix_rms)
    mix_ref = float(np.percentile(20 * np.log10(mix_rms + 1e-9), 99))

    def fit(c: np.ndarray) -> np.ndarray:
        return np.pad(c[:n], (0, max(0, n - len(c))))

    env = {
        name: fit(_envelope(stems[name], hop, mix_ref)) if name in stems else np.zeros(n, np.float32)
        for name in ("drums", "bass", "vocals", "other")
    }
    tracks: dict[str, list[list[float]]] = {}

    # drums
    hits = _drum_hits(stems["drums"], sr, hop)
    drums_active = _smooth(env["drums"], rate, 0.3) > 0.15
    for k, (t, v) in hits.items():
        i = np.clip(np.round(t * rate).astype(int), 0, n - 1)
        keep = drums_active[i]
        tracks[k] = _events(t[keep], v[keep])

    def times(k: str) -> np.ndarray:
        return np.asarray([e[0] for e in tracks[k]])

    # pitched instruments
    bt, bs, bd, bp = _pitched_notes(stems["bass"], sr, hop, env["bass"], librosa.note_to_hz("E1"), 0.25, 0.08)
    bp = _repitch(bt, bp, _transcribe(stems["bass"], sr, "E1", "G4"), keep_octave=True)
    tracks["bass"] = _events(bt, bs, bd, bp)
    phrases = _phrases(env["vocals"], rate) if "vocals" in stems else []
    tracks["phrase"] = _events([a for a, _, _ in phrases], [s for _, _, s in phrases], [b - a for a, b, _ in phrases])
    if "vocals" in stems:
        sung = np.zeros(n, bool)
        for a, b, _ in phrases:
            sung[round(a * rate) : round(b * rate)] = True
        vt, vs, vd, vp = _pitched_notes(stems["vocals"], sr, hop, env["vocals"], librosa.note_to_hz("E2"), 0.3, 0.1, active=sung)
        vp = _repitch(vt, vp, _transcribe(stems["vocals"], sr, "E2", "C6"))
        tracks["vocal"] = _events(vt, vs, vd, vp)
    else:
        tracks["vocal"] = []
    other = _transcribe(stems["other"], sr, "C2", "C8")
    if other is not None:
        keys = _note_events(other, env["other"], rate, 0.2)
        tracks["keys"] = _events(*keys.T)
        tracks["lead"] = _events(*_melody(keys).T) if len(keys) else []
    else:
        lt, ls, ld, lp = _pitched_notes(stems["other"], sr, hop, env["other"], librosa.note_to_hz("C3"), 0.3, 0.08)
        tracks["lead"] = _events(lt, ls, ld, lp)
        tracks["keys"] = tracks["lead"]

    # structure from the instruments
    kick_rate = _hit_rate([times("kick")], [1.0], n, rate)
    density = _hit_rate([times("kick"), times("snare"), times("hihat")], [1.0, 1.0, 0.5], n, rate)
    density = np.clip(density / (np.percentile(density, 97) + 1e-9), 0, 1).astype(np.float32)
    loud = _smooth(mix_rms, rate, 0.75)
    loud = np.clip(loud / (np.percentile(loud, 95) + 1e-9), 0, 1).astype(np.float32)

    all_hits = np.sort(np.concatenate([times("kick"), times("snare"), times("hihat"), times("crash")]))
    fills = _fills(all_hits, beats)
    tracks["fill"] = _events([f[0] for f in fills], [f[2] for f in fills], [f[1] for f in fills])

    # every beat is a candidate: a wrong bar phase must not move a drop
    marks = beats if len(beats) >= 8 else downbeats
    drops = _drops(loud, env["bass"], env["drums"], fit(low), kick_rate, rate, marks)
    tracks["drop"] = _events([t for t, _ in drops], [s for _, s in drops])
    bar = float(np.median(np.diff(downbeats))) if len(downbeats) > 2 else 2.0
    tension = np.zeros(n, np.float32)
    builds = []
    hi = fit(high)
    for t, _ in drops:
        b = _build(t, loud, density, hi, rate, bar)
        if b:
            start, strength = b
            builds.append((start, strength, t - start))
            a, e = round(start * rate), round(t * rate)
            tension[a:e] = np.maximum(tension[a:e], np.linspace(0, 1, e - a) ** 2)
    tracks["build"] = _events([b[0] for b in builds], [b[1] for b in builds], [b[2] for b in builds])
    nd = _no_drums(env["drums"], rate)
    tracks["no_drums"] = _events([a for a, _ in nd], [1.0] * len(nd), [b - a for a, b in nd])

    curves = {**env, "density": density, "tension": tension, "loudness": loud}
    return tracks, curves
