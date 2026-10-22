"""The effect library.

Every effect returns (rgb, alpha) for the LEDs of its clip: rgb (n, 3) float 0..1 and
alpha (n,) 0..1 or None (= fully opaque). The engine blends the result into the frame.
"""

import math

import numpy as np

from lsg.render.colors import hsv_to_rgb, palette_at
from lsg.render.context import RenderContext
from lsg.render.params import Param

Result = tuple[np.ndarray, np.ndarray | None]

# shared parameter definitions
BRIGHTNESS = Param("brightness", "number", 1.0, "overall intensity 0..1", 0.0, 1.0)
SPEED = Param("speed", "number", 0.5, "cycles per second (ignored when beats > 0)", -20.0, 20.0)
BEATS = Param("beats", "number", 0.0, "if > 0: one cycle takes this many beats (tempo-locked)", 0.0, 64.0)
TRIGGERS = ("beat", "bar", "onset", "half_beat", "two_beats", "kick", "snare", "hihat")
EVENTS = ("beat", "bar", "onset", "kick", "snare", "hihat")  # triggers with a list of past event times


def _fill(color: np.ndarray, n: int) -> np.ndarray:
    return np.broadcast_to(color.astype(np.float32), (n, 3)).copy()


def _hash(*arrays) -> np.ndarray:
    """Deterministic pseudo-random 0..1 from integer arrays (vectorised)."""
    h = np.uint32(2166136261)
    with np.errstate(over="ignore"):
        for a in arrays:
            h = (h ^ np.asarray(a).astype(np.uint32)) * np.uint32(16777619)
            h ^= h >> np.uint32(13)
            h *= np.uint32(0x5BD1E995)
            h ^= h >> np.uint32(15)
    return (h & np.uint32(0xFFFFFF)).astype(np.float32) / np.float32(0x1000000)


def _since_trigger(ctx: RenderContext, trigger: str) -> float:
    a = ctx.audio
    period = ctx.features.beat_period
    match trigger:
        case "beat":
            return a.since_beat
        case "bar":
            return a.since_bar
        case "onset":
            return a.since_onset
        case "half_beat":
            return (a.beat_phase % 0.5) * period
        case "two_beats":
            return ((a.beat % 2.0) if a.beat >= 0 else 0.0) * period
        case "kick":
            return a.since_kick
        case "snare":
            return a.since_snare
        case "hihat":
            return a.since_hihat
    raise ValueError(trigger)


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0) if e1 != e0 else (x >= e0).astype(np.float32)
    return t * t * (3 - 2 * t)


class Effect:
    id: str = ""
    name: str = ""
    description: str = ""
    params: tuple[Param, ...] = ()

    def render(self, ctx: RenderContext, p: dict) -> Result:
        raise NotImplementedError

    def info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "params": {p.name: p.schema() for p in self.params},
        }


class Solid(Effect):
    id, name = "solid", "Solid colour"
    description = "Fills the target with one colour. Use colour 'black' to black out."
    params = (Param("color", "color", "#ffffff", "colour"), BRIGHTNESS)

    def render(self, ctx, p):
        return _fill(p["color"] * p["brightness"], ctx.leds.n), None


class Gradient(Effect):
    id, name = "gradient", "Gradient"
    description = "Palette spread along an axis, optionally scrolling."
    params = (
        Param("palette", "palette", "rainbow", "palette name or list of colours", dynamic=False),
        Param("axis", "axis", "x", "axis the palette is spread along", dynamic=False),
        Param("repeat", "number", 1.0, "how often the palette repeats along the axis", 0.05, 50.0),
        Param("speed", "number", 0.0, "scroll speed in cycles per second", -20.0, 20.0),
        BEATS,
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        x = ctx.leds.coord(p["axis"]) * p["repeat"] - ctx.cycle(p["speed"], p["beats"])
        return palette_at(p["palette"], x) * p["brightness"], None


class Rainbow(Effect):
    id, name = "rainbow", "Rainbow"
    description = "Moving hue rainbow along an axis."
    params = (
        Param("axis", "axis", "u", "axis of the rainbow", dynamic=False),
        Param("scale", "number", 1.0, "number of full rainbows along the axis", 0.05, 50.0),
        Param("speed", "number", 0.25, "hue cycles per second", -20.0, 20.0),
        BEATS,
        Param("saturation", "number", 1.0, "colour saturation", 0.0, 1.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        h = ctx.leds.coord(p["axis"]) * p["scale"] - ctx.cycle(p["speed"], p["beats"])
        return hsv_to_rgb(h, p["saturation"], p["brightness"]), None


class Pulse(Effect):
    id, name = "pulse", "Pulse"
    description = "Flashes on every beat / bar / onset and decays exponentially."
    params = (
        Param("color", "color", "#ffffff", "flash colour"),
        Param("trigger", "enum", "beat", "what triggers a flash", options=TRIGGERS, dynamic=False),
        Param("decay", "number", 0.25, "decay time constant in seconds", 0.01, 5.0),
        Param("floor", "number", 0.0, "minimum level between flashes", 0.0, 1.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        since = _since_trigger(ctx, p["trigger"])
        level = p["floor"] + (1 - p["floor"]) * (math.exp(-since / p["decay"]) if math.isfinite(since) else 0.0)
        return _fill(p["color"] * p["brightness"], ctx.leds.n), np.full(ctx.leds.n, level, np.float32)


class Strobe(Effect):
    id, name = "strobe", "Strobe"
    description = "Hard on/off flashing at a fixed rate or locked to the beat."
    params = (
        Param("color", "color", "#ffffff", "flash colour"),
        Param("rate", "number", 10.0, "flashes per second (ignored when division > 0)", 0.1, 30.0),
        Param("division", "number", 0.0, "if > 0: flashes per beat (e.g. 4 = sixteenth notes)", 0.0, 16.0),
        Param("duty", "number", 0.3, "fraction of each cycle the light is on", 0.01, 1.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        phase = (ctx.audio.beat * p["division"]) % 1.0 if p["division"] > 0 else (ctx.lt * p["rate"]) % 1.0
        on = 1.0 if phase < p["duty"] else 0.0
        return _fill(p["color"] * p["brightness"], ctx.leds.n), np.full(ctx.leds.n, on, np.float32)


class Chase(Effect):
    id, name = "chase", "Chase"
    description = (
        "Lit segments running along an axis (default: along each strip). bounce=true gives a scanner. "
        "With axis 's' (metres) count = segments per metre, so long and short strips look alike."
    )
    params = (
        Param("color", "color", "#ffffff", "segment colour"),
        Param("axis", "axis", "u", "path of the chase", dynamic=False),
        Param("count", "number", 1.0, "number of segments", 1.0, 64.0),
        Param("width", "number", 0.15, "segment length as fraction of the spacing between segments", 0.01, 1.0),
        Param("tail", "number", 0.8, "0 = hard block, 1 = fading tail", 0.0, 1.0),
        SPEED,
        BEATS,
        Param("bounce", "bool", False, "move back and forth instead of wrapping", dynamic=False),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        x = ctx.leds.coord(p["axis"])
        c = ctx.cycle(p["speed"], p["beats"])
        w = p["width"]
        if p["bounce"]:
            head = 1 - abs(2 * (c % 1.0) - 1)
            d = np.abs(x - head) / max(w / 2, 1e-6)
            level = np.where(d < 1, 1 - p["tail"] * d, 0.0)
        else:
            k = round(p["count"])
            rel = ((c - x) * k) % 1.0  # distance behind the head, in segment spacings
            d = rel / w
            level = np.where(d < 1, 1 - p["tail"] * d, 0.0)
        return _fill(p["color"] * p["brightness"], ctx.leds.n), level.astype(np.float32)


class Wave(Effect):
    id, name = "wave", "Wave"
    description = (
        "Soft bands travelling along an axis, e.g. axis 'azimuth' sweeps left to right through the viewer's field of view."
    )
    params = (
        Param("color", "color", "#00a0ff", "wave colour"),
        Param("axis", "axis", "x", "direction of travel", dynamic=False),
        Param("wavelength", "number", 0.5, "distance between bands, fraction of the axis", 0.02, 4.0),
        Param("sharpness", "number", 2.0, "1 = sine, higher = narrower bands", 0.5, 50.0),
        SPEED,
        BEATS,
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        x = ctx.leds.coord(p["axis"])
        phase = x / p["wavelength"] - ctx.cycle(p["speed"], p["beats"])
        level = (0.5 + 0.5 * np.cos(2 * np.pi * phase)) ** p["sharpness"]
        return _fill(p["color"] * p["brightness"], ctx.leds.n), level.astype(np.float32)


class Ripple(Effect):
    id, name = "ripple", "Ripple"
    description = "Spherical rings expanding from a point (default: the viewer) on every trigger."
    params = (
        Param("color", "color", "#ff00ff", "ring colour"),
        Param("center", "point", "viewer", "origin: [x, y, z] in metres, 'viewer' or 'center'"),
        Param(
            "trigger",
            "enum",
            "beat",
            "beat / bar / onset / kick / snare / hihat or interval",
            options=(*EVENTS, "interval"),
            dynamic=False,
        ),
        Param("interval", "number", 1.0, "seconds between rings when trigger = interval", 0.05, 30.0),
        Param("speed", "number", 4.0, "ring speed in metres per second", 0.1, 50.0),
        Param("width", "number", 0.4, "ring thickness in metres", 0.02, 10.0),
        Param("decay", "number", 1.5, "seconds until a ring has faded", 0.05, 10.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        center = p["center"]
        if isinstance(center, str):
            center = ctx.viewer_pos if center == "viewer" else self._room_center(ctx)
        d = np.linalg.norm(ctx.leds.pos - center, axis=1)
        if p["trigger"] == "interval":
            k = math.floor(ctx.lt / p["interval"])
            n = int(p["decay"] / p["interval"]) + 1
            times = ctx.t - ctx.lt + p["interval"] * np.arange(max(0, k - n), k + 1)
        else:
            times = ctx.features.recent(p["trigger"], ctx.t, p["decay"])
        level = np.zeros(ctx.leds.n, np.float32)
        for tk in times[-12:]:
            age = ctx.t - tk
            if age < 0 or age > p["decay"]:
                continue
            ring = np.exp(-(((d - p["speed"] * age) / p["width"]) ** 2)) * (1 - age / p["decay"])
            level = np.maximum(level, ring)
        return _fill(p["color"] * p["brightness"], ctx.leds.n), level

    @staticmethod
    def _room_center(ctx: RenderContext) -> np.ndarray:
        s = ctx.leds.spatial
        z = float(s.table.pos[:, 2].mean()) if s.table.count else 1.0
        return np.array([s.center[0], s.center[1], z], dtype=np.float32)


class Hits(Effect):
    id, name = "hits", "Hits"
    description = (
        "On every drum hit (kick / snare / hihat / beat / onset) a few short segments of `size` LEDs light up at "
        "random places and fade. Small, local accents instead of whole strips flashing - ideal for snares and kicks."
    )
    params = (
        Param("palette", "palette", ["#ffffff"], "colours of the segments (picked at random)", dynamic=False),
        Param("trigger", "enum", "snare", "what lights segments", options=EVENTS, dynamic=False),
        Param("count", "number", 3.0, "segments per hit", 1.0, 32.0),
        Param("size", "number", 12.0, "segment length in LEDs", 1.0, 300.0),
        Param("decay", "number", 0.25, "fade time in seconds", 0.02, 4.0),
        Param("soft", "number", 0.3, "0 = hard segment edges, 1 = soft fade towards the ends", 0.0, 1.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        leds = ctx.leds
        n = leds.n
        level = np.zeros(n, np.float32)
        key = np.zeros(n, np.float32)  # random value that picks the colour of the winning segment
        times = ctx.features.recent(p["trigger"], ctx.t, p["decay"] * 5)[-8:]
        count, size = round(p["count"]), max(1, round(p["size"]))
        fi, ii = leds.fixture_index, leds.index_in_fixture
        for tk in times:
            env = math.exp(-(ctx.t - tk) / p["decay"])
            if env < 0.01:
                continue
            ev = round(float(tk) * 1000)
            picks = _hash(np.full(count, ev), np.arange(count), ctx.seed)
            for j, r in enumerate(picks):
                i0 = min(n - 1, int(r * n))
                start = int(ii[i0]) - size // 2
                inside = (fi == fi[i0]) & (ii >= start) & (ii < start + size)
                if not inside.any():
                    continue
                # position inside the segment -1..1 for soft ends
                rel = np.abs((ii[inside] - start + 0.5) / size * 2 - 1)
                shape = 1 - p["soft"] * rel**2
                lv = env * shape
                sel = np.flatnonzero(inside)
                better = lv > level[sel]
                level[sel[better]] = lv[better]
                key[sel[better]] = _hash(np.array([ev]), np.array([j]), ctx.seed + 7)[0]
        rgb = palette_at(p["palette"], key) * p["brightness"]
        return rgb.astype(np.float32), level


class Sweep(Effect):
    id, name = "sweep", "Sweep"
    description = (
        "A band of light that travels once through the whole room per trigger, e.g. axis 'z' from the floor to the "
        "ceiling or 'x' from one wall to the other - it passes from strip to strip. trigger 'loop' repeats it "
        "continuously every `beats`."
    )
    params = (
        Param("color", "color", "#ffffff", "colour of the band"),
        Param("axis", "axis", "z", "direction of travel ('-z' = ceiling to floor, 'azimuth' = left to right)", dynamic=False),
        Param(
            "trigger",
            "enum",
            "bar",
            "start a sweep on every ... ('loop' = back to back)",
            options=(*EVENTS, "loop"),
            dynamic=False,
        ),
        Param("beats", "number", 2.0, "duration of one sweep in beats", 0.125, 64.0),
        Param("width", "number", 0.15, "band width as fraction of the room", 0.01, 1.0),
        Param("tail", "number", 0.3, "length of the fading tail behind the band, fraction of the room", 0.0, 2.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        x = ctx.leds.coord(p["axis"])
        dur = p["beats"] * ctx.features.beat_period
        w, tail = p["width"], p["tail"]
        span = 1 + w + tail  # the band enters below 0 and leaves above 1 completely
        if p["trigger"] == "loop":
            starts = [ctx.t - (ctx.cycle(0, p["beats"]) % 1.0) * dur]
        else:
            starts = ctx.features.recent(p["trigger"], ctx.t, dur)[-4:]
        level = np.zeros(ctx.leds.n, np.float32)
        for t0 in starts:
            prog = (ctx.t - t0) / dur
            if not 0 <= prog <= 1:
                continue
            head = prog * span - w / 2
            d = head - x  # > 0: behind the head
            band = np.clip(1 - np.abs(d) / (w / 2), 0, 1)
            trail = np.where(d > 0, np.exp(-d / tail) if tail > 0 else 0.0, 0.0)
            level = np.maximum(level, np.maximum(band, trail * 0.6).astype(np.float32))
        return _fill(p["color"] * p["brightness"], ctx.leds.n), level


class Sparkle(Effect):
    id, name = "sparkle", "Sparkle"
    description = "Random twinkling LEDs. Bind density to audio (e.g. high) for hi-hat glitter."
    params = (
        Param("palette", "palette", ["#ffffff"], "sparkle colours", dynamic=False),
        Param("density", "number", 0.05, "probability per LED and slot", 0.0, 1.0),
        Param("rate", "number", 20.0, "time slots per second", 1.0, 120.0),
        Param("decay", "number", 0.1, "fade time in seconds", 0.01, 2.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        idx = ctx.leds.idx
        offset = _hash(idx, ctx.seed)
        pos = ctx.t * p["rate"] + offset
        slot = np.floor(pos).astype(np.int64)
        since = (pos - slot) / p["rate"]
        lit = _hash(idx, slot, ctx.seed + 1) < p["density"]
        level = np.where(lit, np.exp(-since / p["decay"]), 0.0).astype(np.float32)
        rgb = palette_at(p["palette"], _hash(idx, slot, ctx.seed + 2)) * p["brightness"]
        return rgb.astype(np.float32), level


class Fade(Effect):
    id, name = "fade", "Fade"
    description = "Cross-fades from one colour to another over the clip duration."
    params = (
        Param("from", "color", "#000000", "start colour", dynamic=False),
        Param("to", "color", "#ffffff", "end colour", dynamic=False),
        Param("ease", "enum", "smooth", "curve", options=("linear", "smooth"), dynamic=False),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        f = ctx.progress
        if p["ease"] == "smooth":
            f = f * f * (3 - 2 * f)
        return _fill((p["from"] + (p["to"] - p["from"]) * f) * p["brightness"], ctx.leds.n), None


class Vu(Effect):
    id, name = "vu", "VU meter"
    description = "Fills along an axis proportional to a loudness band."
    params = (
        Param("palette", "palette", ["#00ff00", "#ffd800", "#ff0000"], "colours from empty to full", dynamic=False),
        Param("source", "enum", "rms", "loudness band", options=("rms", "low", "mid", "high", "onset"), dynamic=False),
        Param("axis", "axis", "u", "fill direction", dynamic=False),
        Param("gain", "number", 1.0, "level multiplier", 0.0, 5.0),
        Param("mirror", "bool", False, "fill from the middle outwards", dynamic=False),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        x = ctx.leds.coord(p["axis"])
        if p["mirror"]:
            x = np.abs(2 * x - 1)
        level = min(1.0, getattr(ctx.audio, p["source"]) * p["gain"])
        alpha = _smoothstep(level + 0.02, level - 0.02, x).astype(np.float32) if level > 0 else np.zeros_like(x)
        rgb = palette_at(p["palette"], x, cyclic=False) * p["brightness"]
        return rgb.astype(np.float32), alpha


def _value_noise(p: np.ndarray, seed: int) -> np.ndarray:
    """Smooth 3D value noise in 0..1 for points p (n, 3)."""
    i = np.floor(p).astype(np.int64)
    f = p - i
    f = f * f * (3 - 2 * f)
    out = np.zeros(len(p), np.float32)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                out += w * _hash(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)
    return out


class Noise(Effect):
    id, name = "noise", "Noise"
    description = "Organic, slowly drifting colour clouds through the room (3D noise)."
    params = (
        Param("palette", "palette", "ocean", "palette sampled by the noise", dynamic=False),
        Param("scale", "number", 1.5, "noise features per metre", 0.05, 20.0),
        Param("speed", "number", 0.3, "drift speed", 0.0, 10.0),
        Param("contrast", "number", 1.0, "1 = normal, higher = more defined blobs", 0.2, 5.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        q = ctx.leds.pos * p["scale"] + np.array([0.31, 0.17, 0.53], np.float32) * (ctx.t * p["speed"])
        v = 0.65 * _value_noise(q, ctx.seed) + 0.35 * _value_noise(q * 2.1 + 7.3, ctx.seed + 1)
        v = np.clip((v - 0.5) * p["contrast"] + 0.5, 0, 1)
        return (palette_at(p["palette"], v, cyclic=False) * p["brightness"]).astype(np.float32), None


class Spotlight(Effect):
    id, name = "spotlight", "Spotlight"
    description = (
        "Lights the LEDs around a viewing direction (azimuth/elevation as seen by the viewer). Animate with keyframes or lfo."
    )
    params = (
        Param("color", "color", "#ffffff", "spot colour"),
        Param("azimuth", "number", 0.0, "degrees, 0 = straight ahead, negative = left", -180.0, 180.0),
        Param("elevation", "number", 0.0, "degrees, positive = up", -90.0, 90.0),
        Param("radius", "number", 30.0, "spot radius in degrees", 1.0, 180.0),
        Param("softness", "number", 0.5, "0 = hard edge, 1 = very soft", 0.0, 1.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        az, el = np.radians(ctx.leds.azimuth), np.radians(ctx.leds.elevation)
        a0, e0 = math.radians(p["azimuth"]), math.radians(p["elevation"])
        cosang = np.sin(el) * math.sin(e0) + np.cos(el) * math.cos(e0) * np.cos(az - a0)
        ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
        r = p["radius"]
        level = _smoothstep(r, r * (1 - p["softness"]) - 1e-3, ang).astype(np.float32)
        return _fill(p["color"] * p["brightness"], ctx.leds.n), level


class Split(Effect):
    id, name = "split", "Split colours"
    description = "Gives every fixture (or every segment of a fixture) its own palette colour, optionally rotating on the beat."
    params = (
        Param("palette", "palette", "party", "colours to distribute", dynamic=False),
        Param("by", "enum", "fixture", "fixture or segment", options=("fixture", "segment"), dynamic=False),
        Param("segments", "number", 4.0, "segments per fixture when by = segment", 1.0, 64.0),
        Param("rotate_beats", "number", 1.0, "shift colours every N beats (0 = static)", 0.0, 64.0),
        BRIGHTNESS,
    )

    def render(self, ctx, p):
        leds = ctx.leds
        idx = leds.fixture_index.astype(np.int64)
        if p["by"] == "segment":
            s = round(p["segments"])
            idx = idx * s + np.minimum((leds.u * s).astype(np.int64), s - 1)
        shift = math.floor(ctx.audio.beat / p["rotate_beats"]) if p["rotate_beats"] > 0 else 0
        pal = p["palette"]
        return (pal[(idx + shift) % len(pal)] * p["brightness"]).astype(np.float32), None


EFFECTS: dict[str, Effect] = {
    e.id: e
    for e in (
        Solid(),
        Gradient(),
        Rainbow(),
        Pulse(),
        Strobe(),
        Chase(),
        Wave(),
        Ripple(),
        Sparkle(),
        Hits(),
        Sweep(),
        Fade(),
        Vu(),
        Noise(),
        Spotlight(),
        Split(),
    )
}


def catalog() -> list[dict]:
    return [e.info() for e in EFFECTS.values()]
