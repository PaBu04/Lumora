"""Rule-based starter show from the song analysis and the room (no AI needed).

Design rules (the same ones the AI gets in its instructions):
  * follow the instruments, not a grid: drums light small segments on their hits (with their
    velocity), melody and bass show up as notes (position = pitch), single moments - drops,
    crashes, drum fills - get one-shot cues, build-ups rise until the drop
  * dark by default and dark where the music is quiet: passages without drums keep only the
    melody glowing, the show's dynamics setting darkens quiet parts further; long strips light
    up the whole room even when dim, so their levels are scaled down
  * the viewer sees only some strips directly: each gets an instrument (drums, melody, bass,
    accents); strips behind / beside the viewer only colour the room and flash on big hits
  * the song form shapes the show: sections with the same label share a theme (colours, who
    leads), a repeat comes a little bigger, light grows with the section's intensity and the full
    look is kept for the song's peak; recurring riffs (motifs) always get the same gesture, and
    looks change on phrase starts
  * a style (party, calm, cinematic, minimal), a colour world and a variant number change the
    result without changing these rules
"""

import colorsys
import zlib

import numpy as np

from lumora.audio.features import AudioFeatures
from lumora.model.project import Project
from lumora.model.show import Clip, Layer, Show, StarterStyle, Target
from lumora.model.song import Analysis

# colour worlds: looks of (palette for washes dark -> bright, accent colour, second accent)
PALETTES: dict[str, list[tuple[list[str], str, str]]] = {
    "cool": [
        (["#001a40", "#0050a0", "#00a0c0"], "#40c0ff", "#ffffff"),
        (["#100030", "#3000a0", "#7040ff"], "#a080ff", "#40e0ff"),
        (["#002018", "#006048", "#00b080"], "#40ffc0", "#80a0ff"),
        (["#0a1030", "#203080", "#5070d0"], "#80b0ff", "#c080ff"),
    ],
    "warm": [
        (["#301000", "#803000", "#ff7000"], "#ffa030", "#ff3000"),
        (["#200030", "#600060", "#c03070"], "#ff4080", "#ffb000"),
        (["#301800", "#805000", "#ffb000"], "#ffd060", "#ff6040"),
        (["#300010", "#901030", "#ff4050"], "#ff8060", "#ffd0a0"),
    ],
    "neon": [
        (["#200030", "#8000c0", "#ff00ff"], "#ff40ff", "#00ffff"),
        (["#002030", "#00a0c0", "#00ffff"], "#00ffd0", "#ff00a0"),
        (["#202000", "#80a000", "#e0ff00"], "#c0ff40", "#ff40c0"),
        (["#300010", "#c00060", "#ff2080"], "#ff4090", "#40ffff"),
    ],
    "nature": [
        (["#0a2010", "#206030", "#60a040"], "#a0e060", "#ffe080"),
        (["#102030", "#205070", "#40a0a0"], "#80e0d0", "#f0d090"),
        (["#201808", "#605020", "#c09040"], "#ffd080", "#80c060"),
        (["#081828", "#185058", "#50a088"], "#a0f0c0", "#ffffff"),
    ],
    "mono": [
        (["#101010", "#404040", "#a0a0a0"], "#ffffff", "#c0d0ff"),
        (["#101418", "#303c48", "#8090a0"], "#e0f0ff", "#ffffff"),
    ],
}
LOOKS = PALETTES["cool"] + PALETTES["warm"]  # the live show and older callers
# what each style puts in: overall level, darkening of quiet parts, which parts and cues
STYLES: dict[str, dict] = {
    "party": dict(level=1.0, dynamics=0.55, hihat=True, accents=True, room=True, cues=True, fills=True, motifs=True,
                  phrase="pulse", chords=False, roles=4, decay=1.0),
    "calm": dict(level=0.75, dynamics=0.7, hihat=False, accents=False, room=True, cues=True, fills=False, motifs=True,
                 phrase=None, chords=True, roles=3, decay=1.8),
    "cinematic": dict(level=0.9, dynamics=0.8, hihat=False, accents=True, room=True, cues=True, fills=True, motifs=True,
                      phrase="sweep", chords=True, roles=4, decay=1.4),
    "minimal": dict(level=0.8, dynamics=0.7, hihat=False, accents=False, room=False, cues=False, fills=False, motifs=False,
                    phrase=None, chords=False, roles=2, decay=1.2),
}  # fmt: skip
LONG_STRIP = 120  # LEDs; longer strips get dimmer washes


def _fallback(name: str, song_id: str | None, duration: float | None) -> Show:
    end = duration or 60.0
    return Show(
        name=name,
        song_id=song_id,
        description="Starter show (song not analysed yet)",
        layers=[
            Layer(name="Base", clips=[Clip(start=0, end=end, effect="noise", params={"palette": "ocean", "brightness": 0.15})])
        ],
    )


def _fixture_info(project: Project | None, table) -> list[dict]:
    """Strips as parts the viewer sees directly or not. A strip that runs both in front of and
    behind the viewer (e.g. around the ceiling) becomes two parts with a view target."""
    if project is None or table is None:
        return []
    out = []
    for f in project.fixtures:
        sl = table.fixture_slice(f.id)
        n = sl.stop - sl.start
        if not n:
            continue
        seen = int((table.view[sl] >= 0.5).sum())
        if min(seen, n - seen) >= max(10, 0.15 * n):
            out.append({"id": f.id, "leds": seen, "view": 1.0, "part": "direct"})
            out.append({"id": f.id, "leds": n - seen, "view": 0.0, "part": "indirect"})
        else:
            out.append({"id": f.id, "leds": n, "view": float(table.view[sl].mean()), "part": None})
    return out


def _target(f: dict) -> Target:
    if f["id"] is None:
        return Target()
    return Target(fixtures=[f["id"]], view=f.get("part"))


def _dim(base: float, leds: int) -> float:
    """Washes on long strips flood the room: scale down with the number of LEDs."""
    return round(max(0.03, base * min(1.0, (LONG_STRIP / max(leds, 1)) ** 0.5)), 3)


ROLES = ("drums", "melody", "bass", "accent")


def _roles(direct: list[dict], count: int = 4) -> dict[str, list[dict]]:
    """Give every strip in view an instrument to show: the longest strip the drums (small hits
    spread over many LEDs), then melody (vocal / lead notes), bass notes and accents. With fewer
    strips, strips take several roles; with more, roles repeat. `count` < 4 leaves out accents
    (and bass)."""
    roles = ROLES[: max(2, min(4, count))]
    parts = sorted(direct, key=lambda f: -f["leds"])
    out: dict[str, list[dict]] = {r: [] for r in ROLES}
    for i, f in enumerate(parts):
        out[roles[i % len(roles)]].append(f)
    for i, r in enumerate(roles):
        if not out[r]:
            out[r] = [parts[i % len(parts)]]
    return out


def _mean(features: AudioFeatures, name: str, a: float, b: float) -> float:
    c = features.curves.get(name)
    if c is None or len(c) < 2:
        return 0.0
    i, j = int(a * features.frame_rate), max(int(a * features.frame_rate) + 1, int(b * features.frame_rate))
    return float(np.mean(c[i:j])) if i < len(c) else 0.0


def _mood(s, features: AudioFeatures) -> str:
    """dark (quiet, no beat), calm, full (the intense parts) or build - from the song form."""
    if s.name == "build":
        return "build"
    drums = _mean(features, "drums", s.start, s.end) if features.has_instruments else _mean(features, "density", s.start, s.end)
    if s.name in ("intro", "outro", "break") and s.intensity <= 3:
        return "dark"
    if drums < 0.12:  # no beat: let the melody glow, keep the room dark
        return "dark" if s.intensity <= 3 else "calm"
    if s.peak or s.name == "drop" or s.intensity >= 4:
        return "full"
    return "calm"


def _clip(start, end, effect, target, blend="max", **params) -> Clip:
    return Clip(start=start, end=end, effect=effect, target=target, blend=blend, params=params)


def _events(f: AudioFeatures, track: str, a: float, b: float) -> list[tuple[float, float, float, float]]:
    """Events of a track that overlap [a, b)."""
    ev = f.tracks.get(track) if f.has_instruments else None
    if ev is None:
        return []
    return [
        (float(t), float(v), float(d), float(p))
        for t, v, d, p in zip(ev.times, ev.strength, ev.duration, ev.pitch, strict=True)
        if t < b and t + d >= a
    ]


def _section_clips(s, mood: str, roles: dict, indirect: list[dict], look, f: AudioFeatures, opt: dict, level: float) -> dict:
    """Long clips driven by instrument tracks for one section, per layer name. `level` scales the
    section's brightness (intensity, repeats, the peak)."""
    pal, acc, acc2 = look
    a, b = s.start, s.end
    out: dict[str, list[Clip]] = {"Raum": [], "Drums": [], "Melodie": []}
    tracks = f.tracks if f.has_instruments else {}
    singing = _events(f, "phrase", a, b)
    bass_on = "bass" in tracks and _mean(f, "bass", a, b) > 0.15
    slow = opt["decay"]

    def lv(x: float) -> float:
        return round(min(1.0, x * level), 2)

    # drums: small segments on the biggest strip(s)
    for p in roles["drums"]:
        tgt = _target(p)
        if mood in ("calm", "full"):
            big = mood == "full"
            out["Drums"].append(
                _clip(
                    a,
                    b,
                    "hits",
                    tgt,
                    palette=[acc, "#ffffff"],
                    trigger="kick",
                    count=2 if big else 1,
                    size=12 if big else 8,
                    decay=round(0.18 * slow, 2),
                    brightness=lv(0.9 if big else 0.7),
                )
            )
            out["Drums"].append(
                _clip(
                    a,
                    b,
                    "hits",
                    tgt,
                    palette=[acc2],
                    trigger="snare",
                    count=2 if big else 1,
                    size=8 if big else 5,
                    decay=round(0.15 * slow, 2),
                    brightness=lv(0.85 if big else 0.6),
                )
            )
            if big and opt["hihat"]:
                out["Drums"].append(
                    _clip(
                        a, b, "hits", tgt, palette=["#ffffff"], trigger="hihat", count=2, size=2, decay=0.07, brightness=lv(0.35)
                    )
                )
        elif mood == "build":  # the rise itself is a cue over all strips in view
            out["Drums"].append(
                _clip(
                    a, b, "hits", tgt, palette=["#ffffff", acc2], trigger="snare", count=1, size=6, decay=0.1, brightness=lv(0.8)
                )
            )

    # melody: sung notes while singing, the keys / synths in between - an arpeggio runs as a chase
    arps = [(t, d) for t, _, d, _ in _events(f, "arp", a, b)]
    for p in roles["melody"]:
        tgt = _target(p)
        base = {"dark": 0.4, "calm": 0.6, "full": 0.85, "build": 0.5}[mood]
        free, cursor = [], a
        for t0, _, d, _ in singing:
            c0, c1 = max(a, t0), min(b, t0 + d + 0.6)
            if c1 - c0 > 0.3:
                out["Melodie"].append(
                    _clip(
                        c0,
                        c1,
                        "notes",
                        tgt,
                        track="vocal",
                        palette=[pal[-1], acc],
                        axis="u",
                        width=0.1,
                        decay=round(0.35 * slow, 2),
                        max_hold=1.0,
                        brightness=lv(base),
                    )
                )
            free.append((cursor, c0))
            cursor = max(cursor, c1)
        free.append((cursor, b))
        for c0, c1 in free:
            if c1 - c0 < 2.0:
                continue
            if "lead" in tracks and mood != "build":
                out["Melodie"].append(
                    _clip(
                        c0,
                        c1,
                        "notes",
                        tgt,
                        track="keys" if "keys" in tracks else "lead",
                        palette=[pal[1], acc],
                        axis="u",
                        width=0.06,
                        decay=round(0.25 * slow, 2),
                        max_hold=0.5,
                        brightness=lv(base * 0.8),
                    )
                )
            elif not tracks and mood != "dark":
                out["Melodie"].append(
                    _clip(
                        c0, c1, "hits", tgt, palette=[acc, acc2], trigger="onset", count=1, size=8, decay=0.4, brightness=lv(base)
                    )
                )
        for t0, d in arps:
            c0, c1 = max(a, t0), min(b, t0 + d)
            if c1 - c0 > 0.5 and mood != "build":
                out["Melodie"].append(
                    _clip(
                        c0,
                        c1,
                        "chase",
                        tgt,
                        blend="add",
                        color=acc,
                        axis="u",
                        count=3,
                        width=0.2,
                        tail=0.9,
                        beats=1,
                        brightness=lv(base * 0.6),
                    )
                )

    # bass notes, low on the strip = low note
    if bass_on and mood in ("calm", "full") and opt["roles"] >= 3:
        for p in roles["bass"]:
            out["Melodie"].append(
                _clip(
                    a,
                    b,
                    "notes",
                    _target(p),
                    track="bass",
                    palette=[pal[0], pal[-1]],
                    axis="u",
                    width=0.25,
                    decay=round(0.2 * slow, 2),
                    max_hold=0.6,
                    brightness=lv(0.75 if mood == "full" else 0.5),
                )
            )

    # accents: chord stabs (or snares) flash the small strips, held chords (pads) glow
    stabs = len(_events(f, "stab", a, b)) >= 4
    pads = _events(f, "pad", a, b)
    for p in roles["accent"] if opt["roles"] >= 4 else []:
        tgt = _target(p)
        if mood in ("calm", "full") and opt["accents"]:
            out["Drums"].append(
                _clip(
                    a,
                    b,
                    "pulse",
                    tgt,
                    color=acc2,
                    trigger="stab" if stabs else "snare",
                    decay=round(0.12 * slow, 2),
                    velocity=0.8,
                    brightness=lv(0.8 if mood == "full" else 0.55),
                )
            )
        if pads and mood != "build":
            out["Melodie"].append(
                _clip(
                    a, b, "pulse", tgt, color=pal[-1], trigger="pad", sustain=True, decay=1.5, velocity=0.4, brightness=lv(0.25)
                )
            )
        elif mood == "dark" and singing:
            out["Melodie"].append(
                _clip(
                    a, b, "pulse", tgt, color=pal[-1], trigger="phrase", sustain=True, decay=1.2, velocity=0.3, brightness=lv(0.2)
                )
            )

    # room colour behind / beside the viewer: dim, follows the bass, flashes on kicks when full
    for p in indirect if opt["room"] else []:
        tgt = _target(p)
        if mood == "full":
            out["Raum"].append(
                _clip(
                    a,
                    b,
                    "noise",
                    tgt,
                    blend="normal",
                    palette=pal,
                    speed=0.15,
                    scale=0.6,
                    brightness={"audio": "bass" if bass_on else "loudness", "min": 0.03, "max": _dim(0.14 * level, p["leds"])},
                )
            )
            out["Raum"].append(
                _clip(
                    a,
                    b,
                    "pulse",
                    tgt,
                    blend="add",
                    color=acc,
                    trigger="kick",
                    decay=0.12,
                    velocity=0.7,
                    brightness=_dim(0.5 * level, p["leds"]),
                )
            )
        elif mood == "calm":
            out["Raum"].append(
                _clip(
                    a,
                    b,
                    "noise",
                    tgt,
                    blend="normal",
                    palette=pal,
                    speed=0.1,
                    scale=0.6,
                    brightness=_dim(0.06 * level, p["leds"]),
                )
            )
        elif mood == "build":
            out["Raum"].append(
                _clip(
                    a,
                    b,
                    "pulse",
                    tgt,
                    blend="add",
                    color=acc,
                    trigger="snare",
                    decay=0.1,
                    velocity=0.5,
                    brightness={"audio": "tension", "min": 0.03, "max": _dim(0.5 * level, p["leds"])},
                )
            )
    return out


def _hue(root_pitch: float) -> str:
    """A colour per chord root (pitch class around the colour wheel)."""
    r, g, b = colorsys.hsv_to_rgb((root_pitch % 12) / 12, 0.75, 1.0)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _cues(
    f: AudioFeatures,
    analysis: Analysis,
    targets: dict[str, Target | None],
    looks_at,
    moods: dict,
    beat: float,
    rise_axis: str,
    opt: dict,
    style: StarterStyle,
) -> list[Clip]:
    """One-shot clips at single moments: drops, crashes, drum fills, build-ups, recurring riffs,
    phrase starts and chord changes - depending on the style."""
    everything, direct, indirect = Target(), targets["direct"], targets["indirect"]
    tracks = f.tracks if f.has_instruments else {}
    out: list[Clip] = []
    drops = [(t, v) for t, v, _, _ in zip(*tracks["drop"], strict=True)] if "drop" in tracks else []
    peak = next((s for s in analysis.sections if s.peak), None)
    for t, v in drops:
        if v < 0.4:
            continue
        _, acc, _ = looks_at(t)
        at_peak = peak is not None and abs(t - peak.start) < 1.0
        out.append(
            _clip(
                t,
                t + 2.0,
                "pulse",
                indirect or everything,
                blend="add",
                color="#ffffff",
                trigger="once",
                decay=0.35 + 0.6 * v,
                brightness=round(min(1.0, (0.5 + 0.5 * v) * (1.0 if at_peak else 0.85)), 2),
            )
        )
        out.append(
            _clip(
                t,
                t + 2.5,
                "ripple",
                everything,
                blend="add",
                color=acc,
                trigger="once",
                center="viewer",
                speed=5.0,
                width=0.6,
                decay=2.0,
                brightness=round(0.5 + 0.4 * v, 2),
            )
        )
        if at_peak and style.strobe:
            out.append(
                _clip(t, t + 4 * beat, "strobe", direct, blend="add", color="#ffffff", division=1.0, duty=0.15, brightness=0.6)
            )
    near_drop = [t for t, _ in drops]

    def free(t: float, gap: float = 1.0) -> bool:
        return all(abs(t - d) > gap for d in near_drop)

    if "crash" in tracks and opt["cues"]:
        for t, v in zip(tracks["crash"].times, tracks["crash"].strength, strict=True):
            if free(t):
                _, acc, _ = looks_at(t)
                out.append(
                    _clip(
                        float(t),
                        float(t) + 1.5,
                        "pulse",
                        indirect or everything,
                        blend="add",
                        color=acc,
                        trigger="once",
                        decay=0.45,
                        brightness=round(0.35 + 0.35 * float(v), 2),
                    )
                )
    builds = list(zip(tracks["build"].times, tracks["build"].duration, strict=True)) if "build" in tracks else []
    for b0, bd in builds:
        _, acc, _ = looks_at(float(b0))
        out.append(
            _clip(
                float(b0),
                float(b0 + bd),
                "rise",
                direct,
                blend="add",
                color=acc,
                axis=rise_axis,
                flicker=0.7,
                floor=0.03,
                curve=2.0,
                brightness=0.7,
            )
        )
    in_build = [(float(b0), float(b0 + bd)) for b0, bd in builds]

    def calm_or_full(t: float) -> bool:
        sec = f.section_at(t)
        return sec is not None and moods.get(id(sec)) in ("calm", "full") and not any(b0 <= t < b1 for b0, b1 in in_build)

    last_fill = -1e9
    if "fill" in tracks and opt["fills"]:
        for i, (t, v, d) in enumerate(zip(tracks["fill"].times, tracks["fill"].strength, tracks["fill"].duration, strict=True)):
            if any(b0 <= t < b1 for b0, b1 in in_build) or t - last_fill < 6.0:
                continue
            last_fill = float(t)
            _, _, acc2 = looks_at(t)
            dur = float(max(d, beat))
            axis = "azimuth" if (i + style.variant) % 2 == 0 else "-azimuth"
            out.append(
                _clip(
                    float(t),
                    float(t) + dur,
                    "sweep",
                    direct,
                    blend="add",
                    color=acc2,
                    trigger="once",
                    axis=axis,
                    width=0.15,
                    tail=0.4,
                    brightness=round(0.5 + 0.4 * float(v), 2),
                )
            )

    # recurring riffs: every motif has its own gesture, each time it plays
    if "motif" in tracks and opt["motifs"]:
        gestures = ["sweep_az", "ripple", "sweep_z", "room"]
        shift = style.variant % len(gestures)
        m = tracks["motif"]
        for t, v, d, n in zip(m.times, m.strength, m.duration, m.pitch, strict=True):
            t = float(t)
            if not calm_or_full(t) or not free(t, 2 * beat):
                continue
            _, acc, acc2 = looks_at(t)
            g = gestures[(round(n) - 1 + shift) % len(gestures)]
            length = float(min(d, 4 * beat))
            lvl = round(0.35 + 0.3 * float(v), 2)
            if g == "sweep_az":
                out.append(
                    _clip(
                        t,
                        t + length,
                        "sweep",
                        direct,
                        blend="add",
                        color=acc,
                        trigger="once",
                        axis="azimuth",
                        width=0.12,
                        tail=0.5,
                        brightness=lvl,
                    )
                )
            elif g == "sweep_z":
                out.append(
                    _clip(
                        t,
                        t + length,
                        "sweep",
                        direct,
                        blend="add",
                        color=acc2,
                        trigger="once",
                        axis=rise_axis,
                        width=0.2,
                        tail=0.5,
                        brightness=lvl,
                    )
                )
            elif g == "ripple":
                out.append(
                    _clip(
                        t,
                        t + length,
                        "ripple",
                        direct,
                        blend="add",
                        color=acc2,
                        trigger="once",
                        center="viewer",
                        speed=3.0,
                        width=0.4,
                        decay=1.2,
                        brightness=lvl,
                    )
                )
            elif indirect is not None:
                out.append(
                    _clip(
                        t,
                        t + 2 * beat,
                        "pulse",
                        indirect,
                        blend="add",
                        color=acc,
                        trigger="once",
                        decay=0.8,
                        brightness=round(lvl * 0.5, 2),
                    )
                )

    # phrase starts: a small gesture so the looks breathe with the song form
    if opt["phrase"]:
        starts = {round(s.start, 2) for s in analysis.sections}
        for k, (t, _) in enumerate(analysis.phrases):
            if round(t, 2) in starts or not calm_or_full(t) or not free(t, 2 * beat):
                continue
            _, acc, _ = looks_at(t)
            if opt["phrase"] == "sweep":
                axis = "azimuth" if (k + style.variant) % 2 == 0 else "-azimuth"
                out.append(
                    _clip(
                        t,
                        t + 2 * beat,
                        "sweep",
                        direct,
                        blend="add",
                        color=acc,
                        trigger="once",
                        axis=axis,
                        width=0.2,
                        tail=0.6,
                        brightness=0.4,
                    )
                )
            elif indirect is not None:
                out.append(
                    _clip(t, t + beat, "pulse", indirect, blend="add", color=acc, trigger="once", decay=0.4, brightness=0.3)
                )

    # chord changes colour the room softly (calm and cinematic)
    if opt["chords"] and indirect is not None and "chord" in tracks:
        last = -1e9
        c = tracks["chord"]
        for t, v, root in zip(c.times, c.strength, c.pitch, strict=True):
            t = float(t)
            sec = f.section_at(t)
            if sec is None or moods.get(id(sec)) not in ("dark", "calm") or t - last < 4 * beat or not free(t, 2 * beat):
                continue
            last = t
            out.append(
                _clip(
                    t,
                    t + 4 * beat,
                    "pulse",
                    indirect,
                    blend="add",
                    color=_hue(root),
                    trigger="once",
                    decay=1.6,
                    brightness=round(0.12 + 0.12 * float(v), 2),
                )
            )
    return out


def starter_show(
    name: str,
    song_id: str | None,
    analysis: Analysis | None,
    duration: float | None = None,
    project: Project | None = None,
    table=None,
    style: StarterStyle | None = None,
) -> Show:
    style = style or StarterStyle()
    if analysis is None or not analysis.sections:
        return _fallback(name, song_id, duration)
    opt = STYLES[style.style]
    f = AudioFeatures(analysis)
    fixtures = _fixture_info(project, table)
    direct = [x for x in fixtures if x["view"] >= 0.5]
    indirect = [x for x in fixtures if x["view"] < 0.5]
    if fixtures and not direct:  # nothing in view: the most visible strips carry the details
        direct = sorted(fixtures, key=lambda x: -x["view"])[: max(1, len(fixtures) // 2)]
        indirect = [x for x in fixtures if x not in direct]
    if not fixtures:  # no room information: one group for everything
        direct = [{"id": None, "leds": 300, "view": 1.0}]
    roles = _roles(direct, opt["roles"])
    z = table.pos[:, 2] if table is not None and table.count else np.zeros(1)
    rise_axis = "z" if float(np.ptp(z)) > 0.5 else "u"

    # colours: one look per section label; "auto" follows the key (minor cooler, major warmer)
    seed = zlib.crc32((song_id or name).encode()) + 7 * style.variant
    colors = style.colors
    if colors == "auto":
        mode = (analysis.harmony or {}).get("mode")
        colors = "cool" if mode == "minor" else "warm" if mode == "major" else ("cool", "warm")[seed % 2]
    looks = PALETTES[colors]
    labels = sorted({s.label for s in analysis.sections})

    def look_of(s) -> tuple:
        return looks[(labels.index(s.label) + seed) % len(looks)]

    def looks_at(t: float) -> tuple:
        sec = f.section_at(t) or analysis.sections[-1]
        return look_of(sec)

    layers = {n: Layer(name=n) for n in ("Raum", "Drums", "Melodie", "Cues")}
    moods = {}
    for s in analysis.sections:
        mood = moods[id(s)] = _mood(s, f)
        # light grows with intensity; a repeat comes a bit bigger; only the peak gets everything
        level = opt["level"] * style.brightness * (0.6 + 0.1 * s.intensity) * min(1.2, 1 + 0.08 * (s.repeat - 1))
        if mood == "full" and not s.peak:
            level *= 0.85
        sec_opt = {**opt, "hihat": opt["hihat"] or s.peak}
        for layer, clips in _section_clips(s, mood, roles, indirect, look_of(s), f, sec_opt, level).items():
            layers[layer].clips.extend(clips)

    def group(parts: list[dict]) -> Target:
        ids = sorted({p["id"] for p in parts if p["id"] is not None})
        return Target(fixtures=ids) if ids else Target()

    whole_parts = {p["id"]: p.get("part") for p in direct}
    targets = {
        "direct": Target(view="direct") if any(v for v in whole_parts.values()) or indirect else group(direct),
        "indirect": Target(view="indirect") if indirect else None,
    }
    beat = 60.0 / analysis.bpm if analysis.bpm else 0.5
    layers["Cues"].clips.extend(_cues(f, analysis, targets, looks_at, moods, beat, rise_axis, opt, style))

    names = {"party": "Party", "calm": "ruhig", "cinematic": "Kino", "minimal": "minimal"}
    return Show(
        name=name,
        song_id=song_id,
        description=f"Starter-Show ({names[style.style]}, Farben {colors}"
        + (f", Variante {style.variant}" if style.variant else "")
        + "): folgt den Instrumenten und der Songform, Höhepunkt am hellsten, leise Stellen dunkel",
        dynamics=opt["dynamics"],
        style=style,
        layers=[layers[n] for n in ("Raum", "Drums", "Melodie", "Cues") if layers[n].clips],
    )
