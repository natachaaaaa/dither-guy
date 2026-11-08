"""Exports, plus regression tests for the bugs fixed in the review."""
import re
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

from utils.export import export_image, svg_string, block_size, to_indexed
from utils.pipeline import render

BASE = dict(method="Bayer 4x4", pixel_size=4, threshold=128, color=(255, 255, 255), palette_name="Synthwave")


def _svg_to_array(svg: str) -> np.ndarray:
    """Rasterise our own simple SVG (rect background + run-length paths)."""
    w, h = map(int, re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups())
    bg = re.search(r'<rect [^>]*fill="#([0-9a-f]{6})"', svg).group(1)
    a = np.zeros((h, w, 3), np.uint8)
    a[:] = [int(bg[i:i + 2], 16) for i in (0, 2, 4)]
    for col, d in re.findall(r'<path fill="#([0-9a-f]{6})" d="([^"]+)"', svg):
        rgb = [int(col[i:i + 2], 16) for i in (0, 2, 4)]
        for x, y, n in re.findall(r"M(\d+) (\d+)h(\d+)", d):
            a[int(y), int(x):int(x) + int(n)] = rgb
    return a


def test_svg_round_trip(sample):
    img = render(sample, BASE)
    b = block_size(img, 4)
    assert b == 4
    back = _svg_to_array(svg_string(img, b))
    small = np.asarray(img.resize((img.width // b, img.height // b), Image.NEAREST))
    assert np.array_equal(back, small)


def test_indexed_png_is_lossless(sample, tmp_path):
    img = render(sample, BASE)
    path = tmp_path / "x.png"
    export_image(img, str(path), "PNG (indexed)", 2)
    back = Image.open(path)
    assert back.mode == "P" and back.size == (img.width * 2, img.height * 2)
    assert np.array_equal(np.asarray(back.convert("RGB"))[::2, ::2], np.asarray(img))
    assert to_indexed(img).mode == "P"


def test_ascii_txt_export(sample, tmp_path):
    path = tmp_path / "x.txt"
    export_image(render(sample, BASE), str(path), "TXT (ASCII)", 1,
                 dict(BASE, ascii=dict(cell=4)), sample)
    assert len(path.read_text(encoding="utf-8").splitlines()) > 5


# ── regressions ──────────────────────────────────────────────────────────

def test_video_kept_when_audio_mux_fails(tmp_path):
    from utils.workers import finalize_video_output
    tmp = tmp_path / "render.mp4"; tmp.write_bytes(b"video")
    final = tmp_path / "final.mp4"
    assert finalize_video_output(str(tmp), str(final), muxed=False) is None
    assert final.read_bytes() == b"video" and not tmp.exists()


def test_video_temp_removed_after_successful_mux(tmp_path):
    from utils.workers import finalize_video_output
    tmp = tmp_path / "render.mp4"; tmp.write_bytes(b"video")
    final = tmp_path / "final.mp4"; final.write_bytes(b"muxed")
    assert finalize_video_output(str(tmp), str(final), muxed=True) is None
    assert final.read_bytes() == b"muxed" and not tmp.exists()


def test_opencl_without_gpu_does_not_crash(monkeypatch):
    """_try_opencl must return 4 values even when no GPU is found."""
    fake = types.ModuleType("pyopencl")
    fake.get_platforms = lambda: []
    fake.array = types.ModuleType("pyopencl.array")
    monkeypatch.setitem(sys.modules, "pyopencl", fake)
    monkeypatch.setitem(sys.modules, "pyopencl.array", fake.array)
    from utils.gpu_kernels import _try_opencl
    assert _try_opencl() == (None, None, None, None)


def test_presets_dir_does_not_depend_on_cwd(monkeypatch, tmp_path):
    import importlib
    import utils.presets as presets
    monkeypatch.chdir(tmp_path)
    importlib.reload(presets)
    assert presets.PRESETS_DIR.is_absolute()
    assert len(presets.list_presets()) >= 50


def test_preset_download_keeps_ssl_verification():
    src = Path(__file__).resolve().parent.parent.joinpath("utils", "presets.py").read_text(encoding="utf-8")
    assert "CERT_NONE" not in src and "check_hostname = False" not in src
