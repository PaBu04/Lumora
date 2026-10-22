"""Test and calibration patterns shown on the LEDs instead of a show.

identify  data input green, end red, rest blinking blue (mapping / direction check)
steps     raw PWM values 1, 2, 3, 4 ... 255 in segments (find the lowest visible level)
ramp      8 perceptually equal steps through the calibration curve (judge evenness)
dark      low perceived levels 1 % ... 20 % (judge dark scenes)
white     perceived white / colour at a level (white balance)
"""

import numpy as np

from lsg.geometry.led_table import LedTable
from lsg.render.colors import parse_color

RAW_STEPS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 24, 32, 48, 64, 96, 128, 192, 255]
RAMP_STEPS = [i / 8 for i in range(1, 9)]
DARK_STEPS = [0.01, 0.02, 0.03, 0.05, 0.07, 0.1, 0.15, 0.2]
KINDS = ("identify", "steps", "ramp", "dark", "white")


def _segments(n: int, k: int) -> list[slice]:
    """k segments over n LEDs, separated by one dark LED when there is room."""
    gap = 1 if n >= 2 * k else 0
    size = (n - gap * (k - 1)) / k
    out = []
    for i in range(k):
        a = round(i * (size + gap))
        b = round(i * (size + gap) + size)
        out.append(slice(a, max(a + 1, b) if n > i else a))
    return out


def pattern_frame(kind: str, table: LedTable, fixture_ids: list[str], params: dict, now: float) -> tuple[np.ndarray, bool]:
    """Frame for the pattern and whether it holds raw PWM values (0..255) instead of perceived ones."""
    frame = np.zeros((table.count, 3), np.float32)
    color = parse_color(params.get("color", "#ffffff"))
    raw = kind == "steps"
    for fid in fixture_ids:
        if fid not in table.fixture_ids:
            continue
        sl = table.fixture_slice(fid)
        n = sl.stop - sl.start
        if n == 0:
            continue
        if kind == "identify":
            blink = 1.0 if now % 1.0 < 0.6 else 0.25
            frame[sl] = [0.0, 0.0, 0.6 * blink]
            frame[sl.start] = [0.0, 1.0, 0.0]
            frame[sl.stop - 1] = [1.0, 0.0, 0.0]
        elif kind == "white":
            frame[sl] = color * float(params.get("level", 0.7))
        else:
            levels = {"steps": RAW_STEPS, "ramp": RAMP_STEPS, "dark": DARK_STEPS}[kind]
            for seg, level in zip(_segments(n, len(levels)), levels, strict=False):
                frame[sl.start + seg.start : sl.start + seg.stop] = color * level
    return frame, raw
