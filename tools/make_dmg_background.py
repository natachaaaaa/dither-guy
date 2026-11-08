"""Render the macOS DMG window background with Dither Guy's own engine.

A synthwave scene (sky, striped sun, perspective grid) is drawn procedurally,
then dithered by `utils.pipeline.render` exactly like a user image would be.
Crisp title / arrow / hint are drawn on top in the bundled VT323 font.

Writes:  <out>/background.png      660 x 420   (DMG window size)
         <out>/background@2x.png   1320 x 840  (Retina)
The Finder layout in the CI must match ICON_POS / APPS_POS below.

Usage:  python tools/make_dmg_background.py [out_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.pipeline import render  # noqa: E402

W, H = 660, 420                 # DMG window content size (1x)
ICON_POS = (170, 215)           # centre of DitherGuy.app icon (1x)
APPS_POS = (490, 215)           # centre of the Applications link (1x)
S = 2                           # draw at 2x, downscale for 1x

INK = (52, 18, 96)              # dark violet for text
PALETTE = [                     # pastel vaporwave, light enough for Finder's dark labels
    (255, 246, 252), (255, 214, 236), (255, 168, 214), (214, 196, 255),
    (168, 150, 250), (124, 214, 255), (255, 226, 150), (122, 80, 200),
    (255, 110, 150), (255, 160, 110),
]


def scene(w: int, h: int) -> Image.Image:
    """Procedural synthwave postcard, smooth (the dithering happens later)."""
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    top = np.array([150, 130, 250], np.float32)
    mid = np.array([255, 190, 228], np.float32)
    horizon = 0.66
    t = np.clip(y / horizon, 0, 1)
    sky = top * (1 - t) + mid * t
    img = np.broadcast_to(sky, (h, w, 3)).copy()

    # Sun: vertical yellow -> pink gradient, cut by thinning stripes near the bottom.
    cx, cy, r = w * 0.5, h * 0.50, h * 0.27
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    sv = np.clip((yy - (cy - r)) / (2 * r), 0, 1)[..., None]
    sun = np.array([255, 238, 130], np.float32) * (1 - sv) + np.array([255, 70, 140], np.float32) * sv
    band = ((yy - cy) / r)
    stripes = np.zeros_like(inside)
    for k, (pos, thick) in enumerate([(0.18, 0.035), (0.36, 0.05), (0.54, 0.065), (0.72, 0.08)]):
        stripes |= np.abs(band - pos) < thick
    sun_mask = inside & ~stripes & (yy < h * horizon)
    img[sun_mask] = sun[sun_mask]

    # Soft halo around the sun.
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
    halo = np.clip(1.2 - d, 0, 0.2)[..., None] * 1.2 * (~inside)[..., None]
    img = img * (1 - halo) + np.array([255, 220, 240], np.float32) * halo

    # Ground + perspective grid.
    gy0 = int(h * horizon)
    ground = np.linspace(0, 1, h - gy0, dtype=np.float32)[:, None, None]
    img[gy0:] = np.array([250, 214, 240], np.float32) * (1 - ground) + np.array([196, 168, 255], np.float32) * ground
    pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    d2 = ImageDraw.Draw(pil)
    line = (150, 90, 220)
    lw = max(1, w // 330)
    d2.line([(0, gy0), (w, gy0)], fill=(255, 120, 200), width=lw * 2)
    vx = w / 2
    for i in range(-14, 15):
        d2.line([(vx + i * w * 0.012, gy0), (vx + i * w * 0.16, h)], fill=line, width=lw)
    yv, step = gy0, 3.0 * S
    while yv < h:
        d2.line([(0, yv), (w, yv)], fill=line, width=lw)
        step *= 1.35
        yv += step
    return pil


def font(px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(ROOT / "fonts" / "VT323-Regular.ttf"), px)
    except OSError:
        return ImageFont.load_default()


def glow_text(img: Image.Image, xy, text: str, f, fill, glow=(255, 255, 255), radius=6, anchor="mm"):
    """Text with a soft light halo so it reads on any part of the scene."""
    halo = Image.new("L", img.size, 0)
    ImageDraw.Draw(halo).text(xy, text, font=f, fill=255, anchor=anchor,
                              stroke_width=radius // 2, stroke_fill=255)
    halo = halo.filter(ImageFilter.GaussianBlur(radius))
    img.paste(Image.new("RGB", img.size, glow), (0, 0), halo.point(lambda v: min(255, v * 2)))
    ImageDraw.Draw(img).text(xy, text, font=f, fill=fill, anchor=anchor)


def pixel_arrow(img: Image.Image, x0: int, x1: int, y: int, cell: int, fill) -> None:
    """Chunky pixel-art arrow from x0 to x1, centred on y."""
    d = ImageDraw.Draw(img)
    head = cell * 5
    shaft_end = x1 - head
    d.rectangle([x0, y - cell, shaft_end, y + cell - 1], fill=fill)
    for i in range(5):  # stepped triangle head
        hx = shaft_end + i * cell
        half = (5 - i) * cell
        d.rectangle([hx, y - half, hx + cell - 1, y + half - 1], fill=fill)


def make(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    w2, h2 = W * S, H * S
    params = dict(
        method="Bayer 8x8", pixel_size=3, threshold=128, color=(255, 255, 255),
        brightness=1.05, contrast=1.1, saturation=1.15,
        palette_name="Custom", custom_palette=PALETTE,
        glow_radius=10, glow_intensity=22,
        glow_gradient=[(255, 113, 206), (185, 103, 255), (1, 205, 254)], glow_mode="Luminance",
        fx=dict(scanlines=12, vignette=18, seed=7),
    )
    art = render(scene(w2, h2), params).convert("RGB").resize((w2, h2), Image.NEAREST)

    # Typography and arrow, crisp on top of the dithered art.
    glow_text(art, (w2 // 2, 62 * S), "DITHER GUY", font(64 * S), INK, radius=8 * S)
    ax0 = ICON_POS[0] * S + 84 * S
    ax1 = APPS_POS[0] * S - 84 * S
    ay = ICON_POS[1] * S
    shadow = Image.new("L", art.size, 0)
    pixel_arrow(Image.merge("RGB", [shadow] * 3), ax0, ax1, ay, 4 * S, (255, 255, 255))
    halo = Image.new("L", art.size, 0)
    hd = Image.new("RGB", art.size, (0, 0, 0))
    pixel_arrow(hd, ax0, ax1, ay, 4 * S, (255, 255, 255))
    halo = hd.convert("L").filter(ImageFilter.GaussianBlur(6 * S))
    art.paste(Image.new("RGB", art.size, (255, 255, 255)), (0, 0), halo.point(lambda v: min(255, v * 3)))
    pixel_arrow(art, ax0, ax1, ay, 4 * S, INK)
    glow_text(art, (w2 // 2, (H - 60) * S), "drag the app into Applications to install",
              font(26 * S), INK, radius=5 * S)

    p2 = out_dir / "background@2x.png"
    p1 = out_dir / "background.png"
    art.save(p2, optimize=True)
    art.resize((W, H), Image.LANCZOS).save(p1, optimize=True)
    return p1, p2


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "dmg"
    for p in make(out):
        print("wrote", p)
