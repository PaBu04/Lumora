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
  * sections that sound alike (same label) look alike
"""

import zlib

import numpy as np

from lsg.audio.features import AudioFeatures
from lsg.model.project import Project
from lsg.model.show import Clip, Layer, Show, Target
from lsg.model.song import Analysis

# tasteful colour pairs per section look: (palette for washes, accent colour, second accent)
LOOKS = [
    (["#001a40", "#0050a0", "#00a0c0"], "#40c0ff", "#ffffff"),
    (["#200030", "#600060", "#c03070"], "#ff4080", "#ffb000"),
    (["#301000", "#803000", "#ff7000"], "#ffa030", "#ff3000"),
    (["#002018", "#006048", "#00b080"], "#40ffc0", "#80a0ff"),
    (["#100030", "#3000a0", "#7040ff"], "#a080ff", "#ff60c0"),
    (["#202020", "#404858", "#8090b0"], "#ffffff", "#40c0ff"),
]
LONG_STRIP = 120  # LEDs; longer strips get dimmer washes


def live_show(name: str = "Live (Mikrofon)", duration: float = 240.0) -> Show:
    """Endless, purely audio-driven show for the live input mode (loops after `duration`)."""
    return Show(
        name=name,
        description="Reagiert live auf die Musik - frei bearbeitbar, läuft in Schleife",
        duration=duration,
        layers=[
            Layer(
                name="Basis",
                clips=[
                    Clip(
                        start=0,
                        end=duration,
                        effect="noise",
                        params={"palette": LOOKS[0][0], "speed": 0.2, "brightness": {"audio": "rms", "min": 0.04, "max": 0.18}},
                    ),
                ],
            ),
            Layer(
                name="Treffer",
                clips=[
                    Clip(
                        start=0,
                        end=duration,
                        effect="hits",
                        blend="max",
                        params={"palette": ["#40c0ff", "#ffffff"], "trigger": "kick", "count": 3, "size": 14, "decay": 0.22},
                    ),
                    Clip(
                        start=0,
                        end=duration,
                        effect="hits",
                        blend="max",
                        params={
                            "palette": ["#ff4080"],
                            "trigger": "snare",
                            "count": 2,
                            "size": 8,
                            "decay": 0.18,
                            "brightness": 0.8,
                        },
                    ),
                    Clip(
                        start=0,
                        end=duration,
                        effect="hits",
                        blend="add",
                        params={
                            "palette": ["#ffffff"],
                            "trigger": "hihat",
                            "count": 2,
                            "size": 2,
                            "decay": 0.08,
                            "brightness": 0.4,
                        },
                    ),
                ],
            ),
        ],
    )


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


def _roles(direct: list[dict]) -> dict[str, list[dict]]:
    """Give every strip in view an instrument to show: the longest strip the drums (small hits
    spread over many LEDs), then melody (vocal / lead notes), bass notes and accents. With fewer
    strips, strips take several roles; with more, roles repeat."""
    parts = sorted(direct, key=lambda f: -f["leds"])
    out: dict[str, list[dict]] = {r: [] for r in ROLES}
    for i, f in enumerate(parts):
        out[ROLES[i % len(ROLES)]].append(f)
    for i, r in enumerate(ROLES):
        if not out[r]:
            out[r] = [parts[i % len(parts)]]
    return out


def _mean(features: AudioFeatures, name: str, a: float, b: float) -> float:
    c = features.curves.get(name)
    if c is None or len(c) < 2:
        return 0.0
    i, j = int(a * features.frame_rate), max(int(a * features.frame_rate) + 1, int(b * features.frame_rate))
    return float(np.mean(c[i:j])) if i < len(c) else 0.0


def _mood(s, features: AudioFeatures, q_hi: float) -> str:
    """dark (quiet, no drums), calm, full (loudest parts) or build."""
    if s.name == "build":
        return "build"
    loud = _mean(features, "loudness", s.start, s.end)
    drums = _mean(features, "drums", s.start, s.end) if features.has_instruments else _mean(features, "density", s.start, s.end)
    if s.name in ("intro", "outro", "break") and loud < 0.75:
        return "dark"
    if drums < 0.12:  # no beat: let the melody glow, keep the room dark
        return "dark" if loud < 0.85 else "calm"
    if s.name == "drop" or s.energy >= q_hi:
        return "full"
    return "calm"


def _clip(start, end, effect, target, blend="max", **params) -> Clip:
    return Clip(start=start, end=end, effect=effect, target=target, blend=blend, params=params)


def _section_clips(s, mood: str, roles: dict, indirect: list[dict], look, f: AudioFeatures) -> dict:
    """Long clips driven by instrument tracks for one section, per layer name."""
    pal, acc, acc2 = look
    a, b = s.start, s.end
    out: dict[str, list[Clip]] = {"Raum": [], "Drums": [], "Melodie": []}
    tracks = f.tracks if f.has_instruments else {}
    singing = [e for e in zip(*tracks["phrase"], strict=True) if e[0] < b and e[0] + e[2] > a] if "phrase" in tracks else []
    bass_on = "bass" in tracks and _mean(f, "bass", a, b) > 0.15

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
                    decay=0.18,
                    brightness=0.9 if big else 0.7,
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
                    decay=0.15,
                    brightness=0.85 if big else 0.6,
                )
            )
            if big:
                out["Drums"].append(
                    _clip(a, b, "hits", tgt, palette=["#ffffff"], trigger="hihat", count=2, size=2, decay=0.07, brightness=0.35)
                )
        elif mood == "build":  # the rise itself is a cue over all strips in view
            out["Drums"].append(
                _clip(a, b, "hits", tgt, palette=["#ffffff", acc2], trigger="snare", count=1, size=6, decay=0.1, brightness=0.8)
            )

    # melody: sung notes while singing, the lead instrument (keys, synths, guitars) in between
    for p in roles["melody"]:
        tgt = _target(p)
        level = {"dark": 0.4, "calm": 0.6, "full": 0.85, "build": 0.5}[mood]
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
                        decay=0.35,
                        max_hold=1.0,
                        brightness=level,
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
                        track="lead",
                        palette=[pal[1], acc],
                        axis="u",
                        width=0.06,
                        decay=0.25,
                        max_hold=0.5,
                        brightness=round(level * 0.8, 2),
                    )
                )
            elif not tracks and mood != "dark":
                out["Melodie"].append(
                    _clip(c0, c1, "hits", tgt, palette=[acc, acc2], trigger="onset", count=1, size=8, decay=0.4, brightness=level)
                )

    # bass notes, low on the strip = low note
    if bass_on and mood in ("calm", "full"):
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
                    decay=0.2,
                    max_hold=0.6,
                    brightness=0.75 if mood == "full" else 0.5,
                )
            )

    # accents: snare / clap flashes on the small strips, a soft glow while singing in quiet parts
    for p in roles["accent"]:
        tgt = _target(p)
        if mood in ("calm", "full"):
            out["Drums"].append(
                _clip(
                    a,
                    b,
                    "pulse",
                    tgt,
                    color=acc2,
                    trigger="snare",
                    decay=0.12,
                    velocity=0.8,
                    brightness=0.8 if mood == "full" else 0.55,
                )
            )
        elif mood == "dark" and singing:
            out["Melodie"].append(
                _clip(a, b, "pulse", tgt, color=pal[-1], trigger="phrase", sustain=True, decay=1.2, velocity=0.3, brightness=0.2)
            )

    # room colour behind / beside the viewer: dim, follows the bass, flashes on kicks when full
    for p in indirect:
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
                    brightness={"audio": "bass" if bass_on else "loudness", "min": 0.03, "max": _dim(0.14, p["leds"])},
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
                    brightness=_dim(0.5, p["leds"]),
                )
            )
        elif mood == "calm":
            out["Raum"].append(
                _clip(a, b, "noise", tgt, blend="normal", palette=pal, speed=0.1, scale=0.6, brightness=_dim(0.06, p["leds"]))
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
                    brightness={"audio": "tension", "min": 0.03, "max": _dim(0.5, p["leds"])},
                )
            )
    return out


def _cues(
    f: AudioFeatures, everything: Target, direct: Target, indirect: Target | None, looks_at, beat: float, rise_axis: str
) -> list[Clip]:
    """One-shot clips at single moments: drops, crashes, drum fills."""
    tracks = f.tracks if f.has_instruments else {}
    out: list[Clip] = []
    drops = [(t, v) for t, v, _, _ in zip(*tracks["drop"], strict=True)] if "drop" in tracks else []
    for t, v in drops:
        if v < 0.4:
            continue
        _, acc, acc2 = looks_at(t)
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
                brightness=round(0.5 + 0.5 * v, 2),
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
    near_drop = [t for t, _ in drops]
    if "crash" in tracks:
        for t, v in zip(tracks["crash"].times, tracks["crash"].strength, strict=True):
            if all(abs(t - d) > 1.0 for d in near_drop):
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
    last_fill = -1e9
    if "fill" in tracks:
        for i, (t, v, d) in enumerate(zip(tracks["fill"].times, tracks["fill"].strength, tracks["fill"].duration, strict=True)):
            if any(b0 <= t < b0 + bd for b0, bd in builds) or t - last_fill < 6.0:
                continue
            last_fill = float(t)
            _, _, acc2 = looks_at(t)
            dur = float(max(d, beat))
            out.append(
                _clip(
                    float(t),
                    float(t) + dur,
                    "sweep",
                    direct,
                    blend="add",
                    color=acc2,
                    trigger="once",
                    axis="azimuth" if i % 2 == 0 else "-azimuth",
                    width=0.15,
                    tail=0.4,
                    brightness=round(0.5 + 0.4 * float(v), 2),
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
) -> Show:
    if analysis is None or not analysis.sections:
        return _fallback(name, song_id, duration)
    f = AudioFeatures(analysis)
    fixtures = _fixture_info(project, table)
    direct = [x for x in fixtures if x["view"] >= 0.5]
    indirect = [x for x in fixtures if x["view"] < 0.5]
    if fixtures and not direct:  # nothing in view: the most visible strips carry the details
        direct = sorted(fixtures, key=lambda x: -x["view"])[: max(1, len(fixtures) // 2)]
        indirect = [x for x in fixtures if x not in direct]
    if not fixtures:  # no room information: one group for everything
        direct = [{"id": None, "leds": 300, "view": 1.0}]
    roles = _roles(direct)
    z = table.pos[:, 2] if table is not None and table.count else np.zeros(1)
    rise_axis = "z" if float(np.ptp(z)) > 0.5 else "u"

    energies = sorted(s.energy for s in analysis.sections)
    q_hi = energies[int(len(energies) * 0.7)]
    labels = sorted({s.label for s in analysis.sections})
    seed = zlib.crc32((song_id or name).encode())

    def look_of(s) -> tuple:
        return LOOKS[(labels.index(s.label) + seed) % len(LOOKS)]

    def looks_at(t: float) -> tuple:
        sec = f.section_at(t) or analysis.sections[-1]
        return look_of(sec)

    layers = {n: Layer(name=n) for n in ("Raum", "Drums", "Melodie", "Cues")}
    for s in analysis.sections:
        mood = _mood(s, f, q_hi)
        for layer, clips in _section_clips(s, mood, roles, indirect, look_of(s), f).items():
            layers[layer].clips.extend(clips)

    def group(parts: list[dict]) -> Target:
        ids = sorted({p["id"] for p in parts if p["id"] is not None})
        return Target(fixtures=ids) if ids else Target()

    whole_parts = {p["id"]: p.get("part") for p in direct}
    direct_t = Target(view="direct") if any(v for v in whole_parts.values()) or indirect else group(direct)
    indirect_t = Target(view="indirect") if indirect else None
    beat = 60.0 / analysis.bpm if analysis.bpm else 0.5
    layers["Cues"].clips.extend(_cues(f, Target(), direct_t, indirect_t, looks_at, beat, rise_axis))

    return Show(
        name=name,
        song_id=song_id,
        description="Starter show from the instruments and the room: drums as small hits, melody and bass as notes, "
        "cues on drops, crashes and fills; dark where the music is quiet",
        dynamics=0.6,
        layers=[layers[n] for n in ("Raum", "Drums", "Melodie", "Cues") if layers[n].clips],
    )
