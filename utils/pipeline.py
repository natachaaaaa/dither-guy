"""Single rendering entry point: params dict -> dithered image.

Every caller (live preview, image save, batch, video preview, video export)
goes through `render()`, so new options only need to be added here.

On top of `apply_dither` it adds:
  - layers  : a second look (from a preset) blended in through a mask
  - fx      : CRT (scanlines, chromatic aberration, curvature, noise,
              vignette) and glitch (RGB split, block shift, pixel sorting)
  - ascii   : render the result as text characters
  - animate : interpolate one parameter over a video's duration
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter

from .dither_kernels import apply_dither

# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------

ANIMATABLE: dict[str, tuple[str, float]] = {
    # label: (param key, UI scale)  -- UI shows value * scale
    "Threshold":      ("threshold", 1),
    "Hue":            ("hue_rotate", 1),
    "Pixel Size":     ("pixel_size", 1),
    "Glow Intensity": ("glow_intensity", 1),
    "Glow Radius":    ("glow_radius", 1),
    "Brightness":     ("brightness", 100),
    "Contrast":       ("contrast", 100),
    "Saturation":     ("saturation", 100),
}
ANIM_CURVES = ["Linear", "Ping-Pong", "Sine Loop"]
_INT_PARAMS = {"threshold", "hue_rotate", "pixel_size", "glow_intensity", "glow_radius"}


def animate_params(p: dict, t: Optional[float]) -> dict:
    """Return a copy of p with the animated parameter set for time t (0..1)."""
    anim = p.get("animate") or {}
    if t is None or not anim.get("enabled") or anim.get("param") not in ANIMATABLE:
        return p
    key, scale = ANIMATABLE[anim["param"]]
    start = float(p.get(key, 0))
    end = float(anim.get("end", 0)) / scale
    curve = anim.get("curve", "Linear")
    t = min(max(t, 0.0), 1.0)
    if curve == "Ping-Pong":
        f = 1.0 - abs(2.0 * t - 1.0)
    elif curve == "Sine Loop":
        f = 0.5 - 0.5 * math.cos(2.0 * math.pi * t)
    else:
        f = t
    v = start + (end - start) * f
    q = dict(p)
    q[key] = int(round(v)) % 360 if key == "hue_rotate" else (
        max(1, int(round(v))) if key == "pixel_size" else (int(round(v)) if key in _INT_PARAMS else v))
    return q


# ---------------------------------------------------------------------------
# Base dither
# ---------------------------------------------------------------------------

def _base(img: Image.Image, p: dict, preview: bool, is_video: bool) -> Image.Image:
    return apply_dither(
        img,
        p.get("pixel_size", 4), p.get("threshold", 128),
        tuple(p.get("color", (255, 255, 255))), p.get("method", "Floyd-Steinberg"),
        p.get("brightness", 1.0), p.get("contrast", 1.0),
        p.get("blur", 0), p.get("sharpen", 0),
        p.get("glow_radius", 0), p.get("glow_intensity", 0),
        preview=preview,
        palette_name=p.get("palette_name", "B&W"),
        custom_palette=p.get("custom_palette"),
        saturation=p.get("saturation", 1.0),
        hue_rotate=p.get("hue_rotate", 0),
        pre_denoise=p.get("pre_denoise", 0),
        pre_smooth=p.get("pre_smooth", 0),
        post_denoise=p.get("post_denoise", 0),
        post_smooth=p.get("post_smooth", 0),
        is_video=is_video,
        glow_gradient=p.get("glow_gradient"),
        glow_mode=p.get("glow_mode", "Luminance"),
        custom_matrix=p.get("custom_matrix"),
    )


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------

MASK_MODES = ["Bright areas", "Dark areas", "Left → Right", "Top → Bottom", "Center (radial)", "Mask image"]


@lru_cache(maxsize=4)
def _load_mask_file(path: str) -> Optional[Image.Image]:
    try:
        return Image.open(path).convert("L")
    except Exception:
        return None


def build_mask(img: Image.Image, layer: dict) -> np.ndarray:
    """Float mask in 0..1 (1 = show layer B), same size as img."""
    w, h = img.size
    mode = layer.get("mask_mode", MASK_MODES[0])
    pos = float(layer.get("mask_pos", 50)) / 100.0        # threshold / split position
    feather = max(0.01, float(layer.get("feather", 10)) / 100.0)
    if mode in ("Bright areas", "Dark areas"):
        v = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
        if mode == "Dark areas":
            v = 1.0 - v
            pos = 1.0 - pos
    elif mode == "Left → Right":
        v = np.broadcast_to(np.linspace(0, 1, w, dtype=np.float32)[None, :], (h, w))
    elif mode == "Top → Bottom":
        v = np.broadcast_to(np.linspace(0, 1, h, dtype=np.float32)[:, None], (h, w))
    elif mode == "Center (radial)":
        x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        y = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        v = 1.0 - np.clip(np.sqrt(x * x + y * y) / math.sqrt(2.0), 0, 1)
    else:  # Mask image: white = layer B
        m = _load_mask_file(layer.get("mask_path") or "")
        if m is None:
            return np.zeros((h, w), dtype=np.float32)
        v = np.asarray(m.resize((w, h), Image.BILINEAR), dtype=np.float32) / 255.0
        pos = 0.5
    # Smooth step around pos with width = feather.
    return np.clip((v - pos) / feather + 0.5, 0.0, 1.0).astype(np.float32)


def _composite(a: Image.Image, b: Image.Image, mask: np.ndarray) -> Image.Image:
    size = (mask.shape[1], mask.shape[0])
    aa = np.asarray(a.convert("RGB").resize(size, Image.NEAREST), dtype=np.float32)
    bb = np.asarray(b.convert("RGB").resize(size, Image.NEAREST), dtype=np.float32)
    m = mask[..., None]
    return Image.fromarray((aa * (1.0 - m) + bb * m).astype(np.uint8), "RGB")


# ---------------------------------------------------------------------------
# FX: CRT + glitch
# ---------------------------------------------------------------------------

FX_DEFAULTS = {
    "scanlines": 0, "chroma": 0, "curvature": 0, "noise": 0, "vignette": 0,
    "rgb_split": 0, "block_glitch": 0, "pixel_sort": 0, "seed": 0,
}


def _shift_x(ch: np.ndarray, d: int) -> np.ndarray:
    if d == 0:
        return ch
    out = np.empty_like(ch)
    if d > 0:
        out[:, d:] = ch[:, :-d]; out[:, :d] = ch[:, :1]
    else:
        out[:, :d] = ch[:, -d:]; out[:, d:] = ch[:, -1:]
    return out


def apply_fx(img: Image.Image, fx: Optional[dict], frame: int = 0) -> Image.Image:
    if not fx or not any(fx.get(k, 0) for k in FX_DEFAULTS if k != "seed"):
        return img
    a = np.asarray(img.convert("RGB"), dtype=np.float32).copy()
    h, w, _ = a.shape
    rng = np.random.default_rng(int(fx.get("seed", 0)) * 7919 + frame)
    unit = max(1, round(min(w, h) / 360))  # effect scale follows resolution

    # ── Glitch ────────────────────────────────────────────────────────────
    if fx.get("block_glitch"):
        amt = fx["block_glitch"] / 100.0
        for _ in range(int(2 + amt * 30)):
            bh = int(rng.integers(max(2, h // 80), max(3, h // 8)))
            y0 = int(rng.integers(0, max(1, h - bh)))
            dx = int(rng.integers(-1, 2) * rng.integers(1, max(2, int(w * 0.15 * amt) + 2)))
            a[y0:y0 + bh] = np.roll(a[y0:y0 + bh], dx, axis=1)
    if fx.get("pixel_sort"):
        # Sort random horizontal segments by luminance (works on 2-colour
        # images too, where threshold-based runs would be uniform).
        amt = fx["pixel_sort"] / 100.0
        luma = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        rows = rng.random(h) < (0.1 + 0.6 * amt)
        max_len = max(4, int(w * (0.1 + 0.6 * amt)))
        for y in np.nonzero(rows)[0]:
            for _ in range(int(rng.integers(1, 4))):
                n = int(rng.integers(4, max_len + 1))
                s = int(rng.integers(0, max(1, w - n)))
                order = np.argsort(luma[y, s:s + n], kind="stable")
                a[y, s:s + n] = a[y, s:s + n][order]
                luma[y, s:s + n] = luma[y, s:s + n][order]
    if fx.get("rgb_split"):
        d = max(1, int(fx["rgb_split"] / 100.0 * w * 0.03))
        a[..., 0] = _shift_x(a[..., 0], d)
        a[..., 2] = _shift_x(a[..., 2], -d)

    # ── CRT ───────────────────────────────────────────────────────────────
    if fx.get("chroma"):
        # radial-ish aberration: shift R/B horizontally, stronger towards the edges
        d = max(1, int(fx["chroma"] / 100.0 * unit * 6))
        r = _shift_x(a[..., 0], d); b = _shift_x(a[..., 2], -d)
        edge = np.abs(np.linspace(-1, 1, w, dtype=np.float32))[None, :]
        a[..., 0] = a[..., 0] * (1 - edge) + r * edge
        a[..., 2] = a[..., 2] * (1 - edge) + b * edge
    if fx.get("noise"):
        a += rng.normal(0.0, fx["noise"] * 0.6, size=(h, w, 1)).astype(np.float32)
    if fx.get("scanlines"):
        period = max(2, unit * 3)
        dark = (np.arange(h) % period) >= period - max(1, period // 3)
        a[dark] *= 1.0 - fx["scanlines"] / 100.0 * 0.85
    if fx.get("vignette"):
        x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        y = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        r2 = (x * x + y * y) / 2.0
        a *= (1.0 - fx["vignette"] / 100.0 * np.clip(r2 * 1.6, 0, 1) ** 1.5)[..., None]
    if fx.get("curvature"):
        k = fx["curvature"] / 100.0 * 0.25
        x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        y = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        r2 = x * x + y * y
        sx = x * (1 + k * r2) / (1 + k)
        sy = y * (1 + k * r2) / (1 + k)
        ix = np.round((sx + 1) * 0.5 * (w - 1)).astype(np.int32)
        iy = np.round((sy + 1) * 0.5 * (h - 1)).astype(np.int32)
        inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        out = np.zeros_like(a)
        out[inside] = a[np.clip(iy, 0, h - 1), np.clip(ix, 0, w - 1)][inside]
        a = out
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


# ---------------------------------------------------------------------------
# ASCII
# ---------------------------------------------------------------------------

CHARSETS = {
    "Standard": " .:-=+*#%@",
    "Dense":    " .'`^\",:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
    "Blocks":   " ░▒▓█",
    "Binary":   " 01",
    "Hex":      " 0123456789ABCDEF",
    "Lines":    " .-=≡#",
}
ASCII_COLOR_MODES = ["Image colours", "Foreground colour"]


@lru_cache(maxsize=16)
def _glyph_atlas(charset: str, cw: int, chh: int) -> np.ndarray:
    """(n_chars, chh, cw) float32 masks rendered with the bundled pixel font."""
    from PIL import ImageDraw, ImageFont
    from .theme import _FONT_FILE, _PIXEL_FONT
    font = None
    if _PIXEL_FONT:
        try:
            font = ImageFont.truetype(str(_FONT_FILE), int(chh * 1.05))
        except Exception:
            font = None
    if font is None:
        for name in ("consola.ttf", "DejaVuSansMono.ttf", "Menlo.ttc"):
            try:
                font = ImageFont.truetype(name, int(chh * 0.85))
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
    masks = []
    for c in charset:
        im = Image.new("L", (cw * 3, chh * 2), 0)
        d = ImageDraw.Draw(im)
        bbox = d.textbbox((0, 0), c, font=font) if c.strip() else (0, 0, 1, 1)
        gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((cw * 3 - gw) / 2 - bbox[0], (chh * 2 - gh) / 2 - bbox[1]), c, fill=255, font=font)
        g = im.crop((cw, chh // 2, cw * 2, chh // 2 + chh))
        masks.append(np.asarray(g, dtype=np.float32) / 255.0)
    return np.stack(masks)


def _ascii_grid(img: Image.Image, a: dict):
    cell = max(4, int(a.get("cell", 8)))
    cw, chh = cell, cell * 2
    w, h = img.size
    cols, rows = max(1, w // cw), max(1, h // chh)
    small = img.convert("RGB").resize((cols, rows), Image.BOX)
    col = np.asarray(small, dtype=np.float32)
    luma = col @ np.array([0.299, 0.587, 0.114], dtype=np.float32) / 255.0
    if a.get("invert"):
        luma = 1.0 - luma
    chars = CHARSETS.get(a.get("charset", "Standard"), CHARSETS["Standard"])
    idx = np.clip((luma * (len(chars) - 1) + 0.5).astype(np.int32), 0, len(chars) - 1)
    return chars, idx, col, cw, chh


def render_ascii(img: Image.Image, a: dict, fg: tuple = (255, 255, 255)) -> Image.Image:
    chars, idx, col, cw, chh = _ascii_grid(img, a)
    rows, cols = idx.shape
    atlas = _glyph_atlas(chars, cw, chh)
    m = atlas[idx]                                   # rows, cols, chh, cw
    m = m.transpose(0, 2, 1, 3).reshape(rows * chh, cols * cw)
    if a.get("color_mode", ASCII_COLOR_MODES[0]) == "Foreground colour":
        c = np.broadcast_to(np.asarray(fg, dtype=np.float32), (rows, cols, 3))
    else:
        # boost colours so dim cells stay readable
        c = np.clip(col * 1.35 + 30, 0, 255)
    c = np.repeat(np.repeat(c, chh, axis=0), cw, axis=1)
    out = c * m[..., None]
    return Image.fromarray(out.astype(np.uint8), "RGB")


def ascii_text(img: Image.Image, p: dict) -> str:
    chars, idx, *_ = _ascii_grid(img, p.get("ascii") or {})
    return "\n".join("".join(chars[i] for i in row).rstrip() for row in idx)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render(img: Image.Image, p: dict, preview: bool = False, is_video: bool = False,
           t: Optional[float] = None, frame: int = 0) -> Image.Image:
    p = animate_params(p, t)
    out = _base(img, p, preview, is_video)

    layer = p.get("layer") or {}
    if layer.get("enabled") and layer.get("params"):
        pb = dict(p)
        pb.update(layer["params"])
        pb.pop("layer", None)
        out_b = _base(img, pb, preview, is_video)
        out = _composite(out, out_b, build_mask(img.convert("RGB").resize(out.size), layer))

    a = p.get("ascii") or {}
    if a.get("enabled"):
        out = render_ascii(out, a, tuple(p.get("color", (255, 255, 255))))

    return apply_fx(out, p.get("fx"), frame)
