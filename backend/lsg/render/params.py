"""Effect parameter specs and the compilation of (possibly dynamic) parameter values."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from lsg.audio.features import AudioFrame
from lsg.render.colors import parse_color, parse_palette
from lsg.render.context import AXES, RenderContext

ParamType = str  # number | color | palette | axis | enum | bool | point

AUDIO_SOURCES = (
    "rms",
    "low",
    "mid",
    "high",
    "onset",
    "beat_phase",
    "bar_phase",
    "beat_decay",
    "bar_decay",
    "onset_decay",
    "section_energy",
)
LFO_SHAPES = ("sine", "triangle", "saw", "square")
EASES = ("linear", "smooth", "step")


@dataclass(frozen=True)
class Param:
    name: str
    type: ParamType
    default: Any
    description: str
    min: float | None = None
    max: float | None = None
    options: tuple[str, ...] | None = None
    dynamic: bool = True  # may use audio / keyframes / lfo

    def schema(self) -> dict:
        d = {"type": self.type, "default": self.default, "description": self.description}
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.options:
            d["options"] = list(self.options)
        if not self.dynamic:
            d["dynamic"] = False
        return d


def audio_value(source: str, a: AudioFrame) -> float:
    match source:
        case "beat_phase":
            return a.beat_phase
        case "bar_phase":
            return a.bar_phase
        case "beat_decay":
            return math.exp(-a.since_beat / 0.15)
        case "bar_decay":
            return math.exp(-a.since_bar / 0.4)
        case "onset_decay":
            return math.exp(-a.since_onset / 0.12)
        case "section_energy":
            return a.section_energy
        case _:
            return getattr(a, source)


def _ease(f: float, mode: str) -> float:
    if mode == "step":
        return 0.0
    if mode == "smooth":
        return f * f * (3 - 2 * f)
    return f


def _lfo(shape: str, x: float) -> float:
    x %= 1.0
    match shape:
        case "sine":
            return 0.5 - 0.5 * math.cos(2 * math.pi * x)
        case "triangle":
            return 1 - abs(2 * x - 1)
        case "saw":
            return x
        case _:
            return 1.0 if x < 0.5 else 0.0


def _is_dynamic(v: Any) -> bool:
    return isinstance(v, dict) and bool({"audio", "keys", "lfo"} & v.keys())


class ParamError(ValueError):
    pass


def _coerce(p: Param, v: Any):
    """Turn a literal into its runtime representation (raises ParamError)."""
    try:
        match p.type:
            case "number":
                if isinstance(v, bool) or not isinstance(v, (int, float, np.floating)):
                    raise ParamError(f"{p.name}: expected a number, got {v!r}")
                x = float(v)
                if p.min is not None:
                    x = max(p.min, x)
                if p.max is not None:
                    x = min(p.max, x)
                return x
            case "color":
                return parse_color(v)
            case "palette":
                return parse_palette(v)
            case "bool":
                if not isinstance(v, bool):
                    raise ParamError(f"{p.name}: expected true/false")
                return v
            case "enum":
                if v not in p.options:
                    raise ParamError(f"{p.name}: {v!r} is not one of {list(p.options)}")
                return v
            case "axis":
                if isinstance(v, str) and v.lstrip("-") in AXES:
                    return v
                if isinstance(v, (list, tuple)) and len(v) == 3 and any(abs(float(c)) > 0 for c in v):
                    return tuple(float(c) for c in v)
                raise ParamError(f"{p.name}: axis must be one of {list(AXES)} (optionally prefixed '-') or [x, y, z]")
            case "point":
                if v in ("viewer", "center"):
                    return v
                if isinstance(v, (list, tuple, np.ndarray)) and len(v) == 3:
                    return np.asarray(v, dtype=np.float32)
                raise ParamError(f"{p.name}: point must be [x, y, z], 'viewer' or 'center'")
    except ParamError:
        raise
    except (ValueError, TypeError) as exc:
        raise ParamError(f"{p.name}: {exc}") from exc
    raise ParamError(f"{p.name}: unsupported parameter type {p.type}")


def _interp_values(p: Param, a, b, f: float):
    if p.type == "number":
        return a + (b - a) * f
    if p.type in ("color", "point") and isinstance(a, np.ndarray) and isinstance(b, np.ndarray):
        return a + (b - a) * f
    return a if f < 1 else b


Compiled = Callable[[RenderContext], Any]


def compile_param(p: Param, value: Any) -> Compiled:
    """Compile a parameter value into a function of the render context."""
    if not _is_dynamic(value):
        lit = _coerce(p, value)
        return lambda ctx: lit
    if not p.dynamic:
        raise ParamError(f"{p.name}: this parameter cannot be animated")

    if "audio" in value:
        src = value["audio"]
        if src not in AUDIO_SOURCES:
            raise ParamError(f"{p.name}: audio source must be one of {list(AUDIO_SOURCES)}")
        if p.type != "number":
            raise ParamError(f"{p.name}: audio binding only works for number parameters")
        lo, hi = float(value.get("min", p.min if p.min is not None else 0.0)), float(value.get("max", 1.0))
        power = float(value.get("pow", 1.0))
        return lambda ctx: _coerce(p, lo + (hi - lo) * (min(max(audio_value(src, ctx.audio), 0.0), 1.0) ** power))

    if "lfo" in value:
        shape = value["lfo"]
        if shape not in LFO_SHAPES:
            raise ParamError(f"{p.name}: lfo must be one of {list(LFO_SHAPES)}")
        if p.type != "number":
            raise ParamError(f"{p.name}: lfo only works for number parameters")
        lo, hi = float(value.get("min", 0.0)), float(value.get("max", 1.0))
        beats = float(value.get("beats", 1.0))
        seconds = value.get("seconds")
        phase = float(value.get("phase", 0.0))
        if beats <= 0 and not seconds:
            raise ParamError(f"{p.name}: lfo needs beats > 0 or seconds > 0")

        def lfo(ctx: RenderContext):
            x = ctx.lt / float(seconds) if seconds else ctx.audio.beat / beats
            return _coerce(p, lo + (hi - lo) * _lfo(shape, x + phase))

        return lfo

    keys = value["keys"]
    ease = value.get("ease", "linear")
    if ease not in EASES:
        raise ParamError(f"{p.name}: ease must be one of {list(EASES)}")
    if not isinstance(keys, list) or not keys or not all(isinstance(k, (list, tuple)) and len(k) == 2 for k in keys):
        raise ParamError(f"{p.name}: keys must be a list of [time, value] pairs")
    pts = sorted(((float(k[0]), _coerce(p, k[1])) for k in keys), key=lambda k: k[0])
    times = [k[0] for k in pts]

    def keyed(ctx: RenderContext):
        t = ctx.lt
        if t <= times[0]:
            return pts[0][1]
        if t >= times[-1]:
            return pts[-1][1]
        i = int(np.searchsorted(times, t, side="right") - 1)
        (t0, a), (t1, b) = pts[i], pts[i + 1]
        return _interp_values(p, a, b, _ease((t - t0) / (t1 - t0), ease))

    return keyed


def compile_params(specs: tuple[Param, ...], values: dict[str, Any], strict: bool = True) -> dict[str, Compiled]:
    known = {p.name for p in specs}
    unknown = set(values) - known
    if unknown and strict:
        raise ParamError(f"unknown parameter(s) {sorted(unknown)}; allowed: {sorted(known)}")
    return {p.name: compile_param(p, values.get(p.name, p.default)) for p in specs}
