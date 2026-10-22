"""Draws the app icon (three glowing LED dots) as a multi-size .ico file.

python -m lsg.tools.make_icon path/to/app.ico
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

COLORS = [(255, 45, 149), (0, 212, 255), (255, 212, 0)]


def draw(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = ImageDraw.Draw(img)
    r = size * 0.18
    bg.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=(14, 17, 24, 255))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    dot = size * 0.12
    for i, c in enumerate(COLORS):
        cx, cy = size * (0.25 + 0.25 * i), size * 0.5
        g.ellipse([cx - dot * 1.6, cy - dot * 1.6, cx + dot * 1.6, cy + dot * 1.6], fill=(*c, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(size * 0.05)))
    d = ImageDraw.Draw(img)
    for i, c in enumerate(COLORS):
        cx, cy = size * (0.25 + 0.25 * i), size * 0.5
        d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=(*c, 255))
    return img


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "app.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    draw().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)


if __name__ == "__main__":
    main()
