"""Rule-based starter show from the song analysis (no AI needed).

It is meant as a reasonable default and as an example of the show format.
"""

from lsg.model.show import Clip, Layer, Show
from lsg.model.song import Analysis

SECTION_PALETTES = ["ocean", "sunset", "neon", "fire", "ice", "party", "forest"]
ACCENTS = ["#ff0080", "#00e0ff", "#ffd800", "#8000ff", "#ff6000", "#00ff80", "#ffffff"]


def live_show(name: str = "Live (Mikrofon)", duration: float = 240.0) -> Show:
    """Endless, purely audio-driven show for the live input mode (loops after `duration`)."""
    return Show(
        name=name,
        description="Reagiert live auf das Mikrofon - frei bearbeitbar, läuft in Schleife",
        duration=duration,
        layers=[
            Layer(
                name="Basis",
                clips=[
                    Clip(
                        start=0,
                        end=duration,
                        effect="noise",
                        params={"palette": "ocean", "speed": 0.3, "brightness": {"audio": "rms", "min": 0.08, "max": 0.45}},
                    ),
                ],
            ),
            Layer(
                name="Beat",
                clips=[
                    Clip(
                        start=0,
                        end=duration,
                        effect="pulse",
                        blend="add",
                        params={
                            "color": "#ff0080",
                            "trigger": "beat",
                            "decay": 0.15,
                            "brightness": {"audio": "low", "min": 0.1, "max": 0.9},
                        },
                    ),
                ],
            ),
            Layer(
                name="Akzente",
                clips=[
                    Clip(
                        start=0,
                        end=duration,
                        effect="sparkle",
                        blend="add",
                        params={"density": {"audio": "high", "min": 0.0, "max": 0.08}, "brightness": 0.7},
                    ),
                    Clip(
                        start=0,
                        end=duration,
                        effect="ripple",
                        blend="add",
                        params={"color": "#00d4ff", "trigger": "bar", "speed": 5, "width": 0.5, "brightness": 0.6},
                    ),
                ],
            ),
        ],
    )


def starter_show(name: str, song_id: str | None, analysis: Analysis | None, duration: float | None = None) -> Show:
    if analysis is None or not analysis.sections:
        end = duration or 60.0
        return Show(
            name=name,
            song_id=song_id,
            description="Starter show (song not analysed yet)",
            layers=[
                Layer(
                    name="Base",
                    clips=[
                        Clip(start=0, end=end, effect="noise", params={"palette": "ocean", "brightness": 0.6}),
                    ],
                )
            ],
        )

    base, rhythm, accent = Layer(name="Base"), Layer(name="Rhythm"), Layer(name="Accents")
    energies = sorted(s.energy for s in analysis.sections)
    loud = energies[int(len(energies) * 0.6)] if len(energies) > 1 else energies[0]
    labels = sorted({s.label for s in analysis.sections})

    for s in analysis.sections:
        k = labels.index(s.label)
        palette = SECTION_PALETTES[k % len(SECTION_PALETTES)]
        color = ACCENTS[k % len(ACCENTS)]
        start, end = s.start, s.end
        fade = min(1.0, (end - start) / 4)
        high = s.energy >= loud and s.name not in ("intro", "outro")

        if high:
            base.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="gradient",
                    fade_in=fade,
                    params={"palette": palette, "axis": "azimuth", "beats": 8, "brightness": 0.45},
                )
            )
            rhythm.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="pulse",
                    blend="add",
                    params={"color": color, "trigger": "beat", "decay": 0.18, "brightness": 0.9},
                )
            )
            accent.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="ripple",
                    blend="add",
                    params={"color": "#ffffff", "trigger": "bar", "speed": 5, "width": 0.5, "brightness": 0.8},
                )
            )
        elif s.name in ("intro", "outro"):
            base.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="noise",
                    fade_in=fade,
                    fade_out=fade,
                    params={"palette": palette, "speed": 0.2, "brightness": {"audio": "rms", "min": 0.2, "max": 0.7}},
                )
            )
            accent.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="sparkle",
                    blend="add",
                    params={"density": {"audio": "high", "min": 0.0, "max": 0.08}, "brightness": 0.7},
                )
            )
        else:
            base.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="noise",
                    fade_in=fade,
                    params={"palette": palette, "speed": 0.4, "brightness": 0.35},
                )
            )
            rhythm.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="chase",
                    blend="add",
                    params={"color": color, "count": 2, "beats": 4, "width": 0.3, "brightness": 0.8},
                )
            )
            accent.clips.append(
                Clip(
                    start=start,
                    end=end,
                    effect="pulse",
                    blend="add",
                    params={"color": color, "trigger": "bar", "decay": 0.4, "brightness": 0.5},
                )
            )

    return Show(
        name=name, song_id=song_id, description="Starter show generated from the song structure", layers=[base, rhythm, accent]
    )
