from __future__ import annotations

import functools
import numpy as np

_BAYER_2x2 = np.array([[0, 192], [128, 64]], dtype=np.float32)

_BAYER_4x4 = np.array([
    [  0, 128,  32, 160], [192,  64, 224,  96],
    [ 48, 176,  16, 144], [240, 112, 208,  80],
], dtype=np.float32)

_BAYER_8x8 = np.array([
    [  0, 128,  32, 160,   8, 136,  40, 168], [192,  64, 224,  96, 200,  72, 232, 104],
    [ 48, 176,  16, 144,  56, 184,  24, 152], [240, 112, 208,  80, 248, 120, 216,  88],
    [ 12, 140,  44, 172,   4, 132,  36, 164], [204,  76, 236, 108, 196,  68, 228, 100],
    [ 60, 188,  28, 156,  52, 180,  20, 148], [252, 124, 220,  92, 244, 116, 212,  84],
], dtype=np.float32)

_CLUSTER_4x4 = np.array([
    [12,  5,  6, 13], [ 4,  0,  1,  7],
    [11,  3,  2,  8], [15, 10,  9, 14],
], dtype=np.float32) * (255.0 / 16.0)

_HALFTONE_4x4 = np.array([
    [ 7, 13, 11,  4], [12, 16, 14,  8],
    [10, 15,  6,  2], [ 5,  9,  3,  1],
], dtype=np.float32) * (255.0 / 17.0)

_PATTERN_8x8 = np.fromfunction(
    lambda i, j: ((i + j) % 8) * 32.0, (8, 8), dtype=np.float32)

_BLUE_NOISE_8x8 = np.array([
    [0.938, 0.250, 0.688, 0.063, 0.875, 0.188, 0.625, 0.125],
    [0.375, 0.813, 0.500, 0.938, 0.313, 0.750, 0.438, 0.563],
    [0.688, 0.125, 0.875, 0.250, 0.625, 0.063, 0.938, 0.188],
    [0.188, 0.625, 0.063, 0.750, 0.125, 0.500, 0.250, 0.813],
    [0.813, 0.438, 0.563, 0.375, 0.875, 0.313, 0.688, 0.063],
    [0.313, 0.938, 0.188, 0.813, 0.063, 0.938, 0.125, 0.563],
    [0.563, 0.063, 0.750, 0.438, 0.563, 0.375, 0.813, 0.313],
    [0.063, 0.500, 0.313, 0.875, 0.250, 0.688, 0.438, 0.750],
], dtype=np.float32) * 255.0

_VOID_CLUSTER_8x8 = np.array([
    [  3, 200,  56, 168,  24, 216,  72, 184], [136,  88, 240, 104, 152,  40, 248, 120],
    [ 48, 176,  16, 224,  64, 192,   8, 160], [208,  80, 144,  32, 232,  96, 128,  16],
    [ 28, 228,  60, 172,   4, 204,  52, 180], [164,  44, 252, 116, 140,  68, 236, 108],
    [ 76, 196,  20, 148,  84, 212,  36, 156], [220,  92, 132,  12, 244, 124, 100,  68],
], dtype=np.float32)

_DOT_CLASS = np.array([
    [0, 2, 4, 6], [1, 3, 5, 7], [0, 2, 4, 6], [1, 3, 5, 7],
], dtype=np.float32)

ORDERED_MATRICES: dict[str, np.ndarray] = {
    "Bayer 2x2":        _BAYER_2x2,
    "Bayer 4x4":        _BAYER_4x4,
    "Bayer 8x8":        _BAYER_8x8,
    "Clustered-Dot":    _CLUSTER_4x4,
    "Halftone":         _HALFTONE_4x4,
    "Blue-Noise":       _BLUE_NOISE_8x8,
    "Void-and-Cluster": _VOID_CLUSTER_8x8,
    "Pattern":          _PATTERN_8x8,
}


def normalize_matrix(values) -> np.ndarray:
    """Turn any user grid of numbers into thresholds 0..255 by rank.

    Equal values share a rank, so e.g. [[0, 1], [1, 0]] gives a checker.
    Returns a Bayer 4x4 when the input is empty or malformed.
    """
    try:
        m = np.asarray(values, dtype=np.float64)
        if m.ndim != 2 or m.size < 2 or m.shape[0] > 32 or m.shape[1] > 32:
            raise ValueError
    except (TypeError, ValueError):
        return _BAYER_4x4
    flat = m.ravel()
    uniq = np.unique(flat)
    ranks = np.searchsorted(uniq, flat).astype(np.float64)
    n = len(uniq)
    out = (ranks + 0.5) / n * 255.0
    return out.reshape(m.shape).astype(np.float32)


# Starting points for the "Custom Matrix" editor.
MATRIX_TEMPLATES: dict[str, list[list[int]]] = {
    "Bayer 4x4":      [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    "Diagonal Lines": [[0, 1, 2, 3], [1, 2, 3, 0], [2, 3, 0, 1], [3, 0, 1, 2]],
    "Horizontal Lines": [[0, 0, 0, 0], [2, 2, 2, 2], [1, 1, 1, 1], [3, 3, 3, 3]],
    "Vertical Lines": [[0, 2, 1, 3]] * 4,
    "Cross":          [[4, 2, 4, 4], [2, 0, 2, 4], [4, 2, 4, 4], [4, 4, 4, 4]],
    "Dots":           [[3, 2, 3, 4], [2, 0, 1, 4], [3, 1, 2, 4], [4, 4, 4, 4]],
    "Checker":        [[0, 1], [1, 0]],
    "Bricks":         [[0, 0, 0, 1, 0, 0, 0, 1], [2, 2, 2, 1, 2, 2, 2, 1],
                       [0, 1, 0, 0, 0, 1, 0, 0], [2, 1, 2, 2, 2, 1, 2, 2]],
    "Diamond":        [[6, 4, 3, 5, 6], [4, 2, 1, 2, 4], [3, 1, 0, 1, 3], [5, 2, 1, 2, 5], [6, 4, 3, 5, 6]],
    "Zigzag":         [[0, 3, 6, 3], [1, 4, 7, 4], [2, 5, 8, 5], [1, 4, 7, 4]],
}


def tile(matrix: np.ndarray, h: int, w: int) -> np.ndarray:
    mh, mw = matrix.shape
    return np.tile(matrix, ((h + mh - 1) // mh, (w + mw - 1) // mw))[:h, :w]


# Flat registry — avoids a separate dict comprehension copy
_MATRIX_REGISTRY: dict[str, np.ndarray] = {
    **ORDERED_MATRICES,
    "dot_class": _DOT_CLASS,
}


@functools.lru_cache(maxsize=64)
def tile_cached(matrix_id: str, h: int, w: int) -> np.ndarray:
    """Cache tiled matrices by (name, h, w) — avoids hashing array data."""
    return tile(_MATRIX_REGISTRY[matrix_id], h, w)
