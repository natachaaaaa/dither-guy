"""render(): layers, FX, ASCII, animation, gradient glow."""
import numpy as np
import pytest
from PIL import Image

from utils.gradients import GLOW_GRADIENTS, GLOW_MODES, sample
from utils.dither_kernels import apply_glow
from utils.pipeline import (
    MASK_MODES, animate_params, build_mask, render, ascii_text, apply_fx, FX_DEFAULTS,
)

BASE = dict(method="Bayer 4x4", pixel_size=2, threshold=128, color=(255, 255, 255), palette_name="B&W")


def test_plain_render_size(sample):
    out = render(sample, BASE)
    assert out.size == sample.size and out.mode == "RGB"


@pytest.mark.parametrize("mode", [m for m in MASK_MODES if m != "Mask image"])
def test_masks_are_bounded(sample, mode):
    m = build_mask(sample, dict(mask_mode=mode, mask_pos=50, feather=20))
    assert m.shape == (sample.height, sample.width)
    assert 0.0 <= m.min() and m.max() <= 1.0


def test_layer_split_uses_both_looks(sample):
    p = dict(BASE, layer=dict(enabled=True, mask_mode="Left → Right", mask_pos=50, feather=1,
                              params=dict(palette_name="Synthwave", method="Bayer 8x8")))
    out = np.asarray(render(sample, p))
    left, right = out[:, :40], out[:, -40:]
    # left half stays black & white, right half gets colour
    assert np.abs(left[..., 0].astype(int) - left[..., 1]).max() == 0
    assert np.abs(right[..., 0].astype(int) - right[..., 2]).max() > 0


def test_fx_keep_size_and_change_pixels(sample):
    base = render(sample, BASE)
    for key in FX_DEFAULTS:
        if key == "seed":
            continue
        out = apply_fx(base, {key: 80, "seed": 1})
        assert out.size == base.size, key
        assert not np.array_equal(np.asarray(out), np.asarray(base)), key


def test_ascii(sample):
    p = dict(BASE, ascii=dict(enabled=True, cell=8, charset="Standard"))
    out = render(sample, p)
    assert out.width <= sample.width and out.height <= sample.height
    txt = ascii_text(sample, p)
    assert len(txt.splitlines()) == sample.height // 16


def test_animation_interpolates():
    p = dict(BASE, threshold=0, animate=dict(enabled=True, param="Threshold", end=200, curve="Linear"))
    assert animate_params(p, 0.0)["threshold"] == 0
    assert animate_params(p, 0.5)["threshold"] == 100
    assert animate_params(p, 1.0)["threshold"] == 200
    pp = dict(p, animate=dict(p["animate"], curve="Ping-Pong"))
    assert animate_params(pp, 1.0)["threshold"] == 0
    assert animate_params(p, None) is p          # no time → unchanged


def test_gradient_sampling():
    stops = [(0, 0, 0), (255, 0, 0), (255, 255, 255)]
    c = sample(stops, np.array([0.0, 0.5, 1.0]))
    assert np.allclose(c, [[0, 0, 0], [255, 0, 0], [255, 255, 255]])


@pytest.mark.parametrize("mode", GLOW_MODES)
def test_gradient_glow_tints_halo(sample, mode):
    img = render(sample, BASE)
    out = apply_glow(img, 6, 80, GLOW_GRADIENTS["Synthwave"], mode)
    a = np.asarray(out).astype(int)
    assert out.size == img.size
    assert np.abs(a[..., 0] - a[..., 2]).max() > 30   # glow is no longer grey
