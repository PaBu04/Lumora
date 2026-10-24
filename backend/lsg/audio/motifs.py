"""Recurring motifs and riffs: a melody / keys pattern that comes back.

Every bar becomes a fingerprint: which pitch classes the melody (and, weaker, the other keys notes)
strike on which eighth (blurred over the neighbouring eighths). Bars whose fingerprints nearly match
play the same riff. A riff that comes at least three times becomes a motif; consecutive bars of the
same motif form one occurrence.

Result: track "motif" with events [start s, strength, duration s, motif number 1..] - the pitch
field carries the number, so the same riff can always get the same light - and a summary list.
"""

import numpy as np

STEPS = 8  # eighth notes: fine enough for a riff, coarse enough for small timing differences
MIN_NOTES = 3  # a bar needs this many melody notes to be a riff
MAX_MOTIFS = 4


def _fingerprints(lead: np.ndarray, keys: np.ndarray, edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bar: STEPS x 12 onset grid (flattened) and the number of melody onsets."""
    fp = np.zeros((len(edges) - 1, STEPS, 12))
    count = np.zeros(len(edges) - 1, int)
    for notes, weight, counts in ((lead, 1.0, True), (keys, 0.35, False)):
        for t, s, _, p in notes:
            if p <= 0:
                continue
            i = int(np.searchsorted(edges, t, "right")) - 1
            if not 0 <= i < len(edges) - 1:
                continue
            step = min(STEPS - 1, int((t - edges[i]) / (edges[i + 1] - edges[i]) * STEPS + 0.35))
            fp[i, step, round(p) % 12] += weight * (0.4 + 0.6 * s)
            count[i] += counts
    fp = fp + 0.5 * (np.roll(fp, 1, axis=1) + np.roll(fp, -1, axis=1))  # a note a little early or late still matches
    flat = fp.reshape(len(fp), -1)
    norm = np.linalg.norm(flat, axis=1, keepdims=True)
    return flat / np.where(norm > 0, norm, 1), count


def motifs(lead: np.ndarray, keys: np.ndarray, downbeats: np.ndarray, duration: float, threshold: float = 0.8):
    """(track events, summary [{"id", "bars", "count", "times", "pitch"}]) of the recurring riffs."""
    db = np.asarray([d for d in downbeats if d < duration - 0.5], float)
    if len(db) < 8 or len(lead) < MIN_NOTES * 3:
        return [], []
    edges = np.concatenate([db, [duration]])
    fp, count = _fingerprints(lead, keys, edges)
    riff = count >= MIN_NOTES
    sim = fp @ fp.T
    # groups of bars that play the same riff (single linkage over riff bars)
    group = -np.ones(len(fp), int)
    n_groups = 0
    for i in np.flatnonzero(riff):
        match = [j for j in np.flatnonzero(riff[:i]) if sim[i, j] >= threshold]
        if match:
            group[i] = group[max(match, key=lambda j: sim[i, j])]
        else:
            group[i] = n_groups
            n_groups += 1
    # occurrences: runs of consecutive bars of one group
    runs: dict[int, list[tuple[int, int]]] = {}
    i = 0
    while i < len(group):
        if group[i] < 0:
            i += 1
            continue
        j = i
        while j + 1 < len(group) and group[j + 1] == group[i]:
            j += 1
        runs.setdefault(int(group[i]), []).append((i, j + 1))
        i = j + 1
    # a riff counts by how often it is played (bars); keep the clearest few
    ranked = sorted((g for g, r in runs.items() if sum(b - a for a, b in r) >= 3), key=lambda g: -sum(b - a for a, b in runs[g]))[
        :MAX_MOTIFS
    ]
    events, summary = [], []
    for number, g in enumerate(sorted(ranked, key=lambda g: runs[g][0][0]), start=1):
        times = []
        bars = [k for a, b in runs[g] for k in range(a, b)]
        melody = lead[[int(np.searchsorted(edges, t, "right")) - 1 in bars for t in lead[:, 0]]]
        for a, b in runs[g]:
            inside = lead[(lead[:, 0] >= edges[a]) & (lead[:, 0] < edges[b])]
            strength = float(inside[:, 1].mean()) if len(inside) else 0.5
            events.append([round(float(edges[a]), 3), round(strength, 2), round(float(edges[b] - edges[a]), 3), float(number)])
            times.append(round(float(edges[a]), 3))
        summary.append(
            {
                "id": number,
                "bars": len(bars),
                "count": len(runs[g]),
                "times": times,
                "pitch": round(float(np.median(melody[:, 3])), 1) if len(melody) else 0.0,
            }
        )
    events.sort(key=lambda e: e[0])
    return events, summary
