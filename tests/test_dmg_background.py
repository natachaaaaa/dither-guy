"""The macOS DMG background is rendered by the app's own pipeline in CI."""
import importlib.util
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "make_dmg_background.py"


def test_dmg_background_sizes(tmp_path):
    spec = importlib.util.spec_from_file_location("make_dmg_background", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p1, p2 = mod.make(tmp_path)
    assert Image.open(p1).size == (mod.W, mod.H)
    assert Image.open(p2).size == (mod.W * 2, mod.H * 2)
    # icons must sit inside the window
    for x, y in (mod.ICON_POS, mod.APPS_POS):
        assert 64 <= x <= mod.W - 64 and 64 <= y <= mod.H - 64
