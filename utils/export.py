"""Image export: raster formats with integer upscaling, indexed PNG, SVG, ASCII text."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

EXPORT_FORMATS = {
    # label: (extension, description)
    "PNG":             (".png",  "Lossless"),
    "PNG (indexed)":   (".png",  "Palette PNG — smallest lossless file for few colours"),
    "JPEG":            (".jpg",  "Lossy, small (blurs dither patterns)"),
    "WEBP (lossless)": (".webp", "Lossless, smaller than PNG"),
    "GIF":             (".gif",  "Up to 256 colours"),
    "SVG (vector)":    (".svg",  "Pixels as vector shapes — scales without blur"),
    "TXT (ASCII)":     (".txt",  "The characters themselves (uses the ASCII settings)"),
}
SCALES = [1, 2, 3, 4, 6, 8]
SVG_MAX_SHAPES = 400_000


def upscale(img: Image.Image, scale: int) -> Image.Image:
    return img if scale <= 1 else img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def to_indexed(img: Image.Image) -> Image.Image:
    rgb = img.convert("RGB")
    n = len(np.unique(np.asarray(rgb).reshape(-1, 3), axis=0))
    return rgb.quantize(colors=min(256, max(2, n)), method=Image.Quantize.FASTOCTREE,
                        dither=Image.Dither.NONE)


def block_size(img: Image.Image, hint: int) -> int:
    """Largest block (<= hint) the image is made of, so SVG uses one shape per block."""
    w, h = img.size
    for b in range(max(1, hint), 1, -1):
        if w % b or h % b:
            continue
        small = img.resize((w // b, h // b), Image.NEAREST)
        if small.resize((w, h), Image.NEAREST).tobytes() == img.tobytes():
            return b
    return 1


def svg_string(img: Image.Image, block: int = 1, scale: int = 1) -> str:
    """One <path> per colour; each horizontal run of equal blocks is one rectangle."""
    rgb = img.convert("RGB")
    if block > 1:
        rgb = rgb.resize((rgb.width // block, rgb.height // block), Image.NEAREST)
    a = np.asarray(rgb, dtype=np.uint32)
    key = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    h, w = key.shape
    paths: dict[int, list[str]] = {}
    shapes = 0
    for y in range(h):
        row = key[y]
        cut = np.flatnonzero(np.diff(row)) + 1
        starts = np.concatenate(([0], cut))
        ends = np.concatenate((cut, [w]))
        for s, e in zip(starts, ends):
            paths.setdefault(int(row[s]), []).append(f"M{s} {y}h{e - s}v1h{s - e}z")
        shapes += len(starts)
        if shapes > SVG_MAX_SHAPES:
            raise ValueError(
                f"Too detailed for SVG (> {SVG_MAX_SHAPES:,} shapes). "
                "Use a bigger pixel size, fewer colours, or turn off glow / FX.")
    # Most frequent colour becomes the background to save shapes.
    counts = {c: len(v) for c, v in paths.items()}
    bg = max(counts, key=counts.get)
    W, H = w * block * scale, h * block * scale
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {w} {h}" shape-rendering="crispEdges">',
           f'<rect width="{w}" height="{h}" fill="#{bg:06x}"/>']
    for c, segs in paths.items():
        if c != bg:
            out.append(f'<path fill="#{c:06x}" d="{"".join(segs)}"/>')
    out.append("</svg>")
    return "\n".join(out)


def export_image(img: Image.Image, path: str, fmt: str, scale: int = 1,
                 params: Optional[dict] = None, source: Optional[Image.Image] = None) -> None:
    """Write `img` (the rendered result) to `path` in the chosen format."""
    params = params or {}
    if fmt == "TXT (ASCII)":
        from .pipeline import _base, ascii_text
        if source is None:
            raise ValueError("No source image for ASCII export.")
        base = _base(source, {k: v for k, v in params.items() if k not in ("fx",)}, False, False)
        Path(path).write_text(ascii_text(base, params), encoding="utf-8")
        return
    if fmt == "SVG (vector)":
        b = block_size(img, int(params.get("pixel_size", 1)))
        Path(path).write_text(svg_string(img, b, scale), encoding="utf-8")
        return
    out = upscale(img.convert("RGB"), scale)
    if fmt == "PNG (indexed)":
        to_indexed(out).save(path, optimize=True)
    elif fmt == "JPEG":
        out.save(path, quality=95, subsampling=0)
    elif fmt == "WEBP (lossless)":
        out.save(path, lossless=True)
    elif fmt == "GIF":
        to_indexed(out).save(path)
    else:
        out.save(path)
