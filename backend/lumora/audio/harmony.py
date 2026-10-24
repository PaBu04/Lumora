"""Harmony and sound character from the transcribed notes.

harmony(): the key of the song (Krumhansl-Kessler profiles) and its chords beat by beat (triad
templates, smoothed so chords change rarely and preferably on a bar line), each with its degree in
the key (I, IV, V, vi ...).

character(): what kind of part the keys / synths play - stabs (short chords struck together),
pads (held chords) and arpeggios (an even run of single notes) - as region tracks.

Notes are rows [time s, strength 0..1, duration s, MIDI pitch] as in lumora.audio.instruments.
"""

import numpy as np

NAMES = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
# Krumhansl-Kessler key profiles (major, minor), tonic first
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# degree of a chord root, semitones above the tonic, named after the major or the natural minor scale
ROMAN = {
    "major": ("I", "♭II", "II", "♭III", "III", "IV", "♯IV", "V", "♭VI", "VI", "♭VII", "VII"),
    "minor": ("I", "♭II", "II", "III", "♯III", "IV", "♯IV", "V", "VI", "♯VI", "VII", "♯VII"),
}


def chord_name(root: int, minor: bool) -> str:
    return NAMES[root % 12] + ("m" if minor else "")


def _profiles(notes: np.ndarray, edges: np.ndarray, weight: float = 1.0) -> np.ndarray:
    """Pitch-class weight per interval [edges[i], edges[i+1]): how long and how loud each note sounds."""
    out = np.zeros((max(0, len(edges) - 1), 12))
    if len(notes) == 0 or len(out) == 0:
        return out
    for t, s, d, p in notes:
        if p <= 0:
            continue
        end = t + max(d, 0.05)
        a = max(0, int(np.searchsorted(edges, t, "right")) - 1)
        b = min(len(out), int(np.searchsorted(edges, end, "left")))
        for i in range(a, b):
            overlap = min(end, edges[i + 1]) - max(t, edges[i])
            if overlap > 0:
                out[i, round(p) % 12] += weight * s * overlap / (edges[i + 1] - edges[i])
    return out


def key_of(profile: np.ndarray) -> tuple[int, str, float]:
    """(tonic pitch class, "major" | "minor", confidence 0..1) of a 12-bin pitch-class profile."""
    if profile.sum() <= 0:
        return 0, "major", 0.0
    scores = []
    for mode, ref in (("major", MAJOR), ("minor", MINOR)):
        for tonic in range(12):
            scores.append((float(np.corrcoef(profile, np.roll(ref, tonic))[0, 1]), tonic, mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    return best[1], best[2], round(max(0.0, min(1.0, best[0])) * min(1.0, 4 * (best[0] - second[0]) + 0.3), 2)


def _templates() -> np.ndarray:
    """24 triads: rows 0-11 major on C..B, rows 12-23 minor."""
    t = np.zeros((24, 12))
    for root in range(12):
        t[root, [root, (root + 4) % 12, (root + 7) % 12]] = [1.0, 0.8, 0.8]
        t[12 + root, [root, (root + 3) % 12, (root + 7) % 12]] = [1.0, 0.8, 0.8]
    return t / np.linalg.norm(t, axis=1, keepdims=True)


def harmony(keys: np.ndarray, bass: np.ndarray, beats: np.ndarray, downbeats: np.ndarray, duration: float) -> dict:
    """Key and chords: {"key", "tonic", "mode", "confidence", "chords": [[start, duration, name, degree, strength]]}."""
    beats = np.asarray(beats, float)
    if len(beats) < 4:
        return {"key": None, "tonic": None, "mode": None, "confidence": 0.0, "chords": []}
    edges = np.concatenate([beats, [min(duration, beats[-1] + np.median(np.diff(beats)))]])
    prof = _profiles(keys, edges) + _profiles(bass, edges, 1.5)
    tonic, mode, conf = key_of(prof.sum(axis=0))
    tmpl = _templates()
    loud = prof.sum(axis=1)
    level = np.percentile(loud[loud > 0], 50) if np.any(loud > 0) else 1.0
    norm = prof / (np.linalg.norm(prof, axis=1, keepdims=True) + 1e-9)
    fit = norm @ tmpl.T  # beats x 24
    # chords that belong to the key are a little more likely
    scale = np.roll(MAJOR if mode == "major" else MINOR, tonic) > 3.4
    in_key = np.array([scale[r % 12] and scale[(r + (4 if c < 12 else 3)) % 12] for c, r in enumerate(list(range(12)) * 2)])
    fit = fit + 0.05 * in_key
    # a strong bass note on the root supports the chord
    bass_prof = _profiles(bass, edges)
    bass_root = np.argmax(bass_prof, axis=1)
    has_bass = bass_prof.max(axis=1) > 0
    for c in range(24):
        fit[has_bass & (bass_root == c % 12), c] += 0.08
    # Viterbi: changing chord costs, less on a bar line
    db = set(np.round(np.asarray(downbeats, float), 2))
    n = len(fit)
    cost = np.zeros((n, 24))
    back = np.zeros((n, 24), int)
    cost[0] = fit[0]
    for i in range(1, n):
        change = 0.08 if round(beats[i], 2) in db else 0.2
        stay = cost[i - 1]
        best = int(np.argmax(stay))
        switch = stay[best] - change
        better = stay >= switch
        cost[i] = np.where(better, stay, switch) + fit[i]
        back[i] = np.where(better, np.arange(24), best)
    path = np.zeros(n, int)
    path[-1] = int(np.argmax(cost[-1]))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    chords = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and path[j + 1] == path[i]:
            j += 1
        c = int(path[i])
        root, minor = c % 12, c >= 12
        strength = float(np.clip(loud[i : j + 1].mean() / (2 * level), 0, 1))
        quiet = loud[i : j + 1].mean() < 0.15 * level
        if not quiet:
            degree = ROMAN[mode][(root - tonic) % 12]
            chords.append(
                [
                    round(float(edges[i]), 3),
                    round(float(edges[j + 1] - edges[i]), 3),
                    chord_name(root, minor),
                    degree.lower() if minor else degree,
                    round(strength, 2),
                ]
            )
        i = j + 1
    return {
        "key": f"{NAMES[tonic]} {'Dur' if mode == 'major' else 'Moll'}",
        "tonic": tonic,
        "mode": mode,
        "confidence": conf,
        "chords": chords,
    }


def chord_events(h: dict) -> list[list[float]]:
    """Chord changes as track events [time, strength, duration, root pitch (MIDI, octave 4)]."""
    out = []
    for start, dur, name, _, strength in h.get("chords", []):
        root = NAMES.index(name.rstrip("m")) if name.rstrip("m") in NAMES else 0
        out.append([start, strength, dur, 60 + root])
    return out


def _groups(notes: np.ndarray, together: float = 0.05) -> list[np.ndarray]:
    groups, i = [], 0
    while i < len(notes):
        j = i
        while j + 1 < len(notes) and notes[j + 1, 0] - notes[i, 0] <= together:
            j += 1
        groups.append(notes[i : j + 1])
        i = j + 1
    return groups


def character(keys: np.ndarray, beat: float) -> dict[str, list[list[float]]]:
    """Stabs, pads and arpeggios of the keys / synths (see module doc) as event tracks."""
    out: dict[str, list[list[float]]] = {"stab": [], "pad": [], "arp": []}
    if len(keys) < 3:
        return out
    groups = _groups(keys)
    # stab: three or more notes struck together and released soon
    for g in groups:
        if len(np.unique(np.round(g[:, 3]))) >= 3 and np.median(g[:, 2]) < max(0.35, 0.6 * beat):
            length = float(np.median(g[:, 2]))
            out["stab"].append([round(g[0, 0], 3), round(float(g[:, 1].max()), 2), round(length, 3), g[:, 3].max()])
    # pad: at least two long notes sound together for a while
    long = keys[keys[:, 2] >= max(0.8, 1.5 * beat)]
    if len(long) >= 2:
        edges = np.arange(keys[0, 0], keys[-1, 0] + keys[-1, 2] + 0.25, 0.25)
        voices = np.zeros(len(edges))
        for t, _, d, _ in long:
            voices[(edges >= t) & (edges < t + d)] += 1
        on = voices >= 2
        i = 0
        while i < len(on):
            if not on[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(on) and (on[j + 1] or (j + 2 < len(on) and on[j + 2])):
                j += 1
            if edges[j] - edges[i] >= 2.0:
                inside = long[(long[:, 0] < edges[j]) & (long[:, 0] + long[:, 2] > edges[i])]
                out["pad"].append(
                    [round(edges[i], 3), round(float(inside[:, 1].mean()), 2), round(edges[j] - edges[i] + 0.25, 3),
                     round(float(inside[:, 3].mean()), 1)]
                )  # fmt: skip
            i = j + 1
    # arpeggio: six or more single notes in an even, quick rhythm with changing pitch
    single = np.array([g[np.argmax(g[:, 3])] for g in groups if len(g) == 1 or len(np.unique(np.round(g[:, 3]))) == 1])
    if len(single) >= 6:
        ioi = np.diff(single[:, 0])
        steady = (ioi <= max(0.32, 0.6 * beat)) & (ioi >= 0.06)
        i = 0
        while i < len(ioi):
            j = i
            while j < len(ioi) and steady[j] and abs(ioi[j] - ioi[i]) <= 0.25 * ioi[i]:
                j += 1
            run = single[i : j + 1]
            if len(run) >= 6 and len(np.unique(np.round(run[:, 3]))) >= 3:
                end = run[-1, 0] + max(run[-1, 2], ioi[i])
                out["arp"].append(
                    [round(run[0, 0], 3), round(float(run[:, 1].mean()), 2), round(end - run[0, 0], 3),
                     round(float(run[:, 3].mean()), 1)]
                )  # fmt: skip
            i = max(j, i + 1)
    for k in out:
        out[k] = [[float(x) for x in e] for e in out[k]]
    return out
