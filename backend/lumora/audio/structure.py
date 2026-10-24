"""Song form from the separated instruments: sections on phrase boundaries, named and rated.

Works bar by bar. A section boundary is where the instrumentation changes (drums, bass or vocals
come in or stop, the music gets louder / denser / brighter, the chords change pattern) - plus the
drops and build-ups found in lumora.audio.instruments. The boundaries are chosen together (dynamic
programming) so that sections are preferably 4, 8 or 16 bars long and start on the song's phrase
grid, which is anchored on its strongest drop.

Sections that sound alike get the same letter. Names follow the instrumentation and the order:
intro, verse, prechorus, chorus, break, build, drop, bridge, outro. Every section gets an
intensity 1..5 relative to the whole song; the strongest one is the peak, so a show can keep its
brightest moment for it. Phrases (4 or 8 bars) subdivide the sections.
"""

import itertools

import numpy as np

from lumora.model.song import Section

# instrumentation per bar and how much a change in it matters for a boundary
PRESENCE = ("drums", "bass", "vocals", "other", "loudness", "density", "brightness")
WEIGHTS = np.array([1.5, 1.5, 1.5, 0.6, 1.0, 1.0, 0.5])
SEGMENT_COST = 0.55  # every section costs this much: fewer, longer sections unless a change is clear
MAX_BARS = 32


def _shape_cost(bars: int) -> float:
    """Musical section lengths: 8 and 16 bars are normal, 4 and 12 fine, odd lengths rare."""
    if bars < 2:
        return 9.0
    if bars in (8, 16):
        return 0.0
    if bars in (4, 12, 24, 32):
        return 0.12
    if bars % 4 == 0:
        return 0.25
    if bars % 2 == 0:
        return 0.45 + (0.25 if bars < 4 else 0.0)
    return 0.7 + (0.25 if bars < 4 else 0.0)


def _bar_means(curves: dict[str, np.ndarray], rate: float, edges: np.ndarray) -> np.ndarray:
    out = np.zeros((len(edges) - 1, len(PRESENCE)))
    for j, name in enumerate(PRESENCE):
        c = curves.get(name)
        if c is None or len(c) < 2:
            continue
        for i in range(len(edges) - 1):
            a, b = int(edges[i] * rate), max(int(edges[i] * rate) + 1, int(edges[i + 1] * rate))
            out[i, j] = float(np.mean(c[a:b])) if a < len(c) else 0.0
    return out


def _bar_chords(harmony: dict | None, edges: np.ndarray) -> np.ndarray:
    """Pitch-class weight of the chord roots sounding in each bar (12 bins)."""
    out = np.zeros((len(edges) - 1, 12))
    from lumora.audio.harmony import NAMES

    for start, dur, name, _, strength in (harmony or {}).get("chords", []):
        root = name.rstrip("m")
        if root not in NAMES:
            continue
        pc = NAMES.index(root)
        for i in range(len(edges) - 1):
            overlap = min(start + dur, edges[i + 1]) - max(start, edges[i])
            if overlap > 0:
                out[i, pc] += overlap * (0.5 + strength)
    norm = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norm > 0, norm, 1)


def _change(x: np.ndarray, i: int, k: int) -> float:
    """How different the k bars after bar line i are from the k bars before it."""
    if i - k < 0 or i + k > len(x):
        k = min(i, len(x) - i)
    if k <= 0:
        return 0.0
    return float(np.linalg.norm(x[i : i + k].mean(axis=0) - x[i - k : i].mean(axis=0)))


def boundaries(
    presence: np.ndarray,
    chords: np.ndarray,
    forced: dict[int, float],
    phase: int,
    blocked: set[int] | None = None,
    pickup: bool = False,
) -> list[int]:
    """Bar indices where sections start (always including 0), chosen by dynamic programming.
    `forced`: extra weight for a boundary at a bar (drops, build-ups); `blocked`: bars that must not
    start a section (inside a build-up)."""
    blocked = blocked or set()
    n = len(presence)
    if n <= 4:
        return [0]
    weighted = presence * WEIGHTS
    score = np.zeros(n + 1)
    for i in range(1, n):
        inst = 0.5 * _change(weighted, i, 2) + 0.5 * _change(weighted, i, 4)
        harm = 0.25 * _change(chords, i, 4)
        grid = 0.25 if (i - phase) % 8 == 0 else 0.12 if (i - phase) % 4 == 0 else 0.0
        score[i] = inst + harm + grid + forced.get(i, 0.0)
    best = np.full(n + 1, -np.inf)
    prev = np.zeros(n + 1, int)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(max(0, j - MAX_BARS), j):
            if best[i] == -np.inf or i in blocked:
                continue
            length = j - i + (1 if i == 0 and pickup else 0)  # music before the first bar line
            # the first and last section may be any length (pickup bars, fade-out)
            shape = 0.2 * _shape_cost(length) if i == 0 or j == n else _shape_cost(length)
            v = best[i] + (score[i] if i > 0 else 0.0) - SEGMENT_COST - shape
            if v > best[j]:
                best[j], prev[j] = v, i
    cuts, j = [], n
    while j > 0:
        cuts.append(int(prev[j]))
        j = int(prev[j])
    return sorted(cuts)


def similarity(vecs: list[np.ndarray]) -> np.ndarray:
    """Cosine similarity of section vectors after removing the song's average, so what counts is
    how a section differs from the rest."""
    v = np.asarray(vecs) - np.mean(vecs, axis=0)
    v = v / np.maximum(v.std(axis=0), 0.25)  # features count by how much they vary in this song
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    return v @ v.T


def _labels(sim: np.ndarray, threshold: float = 0.8) -> list[str]:
    """Letters: a section joins the group of the most similar earlier section (single linkage)."""
    labels: list[str] = []
    groups = 0
    for i in range(len(sim)):
        j = int(np.argmax(sim[i, :i])) if i else -1
        if j >= 0 and sim[i, j] >= threshold:
            labels.append(labels[j])
        else:
            labels.append(chr(ord("A") + min(25, groups)))
            groups += 1
    return labels


def structure(
    downbeats: np.ndarray,
    duration: float,
    curves: dict[str, np.ndarray],
    rate: float,
    tracks: dict[str, list[list[float]]],
    harmony: dict | None,
) -> tuple[list[Section], list[list[float]]]:
    """Sections and phrases ([start s, bars]) of a song analysed with instruments."""
    db = np.asarray([d for d in downbeats if d < duration - 0.5], float)
    if len(db) < 6:
        return [Section(start=0.0, end=duration, name="verse", label="A", energy=0.5, bars=len(db))], []
    edges = np.concatenate([db, [duration]])
    pickup = db[0] > 0.3  # music before the first bar line joins the first section
    presence = _bar_means(curves, rate, edges)
    chords = _bar_chords(harmony, edges)
    bar_len = float(np.median(np.diff(db)))

    def bar_at(t: float) -> int:
        return int(np.argmin(np.abs(db - t)))

    drops = [e for e in tracks.get("drop", []) if e[1] >= 0.8]
    builds = [e for e in tracks.get("build", []) if e[2] >= 1.5 * bar_len]
    forced: dict[int, float] = {}
    for e in drops:
        forced[bar_at(e[0])] = forced.get(bar_at(e[0]), 0.0) + 1.2
    blocked: set[int] = set()
    for e in builds:
        forced[bar_at(e[0])] = forced.get(bar_at(e[0]), 0.0) + 0.6
        blocked.update(range(bar_at(e[0]) + 1, bar_at(e[0] + e[2])))  # a build-up is one section
    if drops:
        phase = bar_at(max(drops, key=lambda e: e[1])[0]) % 8
    else:  # the phase where the instrumentation changes most often
        weighted = presence * WEIGHTS
        change = [_change(weighted, i, 2) for i in range(len(db))]
        phase = int(np.argmax([sum(change[p::4]) for p in range(4)]))
    starts = boundaries(presence, chords, forced, phase, blocked, pickup)
    bounds = [*starts, len(db)]

    # per section: instrumentation, intensity, similarity vector
    segs = []
    for a, b in itertools.pairwise(bounds):
        p = presence[a:b].mean(axis=0)
        segs.append({"a": a, "b": b, "p": dict(zip(PRESENCE, p, strict=True)), "chords": chords[a:b].mean(axis=0)})
    vecs = [np.concatenate([np.array([s["p"][k] for k in PRESENCE]) * WEIGHTS * 1.5, s["chords"]]) for s in segs]
    sim = similarity(vecs)
    labels = _labels(sim)
    score = np.array(
        [
            0.3 * s["p"]["loudness"] + 0.2 * s["p"]["density"] + 0.15 * s["p"]["drums"] + 0.2 * s["p"]["bass"]
            + 0.15 * s["p"]["brightness"]
            for s in segs
        ]
    )  # fmt: skip
    lo, hi = float(score.min()), float(score.max())
    intensity = [round(1 + 4 * (v - lo) / (hi - lo)) if hi > lo else 3 for v in score]
    weight = [s["b"] - s["a"] for s in segs]
    peak = max(range(len(segs)), key=lambda i: score[i] + 0.02 * i / len(segs) if weight[i] >= 4 else -1.0)

    # names
    t_start = [0.0 if s["a"] == 0 else float(edges[s["a"]]) for s in segs]
    t_end = [float(edges[s["b"]]) for s in segs]
    drop_times = [e[0] for e in drops]
    build_spans = [(e[0], e[0] + e[2]) for e in builds]
    names = [""] * len(segs)
    loud_max = max(s["p"]["loudness"] for s in segs) or 1.0
    for i, s in enumerate(segs):
        p = s["p"]
        after_build = i > 1 and (
            names[i - 1] == "build" or (segs[i - 1]["p"]["drums"] < 0.15 and segs[i - 1]["p"]["vocals"] < 0.3)
        )  # not right after the intro: there the beat coming in is usually the verse
        if any(abs(t - t_start[i]) <= bar_len * 0.6 for t in drop_times) and (
            intensity[i] == 5 or (intensity[i] >= 4 and after_build)
        ):
            names[i] = "drop"
        elif any(min(b1, t_end[i]) - max(b0, t_start[i]) >= 0.5 * (t_end[i] - t_start[i]) for b0, b1 in build_spans):
            names[i] = "build"
        elif i == 0 and (p["loudness"] < 0.7 * loud_max or (p["drums"] < 0.15 and p["vocals"] < 0.3)):
            names[i] = "intro"
        elif i == len(segs) - 1 and len(segs) > 2 and (p["loudness"] < 0.7 * loud_max or weight[i] <= 4):
            names[i] = "outro"
        elif p["vocals"] < 0.3 and p["drums"] < 0.15 and 0 < i < len(segs) - 1:
            names[i] = "break"
    # everything before drums or vocals first come in is the intro
    for i, seg in enumerate(segs):
        if seg["p"]["drums"] >= 0.15 or seg["p"]["vocals"] >= 0.3 or names[i] in ("drop", "build") or i > len(segs) // 3:
            break
        names[i] = "intro"
    # the chorus: the sung part that comes back and leads into a break, build-up or drop (a verse
    # leads into the chorus); the other sung parts are verses
    sung = [i for i, seg in enumerate(segs) if not names[i] and seg["p"]["vocals"] >= 0.3]
    by_label: dict[str, list[int]] = {}
    for i in sung:
        by_label.setdefault(labels[i], []).append(i)
    if by_label:

        def leads_on(i: int) -> bool:
            k = i
            while k + 1 < len(segs) and labels[k + 1] == labels[i]:
                k += 1
            nxt = [names[m] or ("" if segs[m]["p"]["vocals"] >= 0.3 else "break") for m in range(k + 1, min(k + 3, len(segs)))]
            return any(n in ("break", "build", "drop") for n in nxt) or k == len(segs) - 1

        def chorus_score(label: str) -> float:
            idx = by_label[label]
            runs = [i for i in idx if i == 0 or labels[i - 1] != label]
            first = min(idx)
            later = sum(first > min(v) for v in by_label.values())
            return (
                float(np.mean([segs[i]["p"]["vocals"] for i in idx]))
                + 0.6 * float(np.mean([leads_on(i) for i in runs]))
                + 0.3 * later
                + (0.4 if len(runs) >= 2 else 0.0)
            )

        chorus = max(by_label, key=chorus_score) if len(by_label) > 1 or len(by_label[next(iter(by_label))]) > 1 else None
        for i in sung:
            names[i] = "chorus" if labels[i] == chorus else "verse"
    # a short tail (up to 4 bars, heard once) belongs to the part before it
    for i in range(1, len(segs)):
        if weight[i] <= 4 and labels.count(labels[i]) == 1 and names[i] in ("verse", "") and sim[i, i - 1] >= 0.3:
            names[i] = names[i - 1]
    plain = [i for i in range(len(segs)) if not names[i]]
    groups: dict[str, list[int]] = {}
    for i in plain:
        groups.setdefault(labels[i], []).append(i)
    instrumental_chorus = max(groups, key=lambda k: np.mean([intensity[i] for i in groups[k]])) if groups else None
    if instrumental_chorus and len(groups) == 1 and max(intensity[i] for i in groups[instrumental_chorus]) < 4:
        instrumental_chorus = None
    seen_chorus = False
    for i in range(len(segs)):
        if names[i] == "verse" and i + 1 < len(segs) and names[i + 1] in ("chorus", "build", "drop") and weight[i] <= 8:
            before = [names[k] for k in range(i)]
            if "verse" in before[-2:]:
                names[i] = "prechorus"
        if not names[i] and i > 0 and labels[i] == labels[i - 1]:  # more of the same
            names[i] = names[i - 1]
        if not names[i]:  # instrumental with drums: the most intense group is the chorus
            names[i] = "chorus" if labels[i] == instrumental_chorus else "verse"
        if seen_chorus and labels.count(labels[i]) == 1 and names[i] in ("verse", "break") and i < len(segs) - 2:
            names[i] = "bridge"
        seen_chorus = seen_chorus or names[i] == "chorus"

    # a split intro is one intro
    while len(segs) > 1 and names[0] == names[1] == "intro":
        segs[1]["a"] = segs[0]["a"]
        w0, w1 = weight[0], weight[1]
        segs[1]["p"] = {k: (segs[0]["p"][k] * w0 + segs[1]["p"][k] * w1) / (w0 + w1) for k in PRESENCE}
        for arr in (segs, names, labels, intensity, weight, t_start, t_end):
            del arr[0]
        weight[0] = segs[0]["b"] - segs[0]["a"]
        t_start[0] = 0.0
        peak -= 1

    # letters in order of appearance
    order: dict[str, str] = {}
    for lab in labels:
        order.setdefault(lab, chr(ord("A") + min(25, len(order))))
    labels = [order[lab] for lab in labels]

    # sections and phrases
    sections, phrases = [], []
    count: dict[str, int] = {}
    for i, s in enumerate(segs):
        count[labels[i]] = count.get(labels[i], 0) + 1
        first = s["a"] - (1 if s["a"] == 0 and pickup else 0)  # a pickup bar before the first bar line counts
        bars = s["b"] - first
        sections.append(
            Section(
                start=round(t_start[i], 3),
                end=round(t_end[i], 3) if i < len(segs) - 1 else round(duration, 3),
                name=names[i],
                label=labels[i],
                energy=round(float(s["p"]["loudness"]), 3),
                bars=bars,
                repeat=count[labels[i]],
                intensity=intensity[i],
                peak=i == peak,
            )
        )
        step = 8 if bars % 8 == 0 and bars >= 16 else 4
        for k in range(first, s["b"], step):
            phrases.append([round(0.0 if k <= 0 and pickup else float(edges[k]), 3), min(step, s["b"] - k)])
    return sections, phrases


def rate_sections(sections: list[Section]) -> list[Section]:
    """Intensity 1..5 and the peak from the sections' energy (analyses without instruments)."""
    if not sections:
        return sections
    e = np.array([s.energy for s in sections])
    lo, hi = float(e.min()), float(e.max())
    peak = int(np.argmax(e + 1e-3 * np.arange(len(e))))
    return [
        s.model_copy(update={"intensity": round(1 + 4 * (s.energy - lo) / (hi - lo)) if hi > lo else 3, "peak": i == peak})
        for i, s in enumerate(sections)
    ]
