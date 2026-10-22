"""Colour parsing and palette helpers (all colours are float RGB 0..1)."""

import colorsys
import re

import numpy as np

NAMED = {
    "black": "#000000",
    "white": "#ffffff",
    "warmwhite": "#ffb46b",
    "red": "#ff0000",
    "orange": "#ff6000",
    "amber": "#ffa000",
    "yellow": "#ffd800",
    "lime": "#80ff00",
    "green": "#00ff00",
    "mint": "#00ff80",
    "cyan": "#00ffff",
    "sky": "#0080ff",
    "blue": "#0000ff",
    "purple": "#8000ff",
    "violet": "#b000ff",
    "magenta": "#ff00ff",
    "pink": "#ff0080",
}

PALETTES = {
    "rainbow": ["#ff0000", "#ffd800", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"],
    "fire": ["#000000", "#800000", "#ff2000", "#ff8000", "#ffd060"],
    "ocean": ["#001040", "#0040ff", "#00c0ff", "#00ffd0"],
    "sunset": ["#ff0040", "#ff6000", "#ffb000", "#8000ff"],
    "neon": ["#ff00ff", "#00ffff", "#ff0080", "#80ff00"],
    "ice": ["#ffffff", "#80d0ff", "#0060ff"],
    "forest": ["#003000", "#00a040", "#80ff00"],
    "party": ["#ff0080", "#ffd800", "#00ffff", "#8000ff"],
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
_HSV = re.compile(r"^hsv\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)$")


def parse_color(value) -> np.ndarray:
    """'#ff8800', '#f80', 'red', 'hsv(200,1,1)' (hue in degrees) or [r, g, b] with 0..255."""
    if isinstance(value, np.ndarray) and value.shape == (3,):
        return value.astype(np.float32)
    if isinstance(value, (list, tuple)) and len(value) == 3 and all(isinstance(v, (int, float)) for v in value):
        return np.clip(np.asarray(value, dtype=np.float32) / 255.0, 0, 1)
    if isinstance(value, str):
        s = value.strip().lower()
        s = NAMED.get(s, s)
        m = _HEX.match(s)
        if m:
            h = m.group(1)
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0
        m = _HSV.match(s)
        if m:
            h, sat, v = (float(g) for g in m.groups())
            return np.array(colorsys.hsv_to_rgb((h / 360.0) % 1.0, min(sat, 1), min(v, 1)), dtype=np.float32)
    raise ValueError(f"invalid colour {value!r} (use '#rrggbb', a name like 'red', 'hsv(h,s,v)' or [r,g,b])")


def parse_palette(value) -> np.ndarray:
    """Palette name ('fire') or list of colours -> (k, 3)."""
    if isinstance(value, str):
        if value.lower() in PALETTES:
            value = PALETTES[value.lower()]
        else:
            return parse_color(value)[None, :]
    if isinstance(value, np.ndarray) and value.ndim == 2:
        return value.astype(np.float32)
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("palette must be a palette name or a non-empty list of colours")
    if len(value) == 3 and all(isinstance(v, (int, float)) for v in value):
        return parse_color(value)[None, :]
    return np.stack([parse_color(c) for c in value])


def palette_at(palette: np.ndarray, x: np.ndarray, cyclic: bool = True) -> np.ndarray:
    """Sample a palette at positions x (0..1). Cyclic palettes wrap smoothly."""
    k = len(palette)
    if k == 1:
        return np.broadcast_to(palette[0], (len(x), 3)).copy()
    if cyclic:
        pos = (np.asarray(x) % 1.0) * k
        i = np.floor(pos).astype(int) % k
        j = (i + 1) % k
    else:
        pos = np.clip(np.asarray(x), 0, 1) * (k - 1)
        i = np.minimum(np.floor(pos).astype(int), k - 2)
        j = i + 1
    f = (pos - np.floor(pos))[:, None] if cyclic else (pos - i)[:, None]
    return palette[i] * (1 - f) + palette[j] * f


def hsv_to_rgb(h: np.ndarray, s: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    """Vectorised HSV -> RGB, h in 0..1 (wraps)."""
    h = np.asarray(h, dtype=np.float32) % 1.0
    s = np.broadcast_to(np.asarray(s, dtype=np.float32), h.shape)
    v = np.broadcast_to(np.asarray(v, dtype=np.float32), h.shape)
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)
