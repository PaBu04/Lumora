"""Spatial shaders: user/AI written Python functions rendering a clip.

A shader is a file with

    def render(t, leds, audio, params):
        ...
        return rgb            # (n, 3) floats 0..1
        # or: return rgb, alpha

`np`, `math` and the helpers listed in SHADER_API are predefined. The code is checked
statically (no imports besides numpy/math, no dunder access, no file/OS access,
no `while`, capped `range`) and executed with a minimal set of builtins. This keeps
accidental damage out; it is not a security boundary against hostile code.
"""

import ast
import builtins
import math
import re
import time

import numpy as np

from lsg.render.colors import hsv_to_rgb, palette_at, parse_color, parse_palette
from lsg.render.context import RenderContext

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
MAX_RANGE = 100_000
SLOW_FRAME_SECONDS = 0.1
MAX_SLOW_FRAMES = 5

SHADER_API = """\
def render(t, leds, audio, params) -> rgb | (rgb, alpha)

t       song time in seconds
leds    the targeted LEDs; numpy arrays of length leds.n:
          leds.pos (n,3) metres, leds.x / leds.y / leds.z, leds.norm_pos (n,3) 0..1 in room bounds,
          leds.u (0..1 along each strip in data order), leds.index_in_fixture, leds.fixture_index,
          leds.azimuth / leds.elevation (degrees as seen by the viewer, negative azimuth = left),
          leds.distance (metres from viewer), leds.coord(axis) -> 0..1 for
          'x','y','z','u','azimuth','elevation','distance','radial','angle','fixture' or [dx,dy,dz]
audio   music at time t: audio.rms, .low, .mid, .high, .onset (0..1), audio.bpm,
          audio.beat (continuous beat count), .beat_phase (0..1), .bar, .bar_phase,
          .since_beat, .since_bar, .since_onset (seconds), .section (name), .section_energy
params  dict of the clip's params (dynamic values already resolved to numbers)
ctx     (global) clip context: ctx.lt (seconds since clip start), ctx.duration, ctx.progress

Predefined: np, math, color('#ff0080') -> (3,), palette('fire' | [colours]) -> (k,3),
palette_at(pal, x) -> (n,3), hsv(h, s, v) -> (n,3) with h in 0..1, clamp(x, lo=0, hi=1),
smoothstep(e0, e1, x).
Return floats 0..1: rgb (n,3) and optionally alpha (n,). No imports, no while loops.
"""

_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "abs", "min", "max", "round", "len", "sum", "float", "int", "bool", "enumerate",
        "zip", "list", "tuple", "dict", "set", "sorted", "reversed", "pow", "divmod",
        "isinstance", "any", "all", "map", "filter", "slice", "str",
        "ValueError", "Exception", "True", "False", "None",
    )
    if hasattr(builtins, name)
}

_FORBIDDEN_NAMES = {
    "eval", "exec", "open", "compile", "__import__", "globals", "locals", "vars", "getattr",
    "setattr", "delattr", "input", "breakpoint", "help", "memoryview", "type", "object",
    "super", "classmethod", "staticmethod", "property", "exit", "quit", "dir", "id",
}
_FORBIDDEN_ATTRS = {
    "load", "loads", "save", "savez", "savez_compressed", "savetxt", "loadtxt", "genfromtxt",
    "fromfile", "tofile", "memmap", "ctypeslib", "ctypes", "lib", "f2py", "testing", "distutils",
    "DataSource", "fromregex", "os", "sys", "dump", "dumps", "frombuffer", "set_printoptions",
    "seterr", "show_config", "format_float_positional",
}


class ShaderError(ValueError):
    pass


def _capped_range(*args):
    r = range(*args)
    if len(r) > MAX_RANGE:
        raise ShaderError(f"range() larger than {MAX_RANGE} is not allowed; use numpy instead")
    return r


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in ("numpy", "math"):
        return {"numpy": np, "math": math}[name]
    raise ShaderError(f"import of {name!r} is not allowed")


def check_source(source: str) -> ast.Module:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ShaderError(f"syntax error line {exc.lineno}: {exc.msg}") from exc
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(m not in ("numpy", "math") for m in mods) or isinstance(node, ast.ImportFrom):
                raise ShaderError(f"line {line}: only 'import numpy as np' / 'import math' are allowed")
        elif isinstance(node, ast.While):
            raise ShaderError(f"line {line}: while loops are not allowed (use numpy or a bounded for loop)")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await, ast.With, ast.AsyncWith)):
            raise ShaderError(f"line {line}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.Name) and (node.id in _FORBIDDEN_NAMES or node.id.startswith("__")):
            raise ShaderError(f"line {line}: name {node.id!r} is not allowed")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _FORBIDDEN_ATTRS):
            raise ShaderError(f"line {line}: attribute {node.attr!r} is not allowed")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "render" for n in tree.body):
        raise ShaderError("shader must define: def render(t, leds, audio, params)")
    return tree


def _clamp(x, lo=0.0, hi=1.0):
    return np.clip(x, lo, hi)


def _smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class Shader:
    def __init__(self, name: str, source: str):
        if not NAME_RE.match(name):
            raise ShaderError("shader name must be lowercase letters, digits and _ (max 41 chars)")
        tree = check_source(source)
        self.name = name
        self.source = source
        self.slow_frames = 0
        self.globals = {
            "__builtins__": {**_SAFE_BUILTINS, "range": _capped_range, "__import__": _restricted_import},
            "np": np,
            "math": math,
            "color": parse_color,
            "palette": parse_palette,
            "palette_at": palette_at,
            "hsv": hsv_to_rgb,
            "clamp": _clamp,
            "smoothstep": _smoothstep,
            "ctx": None,
        }
        try:
            exec(compile(tree, f"<shader {name}>", "exec"), self.globals)
        except Exception as exc:
            raise ShaderError(f"error while loading shader: {exc}") from exc
        self.fn = self.globals["render"]

    def __call__(self, ctx: RenderContext, params: dict):
        if self.slow_frames >= MAX_SLOW_FRAMES:
            raise ShaderError(f"shader disabled: slower than {SLOW_FRAME_SECONDS * 1000:.0f} ms per frame")
        self.globals["ctx"] = ctx
        start = time.perf_counter()
        try:
            out = self.fn(ctx.t, ctx.leds, ctx.audio, params)
        except ShaderError:
            raise
        except Exception as exc:
            raise ShaderError(f"{type(exc).__name__}: {exc}") from exc
        if time.perf_counter() - start > SLOW_FRAME_SECONDS:
            self.slow_frames += 1
        return normalise_output(out, ctx.leds.n)


def normalise_output(out, n: int) -> tuple[np.ndarray, np.ndarray | None]:
    alpha = None
    if isinstance(out, tuple):
        if len(out) != 2:
            raise ShaderError("return rgb or (rgb, alpha)")
        out, alpha = out
    rgb = np.asarray(out, dtype=np.float32)
    if rgb.shape == (3,):
        rgb = np.broadcast_to(rgb, (n, 3))
    if rgb.shape != (n, 3):
        raise ShaderError(f"rgb must have shape ({n}, 3), got {rgb.shape}")
    if alpha is not None:
        alpha = np.broadcast_to(np.asarray(alpha, dtype=np.float32), (n,))
        alpha = np.nan_to_num(np.clip(alpha, 0, 1))
    return np.nan_to_num(np.clip(rgb, 0, 1)), alpha
