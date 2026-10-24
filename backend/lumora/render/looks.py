"""Looks: reusable groups of clips with times in beats, so they fit songs of any tempo.

A look stores clips relative to its start (start/end and keyframe times in beats) and the
layer of each clip relative to the lowest layer of the group. Applying a look converts beats
back to seconds with the beat grid of the target song at the insertion point.
"""

import copy
from collections.abc import Callable

from pydantic import BaseModel, Field

from lumora.model.common import new_id
from lumora.model.show import Clip, Layer, Show


class LookClip(BaseModel):
    layer: int = Field(default=0, ge=0, description="layer offset above the layer the look is dropped on")
    clip: dict  # Clip JSON with start/end (and keyframe times) in beats relative to the look start


class Look(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    builtin: bool = False
    beats: float = Field(gt=0)
    clips: list[LookClip]


def _map_keyframes(params: dict, fn: Callable[[float], float]) -> dict:
    out = copy.deepcopy(params)
    for v in out.values():
        if isinstance(v, dict) and isinstance(v.get("keys"), list):
            v["keys"] = [[round(fn(float(k[0])), 4), k[1]] for k in v["keys"]]
    return out


def _tidy(beats: float) -> float:
    """Detected beat grids are never perfectly regular: snap to 1/8 beat when within 0.03."""
    q = round(beats * 8) / 8
    return q if abs(q - beats) < 0.03 else round(beats, 3)


def look_from_clips(name: str, show: Show, clip_ids: set[str], beat_at: Callable[[float], float], description: str = "") -> Look:
    """Capture clips of a show. `beat_at(t)` = continuous beat position of the song at time t."""
    picked = [(li, c) for li, layer in enumerate(show.layers) for c in layer.clips if c.id in clip_ids]
    if not picked:
        raise ValueError("no clips selected")
    t0 = min(c.start for _, c in picked)
    b0 = beat_at(t0)
    low = min(li for li, _ in picked)
    clips = []
    for li, c in picked:
        bs, be = _tidy(beat_at(c.start) - b0), _tidy(beat_at(c.end) - b0)
        spb = (c.end - c.start) / max(be - bs, 1e-6)  # seconds per beat inside this clip
        data = c.model_dump()
        data.pop("id")
        data["start"], data["end"] = round(bs, 4), round(be, 4)
        data["params"] = _map_keyframes(c.params, lambda s, spb=spb: s / spb)
        clips.append(LookClip(layer=li - low, clip=data))
    return Look(name=name, description=description, beats=round(max(lc.clip["end"] for lc in clips), 4), clips=clips)


def apply_look(
    show: Show, look: Look, at: float, layer_index: int, time_at_beat: Callable[[float], float]
) -> tuple[Show, list[str]]:
    """Insert the look at song time `at`; `time_at_beat(b)` converts a beat position to seconds."""
    show = show.model_copy(deep=True)
    ids = []
    for lc in look.clips:
        li = layer_index + lc.layer
        while li >= len(show.layers):
            show.layers.append(Layer(name=f"{look.name} {len(show.layers) + 1}"))
        data = copy.deepcopy(lc.clip)
        start_beat, end_beat = data["start"], data["end"]
        start = time_at_beat(start_beat)
        end = time_at_beat(end_beat)
        spb = (end - start) / max(end_beat - start_beat, 1e-6)
        data["start"], data["end"] = round(start, 3), round(end, 3)
        data["params"] = _map_keyframes(data.get("params", {}), lambda b, spb=spb: b * spb)
        data["id"] = new_id()
        clip = Clip.model_validate(data)
        show.layers[li].clips.append(clip)
        ids.append(clip.id)
    return show, ids


def _lc(layer: int, start: float, end: float, effect: str, params: dict, **kw) -> LookClip:
    return LookClip(layer=layer, clip={"start": start, "end": end, "effect": effect, "params": params, **kw})


BUILTIN_LOOKS = [
    Look(
        id="builtin-drop",
        name="Drop-Akzent",
        description="Stroboskop auf Sechzehnteln und ein heller Ring vom Betrachter aus - für den ersten Takt eines Drops",
        builtin=True,
        beats=4,
        clips=[
            _lc(0, 0, 2, "strobe", {"division": 4, "duty": 0.25, "brightness": 0.9}, blend="add"),
            _lc(
                1,
                0,
                4,
                "ripple",
                {"color": "#ffffff", "trigger": "beat", "speed": 6, "width": 0.6, "brightness": 1.0},
                blend="add",
            ),
        ],
    ),
    Look(
        id="builtin-bass",
        name="Bass-Puls",
        description="Pulse auf jedem Beat, Helligkeit folgt dem Bass",
        builtin=True,
        beats=16,
        clips=[
            _lc(
                0,
                0,
                16,
                "pulse",
                {"color": "#ff0080", "trigger": "beat", "decay": 0.15, "brightness": {"audio": "low", "min": 0.15, "max": 1.0}},
                blend="add",
            ),
        ],
    ),
    Look(
        id="builtin-riser",
        name="Aufbau (Riser)",
        description="Vier Takte steigende Helligkeit und Funkeln vor einem Höhepunkt",
        builtin=True,
        beats=16,
        clips=[
            _lc(
                0,
                0,
                16,
                "gradient",
                {
                    "palette": "sunset",
                    "axis": "azimuth",
                    "beats": 4,
                    "brightness": {"keys": [[0, 0.1], [16, 0.8]], "ease": "smooth"},
                },
            ),
            _lc(
                1,
                8,
                16,
                "sparkle",
                {"density": {"keys": [[0, 0.01], [8, 0.2]], "ease": "linear"}, "brightness": 0.8},
                blend="add",
            ),
        ],
    ),
    Look(
        id="builtin-calm",
        name="Ruhige Atmosphäre",
        description="Langsame, dunkle Farbwolken für Intros und Breaks",
        builtin=True,
        beats=32,
        clips=[
            _lc(
                0,
                0,
                32,
                "noise",
                {"palette": "ocean", "speed": 0.2, "brightness": {"audio": "rms", "min": 0.06, "max": 0.25}},
                fade_in=2,
                fade_out=2,
            ),
        ],
    ),
]
