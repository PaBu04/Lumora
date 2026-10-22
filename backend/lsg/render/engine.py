"""Render engine: Show x LEDs x time -> RGB frame.

The same engine drives the browser preview, the live output and MCP snapshots, so all
three always show the same thing.
"""

import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import LedTable
from lsg.model.project import Project
from lsg.model.show import Clip, Show, Target
from lsg.render.context import LedView, RenderContext, Spatial
from lsg.render.effects import EFFECTS
from lsg.render.params import Param, ParamError, compile_param, compile_params
from lsg.render.shaders import Shader, ShaderError

SHADER_PREFIX = "shader:"


class TargetError(ValueError):
    pass


def select_leds(target: Target, table: LedTable, project: Project) -> np.ndarray:
    """Indices of the LEDs a target selects."""
    n = table.count
    if target.fixtures is None and target.tags is None:
        mask = np.ones(n, dtype=bool)
    else:
        mask = np.zeros(n, dtype=bool)
        ids = set(target.fixtures or [])
        unknown = ids - set(table.fixture_ids)
        if unknown:
            raise TargetError(f"unknown fixture id(s) {sorted(unknown)}")
        tags = set(target.tags or [])
        known_tags = {t for f in project.fixtures for t in f.tags}
        if tags - known_tags:
            raise TargetError(f"unknown tag(s) {sorted(tags - known_tags)}; known: {sorted(known_tags)}")
        for f in project.fixtures:
            if f.id in ids or tags & set(f.tags):
                mask[table.fixture_slice(f.id)] = True
    for r in target.where:
        match r.field:
            case "x" | "y" | "z":
                v = table.pos[:, "xyz".index(r.field)]
            case "nx" | "ny" | "nz":
                v = table.norm_pos[:, "xyz".index(r.field[1])]
            case _:
                v = getattr(table, r.field)
        if r.min is not None:
            mask &= v >= r.min
        if r.max is not None:
            mask &= v <= r.max
    if target.view == "direct":
        mask &= table.view >= 0.5
    elif target.view == "indirect":
        mask &= table.view < 0.5
    if target.invert:
        mask = ~mask
    return np.flatnonzero(mask)


def _generic_param(name: str, value: Any) -> Callable:
    """Shader params: numbers may be dynamic, everything else is passed through."""
    if isinstance(value, dict) and {"audio", "keys", "lfo"} & value.keys():
        return compile_param(Param(name, "number", 0.0, ""), value)
    return lambda ctx: value


@dataclass
class CompiledClip:
    clip: Clip
    layer_opacity: float
    view: LedView
    render: Callable[[RenderContext, dict], tuple[np.ndarray, np.ndarray | None]]
    params: dict[str, Callable]
    seed: int
    disabled: bool = False


@dataclass
class Renderer:
    project: Project
    table: LedTable
    show: Show
    features: AudioFeatures
    shaders: dict[str, Shader] = field(default_factory=dict)

    def __post_init__(self):
        b0, b1 = self.project.room.bounds
        self.spatial = Spatial(self.table, ((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2))
        self.viewer_pos = np.asarray(self.project.viewer.position, dtype=np.float32)
        self.errors: dict[str, str] = {}
        self.clips: list[CompiledClip] = []
        for layer in self.show.layers:
            if not layer.enabled:
                continue
            for clip in sorted(layer.clips, key=lambda c: c.start):
                try:
                    self.clips.append(self._compile(clip, layer.opacity))
                except (ParamError, TargetError, ShaderError, ValueError) as exc:
                    self.errors[clip.id] = str(exc)
        self.duration = self.show.duration or self.features.duration or max((c.end for _, c in self.show.clips()), default=0.0)

    def _compile(self, clip: Clip, layer_opacity: float) -> CompiledClip:
        view = LedView(self.table, self.spatial, select_leds(clip.target, self.table, self.project))
        seed = zlib.crc32(clip.id.encode()) & 0xFFFF
        if clip.effect.startswith(SHADER_PREFIX):
            name = clip.effect[len(SHADER_PREFIX) :]
            if name not in self.shaders:
                raise ShaderError(f"unknown shader {name!r}; available: {sorted(self.shaders)}")
            params = {k: _generic_param(k, v) for k, v in clip.params.items()}
            return CompiledClip(clip, layer_opacity, view, self.shaders[name], params, seed)
        effect = EFFECTS.get(clip.effect)
        if effect is None:
            raise ValueError(f"unknown effect {clip.effect!r}; available: {sorted(EFFECTS)}")
        return CompiledClip(clip, layer_opacity, view, effect.render, compile_params(effect.params, clip.params), seed)

    def render(self, t: float) -> np.ndarray:
        frame = np.zeros((self.table.count, 3), dtype=np.float32)
        if self.table.count == 0:
            return frame
        audio = self.features.frame(t)
        for cc in self.clips:
            c = cc.clip
            if cc.disabled or not (c.start <= t < c.end) or cc.view.n == 0:
                continue
            env = cc.layer_opacity * c.opacity
            lt = t - c.start
            if c.fade_in > 0 and lt < c.fade_in:
                env *= lt / c.fade_in
            if c.fade_out > 0 and c.end - t < c.fade_out:
                env *= (c.end - t) / c.fade_out
            if env <= 0:
                continue
            ctx = RenderContext(
                t=t,
                lt=lt,
                duration=c.end - c.start,
                leds=cc.view,
                audio=audio,
                features=self.features,
                seed=cc.seed,
                viewer_pos=self.viewer_pos,
            )
            try:
                params = {k: fn(ctx) for k, fn in cc.params.items()}
                rgb, alpha = cc.render(ctx, params)
            except Exception as exc:  # a broken clip must never stop the show
                cc.disabled = True
                self.errors[c.id] = f"runtime error at t={t:.2f}s: {exc}"
                continue
            a = np.full(cc.view.n, env, np.float32) if alpha is None else alpha * env
            _blend(frame, cc.view.idx, rgb, a, c.blend)
        np.clip(frame, 0.0, 1.0, out=frame)
        if self.show.master < 1:
            frame *= self.show.master
        return frame


def _blend(frame: np.ndarray, idx: np.ndarray, rgb: np.ndarray, a: np.ndarray, mode: str) -> None:
    dst = frame[idx]
    a = a[:, None]
    match mode:
        case "normal":
            dst = dst * (1 - a) + rgb * a
        case "add":
            dst = dst + rgb * a
        case "max":
            dst = np.maximum(dst, rgb * a)
        case "multiply":
            dst = dst * (1 - a + rgb * a)
        case "subtract":
            dst = np.maximum(dst - rgb * a, 0)
    frame[idx] = dst
