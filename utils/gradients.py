"""Glow gradients: templates and sampling.

A gradient is a list of RGB stops, evenly spaced from 0 to 1.
`None` means "Source": the glow keeps the colours of the image itself.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

SOURCE = "Source"
CUSTOM = "Custom"

GLOW_GRADIENTS: dict[str, Optional[list[tuple[int, int, int]]]] = {
    SOURCE:        None,
    "Synthwave":   [(255, 0, 128), (140, 30, 255), (0, 220, 255)],
    "Cyberpunk":   [(252, 238, 10), (255, 0, 140), (0, 240, 255)],
    "Vaporwave":   [(255, 113, 206), (185, 103, 255), (1, 205, 254)],
    "Outrun":      [(255, 60, 0), (255, 0, 110), (90, 0, 180)],
    "Neon Blood":  [(60, 0, 0), (255, 0, 40), (255, 140, 140)],
    "Matrix":      [(0, 40, 0), (0, 255, 65), (200, 255, 200)],
    "Toxic":       [(40, 80, 0), (170, 255, 0), (240, 255, 120)],
    "Ice":         [(0, 30, 90), (0, 170, 255), (230, 250, 255)],
    "Fire":        [(80, 0, 0), (255, 60, 0), (255, 200, 0), (255, 255, 200)],
    "Inferno":     [(20, 0, 40), (180, 20, 80), (255, 120, 0), (255, 240, 120)],
    "Sunset":      [(255, 94, 77), (255, 154, 0), (255, 206, 84)],
    "Aurora":      [(0, 255, 160), (0, 160, 255), (180, 0, 255)],
    "Holographic": [(255, 160, 220), (160, 220, 255), (200, 255, 200), (255, 240, 170)],
    "Chrome":      [(40, 40, 50), (200, 200, 215), (255, 255, 255), (150, 140, 200)],
    "Gold":        [(90, 50, 0), (255, 190, 40), (255, 245, 190)],
    "Ultraviolet": [(30, 0, 80), (150, 0, 255), (255, 120, 255)],
    "Hyperpop":    [(255, 0, 200), (170, 255, 0), (0, 230, 255)],
    "Witch House": [(10, 0, 20), (90, 0, 140), (220, 220, 255)],
    "Thermal":     [(0, 0, 80), (120, 0, 200), (255, 0, 0), (255, 200, 0), (255, 255, 255)],
    "Rainbow":     [(255, 0, 0), (255, 170, 0), (255, 255, 0), (0, 220, 0),
                    (0, 160, 255), (120, 0, 255), (255, 0, 200)],
    "Mono White":  [(255, 255, 255)],
}

GLOW_MODES: list[str] = ["Luminance", "Horizontal", "Vertical", "Diagonal", "Radial"]


def sample(stops: Sequence[Sequence[int]], t: np.ndarray) -> np.ndarray:
    """Map t (any shape, 0..1) to colours; returns float32 array of shape t.shape + (3,)."""
    pal = np.asarray(stops, dtype=np.float32).reshape(-1, 3)
    if len(pal) == 1:
        return np.broadcast_to(pal[0], t.shape + (3,)).astype(np.float32)
    xs = np.linspace(0.0, 1.0, len(pal), dtype=np.float32)
    t = np.clip(t, 0.0, 1.0)
    return np.stack([np.interp(t, xs, pal[:, c]) for c in range(3)], axis=-1).astype(np.float32)


def position_map(h: int, w: int, mode: str, luma: np.ndarray) -> np.ndarray:
    """Return the 0..1 coordinate that drives the gradient for each pixel."""
    if mode == "Horizontal":
        return np.broadcast_to(np.linspace(0, 1, w, dtype=np.float32)[None, :], (h, w))
    if mode == "Vertical":
        return np.broadcast_to(np.linspace(0, 1, h, dtype=np.float32)[:, None], (h, w))
    if mode == "Diagonal":
        x = np.linspace(0, 0.5, w, dtype=np.float32)[None, :]
        y = np.linspace(0, 0.5, h, dtype=np.float32)[:, None]
        return x + y
    if mode == "Radial":
        x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        y = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        return np.sqrt(x * x + y * y) / np.sqrt(2.0)
    return luma  # "Luminance": dim halo -> first stop, bright core -> last stop
