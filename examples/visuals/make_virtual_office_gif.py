#!/usr/bin/env python3
"""
Generate an animated GIF illustrating a "virtual office / intranet" with a
white/grey/black theme. The LLM sits at the center of the office, with
services (Slack, Mail, Browser, SSE, Data, Workers, Users, Portal, CRM, ERP)
spread widely near the edges. Bluish conduits with arrowheads show motion from
the central LLM to each service.

Output: _vei_out/visuals/virtual_office.gif

Usage:
  python examples/visuals/make_virtual_office_gif.py

Optional env vars:
  VEI_SEED           If set, seed RNG for determinism (unset = random each run)
  VEI_GIF_FRAMES     Number of frames (default: 120)
  VEI_GIF_FPS        Frames per second (default: 24)
  VEI_GIF_WIDTH      Width in px (default: 1200)
  VEI_GIF_HEIGHT     Height in px (default: 675)
  VEI_FONT_PATH      Path to a .ttf font (fallback to PIL default)
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except Exception as e:  # pragma: no cover - soft hint if PIL missing
    raise SystemExit(
        "Pillow (PIL) is required. Install with: python -m pip install pillow\n"
        f"Original import error: {e}"
    )


@dataclass
class Node:
    name: str
    pos: Tuple[float, float]
    color: Tuple[int, int, int]
    radius: int
    shape: str = "circle"  # 'circle' or 'rect'
    rect: Tuple[int, int] | None = None  # (w, h) if shape == 'rect'


@dataclass
class Edge:
    a: int  # index into nodes
    b: int
    color: Tuple[int, int, int]
    width: int
    pings: List[Tuple[float, float]]  # list of (phase_offset [0..1), speed [0.2..1.0])
    curved: bool = False
    ctrl: Tuple[float, float] | None = None  # control point for quadratic Bezier if curved


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_in_out(t: float) -> float:
    return 0.5 * (1 - math.cos(math.pi * t))


def blend(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    return (
        int(lerp(c1[0], c2[0], t)),
        int(lerp(c1[1], c2[1], t)),
        int(lerp(c1[2], c2[2], t)),
    )


def add_alpha(rgb: Tuple[int, int, int], a: int) -> Tuple[int, int, int, int]:
    return (rgb[0], rgb[1], rgb[2], a)


def qbez(p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    u = 1.0 - t
    x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
    y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
    return x, y


def qbez_tangent(p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    # derivative of quadratic Bezier at t
    dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
    dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
    return dx, dy


def draw_arrowhead(draw: ImageDraw.ImageDraw, x: float, y: float, dx: float, dy: float, color: Tuple[int, int, int, int]):
    # small triangle oriented along (dx, dy)
    mag = math.hypot(dx, dy) or 1.0
    ux, uy = dx / mag, dy / mag
    # perpendicular
    nx, ny = -uy, ux
    length = 8.0
    width = 6.0
    bx = x - ux * length
    by = y - uy * length
    p1 = (x, y)
    p2 = (bx + nx * (width / 2), by + ny * (width / 2))
    p3 = (bx - nx * (width / 2), by - ny * (width / 2))
    draw.polygon([p1, p2, p3], fill=color)


def ensure_outdir() -> Path:
    outdir = Path("_vei_out/visuals")
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def try_font(path: str | None, size: int):
    if path and Path(path).exists():
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    # Fallback to a reasonable system font, then PIL default
    for candidate in [
        "/System/Library/Fonts/SFNSRounded.ttf",  # macOS
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_grid(img: Image.Image, draw: ImageDraw.ImageDraw, w: int, h: int):
    # Light, paper-like background with a whisper of grid
    bg = (245, 247, 250)
    draw.rectangle([0, 0, w, h], fill=bg)

    # soft center highlight
    vignette = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vignette)
    max_r = int(max(w, h) * 0.7)
    for i in range(10):
        r = int(lerp(max_r * 0.2, max_r, i / 9))
        alpha = int(lerp(40, 0, i / 9))
        vd.ellipse([w//2 - r, h//2 - r, w//2 + r, h//2 + r], outline=alpha, width=2)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=35))
    hi = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    hi.putalpha(vignette)
    img.alpha_composite(hi)

    # ultra-light grid
    grid_color = (220, 225, 232, 70)
    step = 64
    for x in range(0, w, step):
        draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, step):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)


def circle(draw: ImageDraw.ImageDraw, x: float, y: float, r: int, fill: Tuple[int, int, int], outline=None, width=2):
    draw.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=outline, width=width)


def rounded_rect(draw: ImageDraw.ImageDraw, xy, r: int, fill, outline=None, width=2):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)


def text_center(draw: ImageDraw.ImageDraw, xy, text: str, font: ImageFont.ImageFont, fill=(230, 235, 255)):
    x, y = xy
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    draw.text((x - tw / 2, y - th / 2), text, font=font, fill=fill)


def build_scene(w: int, h: int, seed: int | None):
    if seed is not None:
        random.seed(seed)
    else:
        # fresh randomness every run
        random.seed(int.from_bytes(os.urandom(8), "big"))

    # Light theme palette
    accent = (90, 160, 255)  # bluish conduits
    neutral = (120, 130, 145)  # grey outlines/text
    line_dim = (160, 170, 185)  # intra-office dim lines

    # Building geometry (shifted left to reduce empty left margin)
    bx0, by0 = int(w * 0.24), int(h * 0.06)
    bx1, by1 = int(w * 0.97), int(h * 0.94)
    mid_y = (by0 + by1) / 2

    # Central LLM hub inside the office
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2

    nodes: List[Node] = []
    nodes.append(Node("VEI", (cx, cy), accent, 34))  # index 0

    # Office rooms in a grid inside the building
    # Use concise labels for readability in smaller boxes
    labels = [
        "Portal",
        "Users",
        "Slack",
        "Mail",
        "Browser",
        "SSE",
        "Workers",
        "Data",
        "CRM",
        "ERP",
    ]
    # Exploded layout: hand-placed near edges for maximum whitespace
    inner_pad_x = 90
    inner_pad_y = 80
    x0, x1 = bx0 + inner_pad_x, bx1 - inner_pad_x
    y0, y1 = by0 + inner_pad_y, by1 - inner_pad_y
    W, H = (x1 - x0), (y1 - y0)

    def at(rx: float, ry: float) -> tuple[float, float]:
        return (x0 + rx * W, y0 + ry * H)

    positions = [
        at(0.06, 0.14),  # top-left
        at(0.28, 0.08),  # top-left-mid
        at(0.68, 0.08),  # top-right-mid
        at(0.94, 0.16),  # top-right
        at(0.08, 0.50),  # mid-left
        at(0.92, 0.50),  # mid-right
        at(0.10, 0.86),  # bottom-left
        at(0.35, 0.92),  # bottom-mid-left
        at(0.65, 0.92),  # bottom-mid-right
        at(0.92, 0.84),  # bottom-right
    ]
    for name, pos in zip(labels, positions):
        nodes.append(Node(name, pos, neutral, 14, shape="rect", rect=(130, 44)))

    # Edges: LLM -> VEI Entrance, and VEI Entrance -> office rooms
    edges: List[Edge] = []

    # From LLM center to each office node (slight curve for elegance)
    for idx in range(1, len(nodes)):
        pings = [(random.random(), random.uniform(0.28, 0.66)) for _ in range(random.randint(3, 5))]
        tx, ty = nodes[idx].pos
        dx, dy = tx - cx, ty - cy
        ctrl_x = cx + 0.22 * dx
        ctrl_y = cy + 0.22 * dy
        edges.append(Edge(0, idx, accent, 3, pings, curved=True, ctrl=(ctrl_x, ctrl_y)))

    # Some muted inter-service lines inside the office (dim, fewer pings)
    # Named intra-office pairs for dim internal chatter (kept sparse)
    name_to_idx = {nd.name: i for i, nd in enumerate(nodes)}
    intra_named = [
        ("Portal", "Data"),
        ("Slack", "CRM"),
        ("Mail", "CRM"),
        ("ERP", "Data"),
        ("Workers", "ERP"),
        ("SSE", "Browser"),
    ]
    for an, bn in intra_named:
        if an in name_to_idx and bn in name_to_idx:
            a, b = name_to_idx[an], name_to_idx[bn]
            pings = [(random.random(), random.uniform(0.2, 0.45))]
            edges.append(Edge(a, b, line_dim, 2, pings, curved=False))

    # Return geometry for drawing building
    building = (bx0, by0, bx1, by1)
    return nodes, edges, building


def draw_frame(nodes: List[Node], edges: List[Edge], building, w: int, h: int, t: float, font_ui, font_caption) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    draw_grid(img, draw, w, h)

    # Titles
    # Minimal top accent only (no title/subtitle for cleaner deck look)

    # Draw office building (light theme)
    bx0, by0, bx1, by1 = building
    b_fill = (255, 255, 255, 255)
    b_outline = (192, 198, 208, 220)
    rounded_rect(draw, (bx0, by0, bx1, by1), 18, fill=b_fill, outline=b_outline, width=2)

    # Clean interior (no grid lines) for clarity; center LLM will be drawn below

    # Links
    for e in edges:
        a = nodes[e.a].pos
        b = nodes[e.b].pos
        # line background glow
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow, "RGBA")
        if e.curved and e.ctrl is not None:
            # draw as polyline
            pts = [qbez(a, e.ctrl, b, tt / 32.0) for tt in range(33)]
            gd.line(pts, fill=add_alpha(e.color, 24), width=e.width + 7, joint="curve")
        else:
            gd.line([a, b], fill=add_alpha(e.color, 24), width=e.width + 6)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=3))
        img.alpha_composite(glow)

        # core line
        if e.curved and e.ctrl is not None:
            pts = [qbez(a, e.ctrl, b, tt / 64.0) for tt in range(65)]
            draw.line(pts, fill=add_alpha(e.color, 130), width=e.width)
        else:
            draw.line([a, b], fill=add_alpha(e.color, 130), width=e.width)

    # Pings along links (with arrowheads)
    for e in edges:
        a = nodes[e.a].pos
        b = nodes[e.b].pos
        for phase, speed in e.pings:
            s = (phase + t * speed) % 1.0
            if e.curved and e.ctrl is not None:
                x, y = qbez(a, e.ctrl, b, s)
            else:
                x, y = lerp(a[0], b[0], s), lerp(a[1], b[1], s)
            r = 4
            # tail for clarity
            tail_steps = 4
            for ti in range(tail_steps, -1, -1):
                tt = max(0.0, s - ti * 0.015)
                if e.curved and e.ctrl is not None:
                    tx, ty = qbez(a, e.ctrl, b, tt)
                else:
                    tx, ty = lerp(a[0], b[0], tt), lerp(a[1], b[1], tt)
                alpha = int(170 * (1.0 - ti / (tail_steps + 1)))
                rr = r - int(ti * 0.6)
                circle(draw, tx, ty, max(2, rr), add_alpha(e.color, alpha), outline=None, width=1)

            # arrowhead at the tip
            if e.curved and e.ctrl is not None:
                dx, dy = qbez_tangent(a, e.ctrl, b, s)
            else:
                dx, dy = b[0] - a[0], b[1] - a[1]
            draw_arrowhead(draw, x, y, dx, dy, add_alpha(e.color, 200))

    # Nodes (LLM center + office services)
    for i, nd in enumerate(nodes):
        x, y = nd.pos
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * (t + i * 0.07))
        pr = nd.radius + int(2 * pulse)
        glow_r = pr + 6

        # drop shadow / glow
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow, "RGBA")
        if True:
            circle(gd, x, y, glow_r, add_alpha((0, 0, 0), 12), outline=None)
            glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
            img.alpha_composite(glow)

        # node body: circle for LLM, rect for rooms
        if nd.name == "VEI":
            outline_alpha = 220
            circle(draw, x, y, pr, add_alpha((255, 255, 255), 255), outline=add_alpha((90, 160, 255), outline_alpha), width=3)
            inner = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            idr = ImageDraw.Draw(inner, "RGBA")
            circle(idr, x, y, pr - 5, add_alpha((248, 250, 252), 255))
            inner = inner.filter(ImageFilter.GaussianBlur(radius=1.0))
            img.alpha_composite(inner)
            label_col = (30, 34, 40)
            text_center(draw, (x, y), nd.name, font_caption, label_col)
        elif nd.shape == "rect" and nd.rect:
            rw, rh = nd.rect
            rx0, ry0 = int(x - rw / 2), int(y - rh / 2)
            rx1, ry1 = int(x + rw / 2), int(y + rh / 2)
            rounded_rect(draw, (rx0, ry0, rx1, ry1), 10, fill=add_alpha((255, 255, 255), 255), outline=add_alpha((190, 196, 206), 255), width=2)
            inner = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            idr = ImageDraw.Draw(inner, "RGBA")
            # subtle inner highlight
            rounded_rect(idr, (rx0+2, ry0+2, rx1-2, ry1-2), 9, fill=add_alpha((248, 250, 252), 255))
            inner = inner.filter(ImageFilter.GaussianBlur(radius=0.8))
            img.alpha_composite(inner)
            label_col = (30, 34, 40)
            text_center(draw, (x, y), nd.name, font_caption, label_col)
        else:
            # No other circle nodes in light theme
            pass

    # Watermark
    wm = "VEI"
    draw.text((20, h - 36), wm, font=font_ui, fill=(140, 148, 160))

    return img


def main():
    seed_env = os.getenv("VEI_SEED")
    seed = int(seed_env) if seed_env and seed_env.strip() else None
    frames = int(os.getenv("VEI_GIF_FRAMES", "120"))
    fps = int(os.getenv("VEI_GIF_FPS", "24"))
    w = int(os.getenv("VEI_GIF_WIDTH", "1200"))
    h = int(os.getenv("VEI_GIF_HEIGHT", "675"))
    font_path = os.getenv("VEI_FONT_PATH")

    outdir = ensure_outdir()
    outfile = outdir / "virtual_office.gif"

    nodes, edges, building = build_scene(w, h, seed)

    # Smaller text for cleaner, spaced-out look (light theme)
    font_ui = try_font(font_path, size=20)
    font_caption = try_font(font_path, size=14)

    imgs: List[Image.Image] = []
    for i in range(frames):
        t = i / frames  # 0..1
        img = draw_frame(nodes, edges, building, w, h, t, font_ui, font_caption)
        imgs.append(img.convert("P", palette=Image.ADAPTIVE))

    duration_ms = int(1000 / fps)
    imgs[0].save(
        outfile,
        save_all=True,
        append_images=imgs[1:],
        optimize=False,
        duration=duration_ms,
        loop=0,
        disposal=2,
    )
    print(f"Saved: {outfile} ({w}x{h}, {frames} frames @ {fps} fps)")


if __name__ == "__main__":
    main()
