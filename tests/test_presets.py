"""Every preset loads in the real control panel and renders like its reference.

Reference thumbnails live in tests/snapshots/. After an intended visual change,
regenerate them with:  python tests/update_snapshots.py
"""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from utils.palettes import PALETTES
from utils.presets import list_presets, load_preset

SNAP_DIR = Path(__file__).parent / "snapshots"
PRESETS = list_presets()
# Allow tiny numeric drift between platforms / Numba versions.
MAX_MEAN_DIFF = 6.0


def render_preset(panel, name, sample):
    from utils.pipeline import render
    panel.set_params(load_preset(name))
    return render(sample, panel.get_params())


def test_presets_exist():
    assert len(PRESETS) >= 50


@pytest.mark.parametrize("name", PRESETS)
def test_preset_file_is_valid(name):
    p = load_preset(name)
    assert isinstance(p, dict) and p.get("category")
    assert p.get("palette_name", "B&W").lower() in {k.lower() for k in PALETTES}, p.get("palette_name")
    json.dumps(p)


@pytest.mark.parametrize("name", PRESETS)
def test_preset_matches_snapshot(qapp, sample, name):
    from utils.ui_control_panel import ControlPanel
    panel = ControlPanel()
    out = render_preset(panel, name, sample)
    snap = SNAP_DIR / f"{name}.png"
    if not snap.exists():
        pytest.skip("no snapshot yet (run tests/update_snapshots.py)")
    ref = np.asarray(Image.open(snap).convert("RGB"), dtype=np.float32)
    got = np.asarray(out.convert("RGB"), dtype=np.float32)
    assert got.shape == ref.shape
    diff = np.abs(got - ref).mean()
    assert diff < MAX_MEAN_DIFF, f"{name}: mean diff {diff:.2f}"


def test_panel_round_trip(qapp):
    from utils.ui_control_panel import ControlPanel
    panel = ControlPanel()
    for name in PRESETS:
        panel.set_params(load_preset(name))
        p = panel.get_params()
        panel.set_params(json.loads(json.dumps(p, default=list)))
        assert json.dumps(panel.get_params(), default=list, sort_keys=True) == \
            json.dumps(p, default=list, sort_keys=True), name


def test_settings_undo_redo(qapp):
    from utils.ui_control_panel import ControlPanel
    panel = ControlPanel()
    panel._hist_timer.stop(); panel._snapshot()
    start = panel.pixel_sl.value()
    panel.pixel_sl.setValue(start + 5); panel._snapshot()
    assert panel.undo_settings() and panel.pixel_sl.value() == start
    assert panel.redo_settings() and panel.pixel_sl.value() == start + 5
