"""The Lumora icon: a ring of glowing LEDs in spectrum colours around a warm core of light.

python -m lumora.tools.make_icon path/to/app.ico [path/to/icon.png] [path/to/icon.svg]

One geometry for all formats: .ico (Windows shortcut), .png (README, release) and .svg (web UI).
"""

import colorsys
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

DOTS = 10
RING = 0.30  # ring radius, fraction of the size
DOT = 0.064  # LED radius
CORE = 0.115  # radius of the core of light
BG_TOP, BG_BOTTOM = (22, 26, 46), (9, 11, 20)
# hue of each LED: magenta -> violet -> blue -> cyan -> green -> yellow -> orange -> back
HUES = [0.92, 0.80, 0.68, 0.56, 0.50, 0.42, 0.15, 0.11, 0.05, 0.98]


def colors() -> list[tuple[int, int, int]]:
    out = []
    for h in HUES:
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, 0.78, 1.0)
        out.append((round(r * 255), round(g * 255), round(b * 255)))
    return out


def positions(size: float) -> list[tuple[float, float]]:
    c, r = size / 2, RING * size
    angles = [-math.pi / 2 + 2 * math.pi * i / DOTS for i in range(DOTS)]
    return [(c + r * math.cos(a), c + r * math.sin(a)) for a in angles]


def draw(size: int = 512) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # background: rounded square with a vertical gradient
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        f = y / (s - 1)
        gd.line([(0, y), (s, y)], fill=(*(round(a + (b - a) * f) for a, b in zip(BG_TOP, BG_BOTTOM, strict=True)), 255))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=255)
    img.paste(grad, (0, 0), mask)
    # glow of LEDs and core
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for (x, y), c in zip(positions(s), colors(), strict=True):
        r = DOT * s * 2.0
        g.ellipse([x - r, y - r, x + r, y + r], fill=(*c, 170))
    r = CORE * s * 2.4
    g.ellipse([s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r], fill=(255, 196, 120, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s * 0.045)), (0, 0))
    # sharp LEDs with a bright centre, then the core
    d = ImageDraw.Draw(img)
    for (x, y), c in zip(positions(s), colors(), strict=True):
        r = DOT * s
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*c, 255))
        r2 = r * 0.45
        hi = tuple(min(255, v + 90) for v in c)
        d.ellipse([x - r2, y - r2, x + r2, y + r2], fill=(*hi, 255))
    core = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    for k in range(12, 0, -1):  # soft radial core: warm edge, nearly white centre
        f = k / 12
        r = CORE * s * f
        col = (255, round(170 + 85 * (1 - f)), round(90 + 160 * (1 - f)), 255)
        cd.ellipse([s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r], fill=col)
    img.alpha_composite(core.filter(ImageFilter.GaussianBlur(s * 0.006)))
    return img


def svg() -> str:
    """The same icon as SVG (crisp at every size in the browser)."""
    size = 512
    dots, glows = [], []
    for (x, y), (r, g, b) in zip(positions(size), colors(), strict=True):
        hi = tuple(min(255, v + 90) for v in (r, g, b))
        glows.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT * size * 1.9:.1f}" fill="rgb({r},{g},{b})" opacity="0.6"/>')
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT * size:.1f}" fill="rgb({r},{g},{b})"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{DOT * size * 0.45:.1f}" fill="rgb({hi[0]},{hi[1]},{hi[2]})"/>'
        )
    c = size / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="rgb{BG_TOP}"/><stop offset="1" stop-color="rgb{BG_BOTTOM}"/></linearGradient>
<radialGradient id="core">
<stop offset="0" stop-color="#fffdf6"/><stop offset="0.55" stop-color="#ffd9a0"/>
<stop offset="1" stop-color="#ffab5a"/></radialGradient>
<radialGradient id="halo">
<stop offset="0" stop-color="#ffc478" stop-opacity="0.55"/>
<stop offset="1" stop-color="#ffc478" stop-opacity="0"/></radialGradient>
<filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{size * 0.035:.1f}"/></filter>
</defs>
<rect width="{size}" height="{size}" rx="{size * 0.22:.1f}" fill="url(#bg)"/>
<g filter="url(#blur)">{"".join(glows)}</g>
<circle cx="{c}" cy="{c}" r="{CORE * size * 2.6:.1f}" fill="url(#halo)"/>
{"".join(dots)}
<circle cx="{c}" cy="{c}" r="{CORE * size:.1f}" fill="url(#core)"/>
</svg>
"""


def main() -> None:
    ico = Path(sys.argv[1] if len(sys.argv) > 1 else "app.ico")
    ico.parent.mkdir(parents=True, exist_ok=True)
    img = draw(512)
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(ico)
    if len(sys.argv) > 2:
        img.save(sys.argv[2])
        print(sys.argv[2])
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(svg(), encoding="utf-8")
        print(sys.argv[3])


if __name__ == "__main__":
    main()
