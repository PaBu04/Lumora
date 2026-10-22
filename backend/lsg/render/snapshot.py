"""Still images of a show: viewer perspective, top view and a time x LED timeline.

Used by the MCP server so the AI can check what it programmed.
"""

import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from lsg.geometry.led_table import LedTable
from lsg.geometry.viewer import viewer_basis
from lsg.model.project import Project
from lsg.render.engine import Renderer

BG = (11, 13, 18)
ROOM_LINE = (70, 78, 96)
OFF_LED = (38, 42, 52)
TEXT = (200, 205, 215)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _room_edges(project: Project) -> list[tuple[np.ndarray, np.ndarray]]:
    h = project.room.height
    edges = []
    for w in project.room.walls:
        a, b = np.array([*w.start, 0.0]), np.array([*w.end, 0.0])
        edges += [(a, b), (a + [0, 0, h], b + [0, 0, h]), (a, a + [0, 0, h])]
    return edges


def _glow(base: np.ndarray, layer: np.ndarray, radius: float) -> np.ndarray:
    img = Image.fromarray(np.clip(layer * 255, 0, 255).astype(np.uint8))
    blurred = np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255
    return np.clip(base + layer + 1.6 * blurred, 0, 1)


def render_viewer_image(project: Project, table: LedTable, colors: np.ndarray, width: int = 960, height: int = 540, fov_deg: float = 100.0) -> bytes:
    """What the audience sees (perspective from the viewer position)."""
    forward, right, up = viewer_basis(project.viewer)
    eye = np.asarray(project.viewer.position, dtype=np.float64)
    focal = (width / 2) / math.tan(math.radians(fov_deg) / 2)
    near = 0.05

    def project_pts(p: np.ndarray):
        d = p - eye
        f, r, u = d @ forward, d @ right, d @ up
        return np.stack([width / 2 + r / f * focal, height / 2 - u / f * focal], axis=-1), f

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    for a, b in _room_edges(project):
        fa, fb = (a - eye) @ forward, (b - eye) @ forward
        if fa < near and fb < near:
            continue
        if fa < near:
            a = a + (b - a) * (near - fa) / (fb - fa)
        elif fb < near:
            b = b + (a - b) * (near - fb) / (fa - fb)
        (pa, pb), _ = project_pts(np.stack([a, b]))
        draw.line([tuple(pa), tuple(pb)], fill=ROOM_LINE, width=1)

    base = np.asarray(img, dtype=np.float32) / 255
    layer_img = Image.new("RGB", (width, height), (0, 0, 0))
    ldraw = ImageDraw.Draw(layer_img)
    if table.count:
        pts, f = project_pts(table.pos.astype(np.float64))
        order = np.argsort(-f)  # far first
        for i in order:
            if f[i] < near:
                continue
            x, y = pts[i]
            if not (-10 <= x <= width + 10 and -10 <= y <= height + 10):
                continue
            r = max(1.0, min(6.0, 0.025 / f[i] * focal))
            c = colors[i]
            col = tuple(int(v * 255) for v in c) if c.max() > 0.02 else OFF_LED
            ldraw.ellipse([x - r, y - r, x + r, y + r], fill=col)
    layer = np.asarray(layer_img, dtype=np.float32) / 255
    out = _glow(base, layer, radius=4)
    return _png(Image.fromarray((out * 255).astype(np.uint8)))


def render_top_image(project: Project, table: LedTable, colors: np.ndarray | None = None, size: int = 640) -> bytes:
    """Floor plan from above with LEDs, fixture names and the viewer."""
    (x0, y0, _), (x1, y1, _) = project.room.bounds
    pad = 40
    scale = (size - 2 * pad) / max(x1 - x0, y1 - y0, 1e-6)
    w = int((x1 - x0) * scale + 2 * pad)
    h = int((y1 - y0) * scale + 2 * pad)

    def to_px(x, y):
        return pad + (x - x0) * scale, h - pad - (y - y0) * scale

    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    draw.polygon([to_px(*p) for p in project.room.floor], outline=ROOM_LINE, fill=(18, 21, 28))
    font = ImageFont.load_default()
    # 1 m grid ticks along the bounds
    for gx in range(math.ceil(x0), math.floor(x1) + 1):
        px, _ = to_px(gx, y0)
        draw.text((px - 3, h - pad + 6), f"{gx}", fill=ROOM_LINE, font=font)
    for gy in range(math.ceil(y0), math.floor(y1) + 1):
        _, py = to_px(x0, gy)
        draw.text((pad - 18, py - 6), f"{gy}", fill=ROOM_LINE, font=font)

    for i in range(table.count):
        x, y = to_px(table.pos[i, 0], table.pos[i, 1])
        c = colors[i] if colors is not None else np.array([0.9, 0.9, 0.9])
        col = tuple(int(v * 255) for v in c) if c.max() > 0.02 else OFF_LED
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=col)
    for k, fid in enumerate(table.fixture_ids):
        sl = table.fixture_slice(fid)
        if sl.stop > sl.start:
            p = table.pos[sl.start]
            x, y = to_px(p[0], p[1])
            draw.text((x + 4, y + 2), project.fixture(fid).name, fill=TEXT, font=font)

    vx, vy = to_px(*project.viewer.position[:2])
    yaw = math.radians(project.viewer.yaw_deg)
    draw.ellipse([vx - 6, vy - 6, vx + 6, vy + 6], outline=(255, 255, 255), width=2)
    draw.line([(vx, vy), (vx + 22 * math.cos(yaw), vy - 22 * math.sin(yaw))], fill=(255, 255, 255), width=2)
    draw.text((vx + 8, vy + 8), "viewer", fill=TEXT, font=font)
    return _png(img)


def render_timeline_image(renderer: Renderer, start: float, end: float, width: int = 800, max_rows: int = 400) -> bytes:
    """x = time, y = LED (grouped by fixture). Gives an overview of a whole passage at a glance."""
    table = renderer.table
    n = table.count
    rows = np.arange(n) if n <= max_rows else np.linspace(0, n - 1, max_rows).astype(int)
    header, label_w = 28, 110
    times = np.linspace(start, end, width, endpoint=False)
    data = np.zeros((len(rows), width, 3), dtype=np.float32)
    for j, t in enumerate(times):
        data[:, j] = renderer.render(float(t))[rows]
    body = Image.fromarray((data * 255).astype(np.uint8)).resize((width, max(len(rows), 1) * max(1, 300 // max(len(rows), 1))), Image.NEAREST)

    img = Image.new("RGB", (label_w + width, header + body.height), BG)
    img.paste(body, (label_w, header))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    feats = renderer.features
    for s in feats.sections:
        if start <= s.start < end:
            x = label_w + (s.start - start) / (end - start) * width
            draw.line([(x, 0), (x, header + body.height)], fill=(120, 120, 140))
            draw.text((x + 3, 2), s.name, fill=TEXT, font=font)
    for b in feats.recent("bar", end, end - start):
        x = label_w + (b - start) / (end - start) * width
        draw.line([(x, header - 8), (x, header - 2)], fill=(150, 150, 160))
    draw.text((label_w, header - 14), f"{start:.1f}s", fill=TEXT, font=font)
    draw.text((label_w + width - 40, header - 14), f"{end:.1f}s", fill=TEXT, font=font)
    row_px = body.height / max(len(rows), 1)
    for fid in table.fixture_ids:
        sl = table.fixture_slice(fid)
        r0 = int(np.searchsorted(rows, sl.start))
        y = header + r0 * row_px
        draw.line([(0, y), (label_w + width, y)], fill=(60, 64, 76))
        draw.text((4, y + 2), renderer.project.fixture(fid).name[:16], fill=TEXT, font=font)
    return _png(img)
