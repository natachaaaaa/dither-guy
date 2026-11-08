"""Generate the README artwork in docs/ with Dither Guy's own engine.

Everything starts from one procedural, original ink illustration (a staring
eye wrapped in hair-like strands, heavy blacks), which is then dithered by
`utils.pipeline.render` exactly like a user image.

Usage:  python tools/make_readme_assets.py [out_dir]     (default: docs/)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.pipeline import render  # noqa: E402
from utils.presets import load_preset  # noqa: E402

VIOLET = (192, 107, 255)
PINK = (255, 95, 207)
BONE = (236, 226, 255)
INK = (8, 5, 12)


# ---------------------------------------------------------------------------
# Original source illustration
# ---------------------------------------------------------------------------

def ink_eye(w: int, h: int, seed: int = 13) -> Image.Image:
    """Procedural horror-ink eye: hatched lids, veined sclera, fibrous iris,
    and flowing strands of hair around it. Greyscale-ish, high contrast."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w * 0.5, h * 0.46
    ew, eh = w * 0.30, h * 0.30

    # Pale face around the eye fading into black: ink only reads on skin.
    fr = np.sqrt(((xx - cx) / (w * 0.40)) ** 2 + ((yy - cy) / (h * 0.70)) ** 2)
    skin = np.clip((1.0 - fr) / 0.35, 0, 1) ** 1.3
    base = 10 + 205 * skin
    img = np.dstack([base * 0.98, base * 0.93, base * 1.0])

    pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(pil)

    # Hair strands: long sinuous curves sweeping around the eye (black over the
    # skin, a few pale ones catching light in the dark).
    for i in range(190):
        side = -1 if i % 2 else 1
        y0 = rng.uniform(-0.1, 1.1) * h
        amp = rng.uniform(10, 70)
        freq = rng.uniform(0.002, 0.006)
        phase = rng.uniform(0, 6.28)
        pale = i % 6 == 0
        tone = int(rng.uniform(90, 150)) if pale else int(rng.uniform(0, 22))
        width = int(rng.integers(1, 3)) if pale else int(rng.integers(2, 6))
        pts = []
        for x in np.linspace(0, w, 140):
            bend = side * h * 0.42 * math.exp(-((x - cx) / (w * 0.26)) ** 2)  # part around the eye
            y = y0 + amp * math.sin(x * freq * 6.28 + phase) + bend * (1 if y0 > cy else -1)
            pts.append((x, y))
        d.line(pts, fill=(tone, int(tone * 0.9), int(tone * 1.1)), width=width)

    a = np.asarray(pil, dtype=np.float32).copy()

    # Almond-shaped eye opening.
    nx = (xx - cx) / ew
    ny = (yy - cy) / eh
    lid = np.clip(1 - nx ** 2, 0, 1) ** 0.75
    inside = np.abs(ny) < lid
    # Sclera: bone white, shadowed under the upper lid and towards the corners.
    shade = np.clip(0.55 + 0.45 * (ny + 0.2) / 1.2, 0.25, 1.0) * np.clip(1.15 - np.abs(nx) ** 3, 0.3, 1)
    sclera = np.dstack([232 * shade, 222 * shade, 214 * shade])
    a[inside] = sclera[inside]

    # Iris: radial fibres + dark limbal ring, looking slightly down-left.
    ix, iy, ir = cx - ew * 0.08, cy + eh * 0.12, eh * 0.62
    dx, dy = xx - ix, yy - iy
    rr = np.sqrt(dx ** 2 + dy ** 2) / ir
    ang = np.arctan2(dy, dx)
    fib = 0.5 + 0.5 * np.sin(ang * 90 + rng.normal(0, 0.6, size=ang.shape).astype(np.float32) * 0.3)
    iris_v = (70 + 90 * fib * (1 - rr) + 40 * np.sin(rr * 18)) * np.clip(1.25 - rr, 0, 1)
    iris_v = np.where(rr > 0.86, iris_v * 0.25, iris_v)  # limbal ring
    iris_mask = inside & (rr < 1)
    a[iris_mask] = np.dstack([iris_v * 0.9, iris_v * 0.75, iris_v * 1.15])[iris_mask]
    pupil = inside & (rr < 0.38)
    a[pupil] = INK
    # Specular highlight.
    hl = inside & (((xx - (ix + ir * 0.3)) ** 2 + (yy - (iy - ir * 0.34)) ** 2) < (ir * 0.08) ** 2)
    a[hl] = (255, 255, 255)

    pil = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(pil)

    # Veins creeping from the corners.
    for _ in range(26):
        side = rng.choice([-1, 1])
        x, y = cx + side * ew * rng.uniform(0.75, 0.95), cy + rng.uniform(-0.25, 0.25) * eh
        pts = [(x, y)]
        for _ in range(int(rng.integers(8, 20))):
            x -= side * rng.uniform(4, 12) * w / 1280
            y += rng.normal(0, 4) * h / 520
            if abs((y - cy) / eh) > (1 - ((x - cx) / ew) ** 2) ** 0.75 * 0.95:
                break
            pts.append((x, y))
        if len(pts) > 2:
            d.line(pts, fill=(110, 40, 70), width=max(1, w // 900))

    # Lids: heavy ink outline and lashes.
    outline = []
    for t in np.linspace(-1, 1, 200):
        outline.append((cx + t * ew, cy - (1 - t * t) ** 0.75 * eh))
    lower = [(cx + t * ew, cy + (1 - t * t) ** 0.75 * eh) for t in np.linspace(1, -1, 200)]
    d.line(outline, fill=INK, width=max(4, w // 160))
    d.line(lower, fill=INK, width=max(3, w // 260))
    for t in np.linspace(-0.92, 0.92, 46):
        x0, y0 = cx + t * ew, cy - (1 - t * t) ** 0.75 * eh
        ln = eh * rng.uniform(0.25, 0.45)
        ang2 = -math.pi / 2 + t * 0.9 + rng.normal(0, 0.08)
        d.line([(x0, y0), (x0 + math.cos(ang2) * ln, y0 + math.sin(ang2) * ln)], fill=INK, width=max(2, w // 420))

    # Hatching on the upper lid (horror-manga shading).
    hatch = Image.new("L", pil.size, 0)
    hd = ImageDraw.Draw(hatch)
    step = max(4, w // 180)
    for k in range(-h, w, step):
        hd.line([(k, 0), (k + h, h)], fill=255, width=1)
    upper = (ny < -lid) & (ny > -lid - 0.55) & (np.abs(nx) < 1.05)
    under = (ny > lid + 0.15) & (ny < lid + 0.75) & (np.abs(nx) < 0.85)   # dark circles
    lid_band = (upper | under).astype(np.uint8) * 255
    hmask = Image.fromarray(np.minimum(np.asarray(hatch), lid_band).astype(np.uint8))
    pil.paste(Image.new("RGB", pil.size, INK), (0, 0), hmask)

    # Ink tears dripping from the lower lid.
    for t in (-0.35, 0.05, 0.42):
        x0 = cx + t * ew
        y0 = cy + (1 - t * t) ** 0.75 * eh
        ln = h * rng.uniform(0.12, 0.3)
        wd = max(3, w // 240)
        d.line([(x0, y0), (x0, y0 + ln)], fill=INK, width=wd)
        d.ellipse([x0 - wd * 1.4, y0 + ln - wd, x0 + wd * 1.4, y0 + ln + wd * 1.8], fill=INK)

    return pil.filter(ImageFilter.GaussianBlur(0.6))


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

HERO_PARAMS = dict(
    method="Atkinson", pixel_size=2, threshold=112, color=BONE,
    brightness=1.05, contrast=1.45, palette_name="B&W",
    glow_radius=10, glow_intensity=38,
    glow_gradient=[(40, 0, 80), (150, 0, 255), (255, 120, 255)], glow_mode="Luminance",
    layer=dict(enabled=True, mask_mode="Center (radial)", mask_pos=82, feather=6,
               params=dict(method="Bayer 8x8", palette_name="Witch House", pixel_size=2)),
    fx=dict(scanlines=18, chroma=22, vignette=62, noise=6, seed=3),
)


def font(px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(ROOT / "fonts" / "VT323-Regular.ttf"), px)
    except OSError:
        return ImageFont.load_default()


def glow_text(img: Image.Image, xy, text: str, f, fill, glow, radius: int, anchor="mm", split=0):
    halo = Image.new("L", img.size, 0)
    ImageDraw.Draw(halo).text(xy, text, font=f, fill=255, anchor=anchor, stroke_width=radius // 3, stroke_fill=255)
    halo = halo.filter(ImageFilter.GaussianBlur(radius))
    img.paste(Image.new("RGB", img.size, glow), (0, 0), halo.point(lambda v: min(255, int(v * 1.8))))
    d = ImageDraw.Draw(img)
    if split:
        d.text((xy[0] - split, xy[1]), text, font=f, fill=(255, 40, 120), anchor=anchor)
        d.text((xy[0] + split, xy[1]), text, font=f, fill=(40, 220, 255), anchor=anchor)
    d.text(xy, text, font=f, fill=fill, anchor=anchor)


def label(img: Image.Image, text: str, size: int = 22) -> Image.Image:
    """Dark caption bar under a tile."""
    w, h = img.size
    bar = 30
    out = Image.new("RGB", (w, h + bar), INK)
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    d.line([(0, h), (w, h)], fill=(61, 43, 87), width=1)
    d.text((10, h + bar // 2), text.upper(), font=font(size), fill=VIOLET, anchor="lm")
    return out


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def hero(src_big: Image.Image) -> Image.Image:
    art = render(src_big, HERO_PARAMS).convert("RGB")
    w, h = art.size
    glow_text(art, (w // 2, int(h * 0.835)), "DITHER GUY", font(int(h * 0.19)), BONE, VIOLET, 14, split=2)
    glow_text(art, (w // 2, int(h * 0.94)), "retro dithering for images · video · webcam",
              font(int(h * 0.058)), (200, 170, 255), (60, 0, 110), 6)
    return art


def before_after(src: Image.Image) -> Image.Image:
    out = render(src, HERO_PARAMS).convert("RGB")
    w, h = out.size
    comp = out.copy()
    split = int(w * 0.42)
    comp.paste(src.crop((0, 0, split, h)), (0, 0))
    d = ImageDraw.Draw(comp)
    d.rectangle([split - 1, 0, split + 1, h], fill=VIOLET)
    d.rectangle([split - 5, h // 2 - 18, split + 5, h // 2 + 18], fill=VIOLET)
    f = font(28)
    for txt, x, anc in (("BEFORE", split - 14, "rm"), ("AFTER", split + 14, "lm")):
        glow_text(comp, (x, 26), txt, f, BONE, (40, 0, 80), 4, anchor=anc)
    return comp


PRESET_PICKS = [
    "Cybersigilism", "Cybersigil Blood", "Witch House", "Ghost Signal",
    "Noir Film", "Blood Moon", "Ink Sketch", "Newspaper",
    "Synthwave Sunset", "Matrix Rain", "Thermal Vision", "Holographic",
]


def preset_grid(src: Image.Image, cols: int = 4) -> Image.Image:
    from PySide6.QtWidgets import QApplication
    from utils.ui_control_panel import ControlPanel
    QApplication.instance() or QApplication([])
    panel = ControlPanel()
    tiles = []
    for name in PRESET_PICKS:
        panel.set_params(load_preset(name))
        tiles.append(label(render(src, panel.get_params()).convert("RGB"), name))
    tw, th = tiles[0].size
    gap = 6
    rows = (len(tiles) + cols - 1) // cols
    grid = Image.new("RGB", (cols * tw + (cols - 1) * gap, rows * th + (rows - 1) * gap), INK)
    for i, t in enumerate(tiles):
        grid.paste(t, ((i % cols) * (tw + gap), (i // cols) * (th + gap)))
    return grid


ALGOS = ["Floyd-Steinberg", "Atkinson", "Stucki", "Riemersma", "Bayer 8x8", "Halftone", "Crosshatch", "Blue-Noise Mask"]


def algorithm_grid(src: Image.Image, cols: int = 4) -> Image.Image:
    """The same eye through 8 algorithms, one full tile each."""
    tiles = []
    for m in ALGOS:
        p = dict(method=m, pixel_size=1, threshold=118, color=BONE, contrast=1.4, palette_name="B&W")
        tiles.append(label(render(src, p).convert("RGB"), m))
    tw, th = tiles[0].size
    gap = 6
    rows = (len(tiles) + cols - 1) // cols
    grid = Image.new("RGB", (cols * tw + (cols - 1) * gap, rows * th + (rows - 1) * gap), INK)
    for i, t in enumerate(tiles):
        grid.paste(t, ((i % cols) * (tw + gap), (i // cols) * (th + gap)))
    return grid


def divider(w: int = 1280, h: int = 18) -> Image.Image:
    x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
    v = np.clip(1 - np.abs(x) ** 1.6, 0, 1) * np.ones((h, 1), np.float32)
    v *= np.clip(1 - np.abs(np.linspace(-1, 1, h))[:, None] * 0.9, 0, 1)
    rgb = (np.dstack([v * 200, v * 110, v * 255])).astype(np.uint8)
    p = dict(method="Bayer 4x4", pixel_size=2, palette_name="Custom",
             custom_palette=[INK, (61, 43, 87), (120, 60, 200), VIOLET, PINK], color=(255, 255, 255))
    return render(Image.fromarray(rgb, "RGB"), p).convert("RGB")


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    big = ink_eye(1280, 560)
    hero(big).save(out_dir / "hero.png", optimize=True)
    mid = ink_eye(640, 420, seed=13)
    before_after(mid).save(out_dir / "before_after.png", optimize=True)
    small = ink_eye(320, 210, seed=13)
    preset_grid(small).save(out_dir / "presets.png", optimize=True)
    algorithm_grid(small).save(out_dir / "algorithms.png", optimize=True)
    divider().save(out_dir / "divider.png", optimize=True)
    big.save(out_dir / "source.png", optimize=True)   # used for the UI screenshot
    for f in sorted(out_dir.glob("*.png")):
        print("wrote", f, Image.open(f).size)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs")
