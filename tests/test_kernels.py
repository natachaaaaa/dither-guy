"""Dithering kernels: tone preservation, palette output, custom matrices."""
import numpy as np
import pytest
from PIL import Image

from utils.constants import METHOD_GROUPS
from utils.dither_kernels import _BW_DISPATCH, apply_dither, palette_dither
from utils.matrices import normalize_matrix, MATRIX_TEMPLATES

GRAD = np.tile(np.linspace(0, 255, 256, dtype=np.float32), (96, 1))


@pytest.mark.parametrize("method", sorted(_BW_DISPATCH))
def test_error_diffusion_keeps_tone(method):
    out = _BW_DISPATCH[method](GRAD.copy(), 128.0)
    assert out.dtype == np.uint8 and set(np.unique(out)) <= {0, 255}
    # average brightness of each 32-column band stays close to the source
    src = GRAD.reshape(96, 8, 32).mean(axis=(0, 2))
    got = out.reshape(96, 8, 32).mean(axis=(0, 2))
    # Atkinson only diffuses 6/8 of the error on purpose (crisper, clipped extremes).
    tol = 25 if method == "Atkinson" else 12
    assert np.abs(src - got).max() < tol, (method, np.abs(src - got).max())


def test_palette_dither_only_uses_palette_colours():
    img = Image.fromarray(np.dstack([GRAD, GRAD[::-1], np.full_like(GRAD, 90)]).astype(np.uint8))
    pal = [(0, 0, 0), (255, 0, 128), (0, 220, 255), (255, 255, 255)]
    out = np.asarray(palette_dither(img, pal, "Stevenson-Arce")).reshape(-1, 3)
    assert {tuple(c) for c in np.unique(out, axis=0)} <= set(pal)


@pytest.mark.parametrize("method", [m for ms in METHOD_GROUPS.values() for m in ms])
def test_every_method_runs(method):
    img = Image.fromarray(np.dstack([GRAD] * 3).astype(np.uint8))
    out = apply_dither(img, 2, 128, (255, 255, 255), method)
    assert out.size == (256, 96)


def test_normalize_matrix_ranks_values():
    m = normalize_matrix([[0, 1], [1, 0]])
    assert m.shape == (2, 2) and m[0, 0] == m[1, 1] < m[0, 1] == m[1, 0]
    assert normalize_matrix("garbage").shape == (4, 4)       # falls back to Bayer
    for tpl in MATRIX_TEMPLATES.values():
        n = normalize_matrix(tpl)
        assert n.min() > 0 and n.max() < 255


def test_custom_matrix_changes_pattern():
    img = Image.fromarray(np.dstack([GRAD] * 3).astype(np.uint8))
    a = np.asarray(apply_dither(img, 1, 128, (255, 255, 255), "Custom Matrix",
                                custom_matrix=MATRIX_TEMPLATES["Checker"]))
    b = np.asarray(apply_dither(img, 1, 128, (255, 255, 255), "Custom Matrix",
                                custom_matrix=MATRIX_TEMPLATES["Horizontal Lines"]))
    assert not np.array_equal(a, b)
