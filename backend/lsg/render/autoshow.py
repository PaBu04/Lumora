"""Rule-based starter show from the song analysis and the room (no AI needed).

Design rules (the same ones the AI gets in its instructions):
  * dark by default: most of the time most LEDs are off or very dim, light is an accent;
    long strips light up the whole room even when dim, so their levels are scaled down
  * the viewer sees only some strips directly: those carry rhythm and detail (segment hits,
    chases), strips behind / beside the viewer only colour the room and flash on big hits
  * variety: every direct strip gets its own effect and the assignment rotates every phrase
    (8 bars); sections that sound alike (same label) look alike
  * drums drive the accents: kick / snare / hi-hat hits light short segments, sweeps travel
    through the room at the start of loud sections
  * patterns are measured in metres / LEDs (axis "s", hits.size), not stretched per strip
"""

import zlib

import numpy as np

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
PHRASE_BARS = 8
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


def _phrases(start: float, end: float, downbeats: np.ndarray) -> list[tuple[float, float]]:
    """Split a section into phrases of PHRASE_BARS bars (the last one takes the remainder)."""
    bars = downbeats[(downbeats >= start - 0.05) & (downbeats < end - 0.05)]
    cuts = [start] + [float(b) for b in bars[PHRASE_BARS::PHRASE_BARS] if end - b > 2.0] + [end]
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


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


def _detail_clip(scene: str, t0: float, t1: float, fid: str, look, level: float) -> Clip:
    """One rhythm/detail effect on one directly visible strip."""
    pal, acc, acc2 = look
    target = Target(fixtures=[fid])
    match scene:
        case "glow":
            return Clip(
                start=t0,
                end=t1,
                effect="noise",
                target=target,
                params={"palette": pal, "speed": 0.15, "brightness": 0.1 + 0.1 * level},
            )
        case "drift":
            return Clip(
                start=t0,
                end=t1,
                effect="wave",
                target=target,
                params={
                    "color": acc,
                    "axis": "s",
                    "wavelength": 1.2,
                    "sharpness": 3,
                    "beats": 8,
                    "brightness": 0.15 + 0.15 * level,
                },
            )
        case "onset_hits":
            return Clip(
                start=t0,
                end=t1,
                effect="hits",
                blend="max",
                target=target,
                params={
                    "palette": [acc, acc2],
                    "trigger": "onset",
                    "count": 1,
                    "size": 8,
                    "decay": 0.5,
                    "brightness": 0.35 + 0.2 * level,
                },
            )
        case "kick_hits":
            return Clip(
                start=t0,
                end=t1,
                effect="hits",
                blend="max",
                target=target,
                params={
                    "palette": [acc, "#ffffff"],
                    "trigger": "kick",
                    "count": 2 + round(2 * level),
                    "size": 10 + round(8 * level),
                    "decay": 0.22,
                    "brightness": 0.6 + 0.35 * level,
                },
            )
        case "snare_hits":
            return Clip(
                start=t0,
                end=t1,
                effect="hits",
                blend="max",
                target=target,
                params={
                    "palette": [acc2, acc],
                    "trigger": "snare",
                    "count": 2 + round(2 * level),
                    "size": 6 + round(6 * level),
                    "decay": 0.18,
                    "brightness": 0.6 + 0.35 * level,
                },
            )
        case "hat_glitter":
            return Clip(
                start=t0,
                end=t1,
                effect="hits",
                blend="max",
                target=target,
                params={
                    "palette": ["#ffffff", acc],
                    "trigger": "hihat",
                    "count": 3,
                    "size": 2,
                    "decay": 0.1,
                    "brightness": 0.5 + 0.3 * level,
                },
            )
        case "chase":
            return Clip(
                start=t0,
                end=t1,
                effect="chase",
                blend="max",
                target=target,
                params={
                    "color": acc,
                    "axis": "s",
                    "count": 0.5 + 0.5 * level,
                    "width": 0.25,
                    "tail": 0.9,
                    "beats": 4 if level < 0.7 else 2,
                    "brightness": 0.45 + 0.4 * level,
                },
            )
    raise ValueError(scene)


SCENES = {
    "low": ["glow", "drift", "onset_hits"],
    "mid": ["kick_hits", "chase", "snare_hits", "drift"],
    "high": ["kick_hits", "snare_hits", "chase", "hat_glitter"],
}


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
    fixtures = _fixture_info(project, table)
    direct = [f for f in fixtures if f["view"] >= 0.5]
    indirect = [f for f in fixtures if f["view"] < 0.5]
    if fixtures and not direct:  # nothing in view: the most visible strips carry the details
        direct = sorted(fixtures, key=lambda f: -f["view"])[: max(1, len(fixtures) // 2)]
        indirect = [f for f in fixtures if f not in direct]
    if not fixtures:  # no room information: one group for everything
        direct = [{"id": None, "leds": 300, "view": 1.0}]

    room, rhythm, accent = Layer(name="Raum"), Layer(name="Rhythmus"), Layer(name="Akzente")
    energies = sorted(s.energy for s in analysis.sections)
    q_lo = energies[int(len(energies) * 0.35)]
    q_hi = energies[int(len(energies) * 0.7)]
    labels = sorted({s.label for s in analysis.sections})
    seed = zlib.crc32((song_id or name).encode())
    downbeats = np.asarray(analysis.downbeats, dtype=float)

    for si, s in enumerate(analysis.sections):
        k = labels.index(s.label)
        look = LOOKS[(k + seed) % len(LOOKS)]
        quiet = s.name in ("intro", "outro", "break")
        kind = "low" if quiet or s.energy <= q_lo else "high" if s.energy >= q_hi else "mid"
        level = {"low": 0.2, "mid": 0.55, "high": 0.9}[kind]
        fade = min(1.5, (s.end - s.start) / 4)

        # room colour on the strips behind the viewer: dim wash, flashes only when it is loud
        for f in indirect or ([] if fixtures else direct):
            tgt = _target(f)
            room.clips.append(
                Clip(
                    start=s.start,
                    end=s.end,
                    effect="noise",
                    target=tgt,
                    fade_in=fade,
                    fade_out=fade if quiet else 0.0,
                    params={"palette": look[0], "speed": 0.15, "scale": 0.6, "brightness": _dim(0.06 + 0.1 * level, f["leds"])},
                )
            )
            if kind == "high":
                room.clips.append(
                    Clip(
                        start=s.start,
                        end=s.end,
                        effect="pulse",
                        blend="add",
                        target=tgt,
                        params={"color": look[1], "trigger": "kick", "decay": 0.12, "brightness": _dim(0.55, f["leds"])},
                    )
                )

        # details on the strips in view, a different effect per strip, rotating every phrase
        for pi, (t0, t1) in enumerate(_phrases(s.start, s.end, downbeats)):
            pool = SCENES[kind]
            for fi, f in enumerate(direct):
                scene = pool[(pi + 2 * fi + k) % len(pool)]
                clip = _detail_clip(scene, t0, t1, f["id"], look, level)
                clip.target = _target(f)
                if clip.effect in ("noise", "wave"):  # washes: mind long strips
                    clip.params["brightness"] = _dim(clip.params["brightness"], f["leds"])
                rhythm.clips.append(clip)
            # a sweep through the whole room opens every loud phrase
            if kind == "high":
                bar = 4 * 60.0 / analysis.bpm if analysis.bpm else 2.0
                axis = ["z", "azimuth", "-z", "-azimuth"][(pi + si) % 4]
                accent.clips.append(
                    Clip(
                        start=t0,
                        end=min(t1, t0 + 2 * bar),
                        effect="sweep",
                        blend="add",
                        params={
                            "color": look[2],
                            "axis": axis,
                            "trigger": "bar",
                            "beats": 3,
                            "width": 0.12,
                            "tail": 0.25,
                            "brightness": 0.7,
                        },
                    )
                )

        # a quiet glimmer keeps breaks alive without lighting the room
        if quiet and direct and direct[0]["id"] is not None:
            accent.clips.append(
                Clip(
                    start=s.start,
                    end=s.end,
                    effect="hits",
                    blend="max",
                    target=Target(fixtures=sorted({f["id"] for f in direct})),
                    params={"palette": [look[1]], "trigger": "hihat", "count": 1, "size": 3, "decay": 0.3, "brightness": 0.3},
                )
            )

    return Show(
        name=name,
        song_id=song_id,
        description="Starter show from the song structure and the room (dark base, drum hits, varied per strip)",
        layers=[room, rhythm, accent],
    )
