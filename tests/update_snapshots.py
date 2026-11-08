"""Regenerate tests/snapshots/*.png from the current presets.

Run after an intended visual change:  python tests/update_snapshots.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from utils.pipeline import render  # noqa: E402
from utils.presets import list_presets, load_preset  # noqa: E402
from utils.ui_control_panel import ControlPanel  # noqa: E402
from utils.ui_preset_browser import sample_image  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    out_dir = Path(__file__).parent / "snapshots"
    out_dir.mkdir(exist_ok=True)
    src = sample_image(160, 112)
    panel = ControlPanel()
    for name in list_presets():
        panel.set_params(load_preset(name))
        render(src, panel.get_params()).save(out_dir / f"{name}.png", optimize=True)
        print("updated", name)


if __name__ == "__main__":
    main()
