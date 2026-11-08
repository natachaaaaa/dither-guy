"""Extra control-panel sections, mixed into ControlPanel.

Kept apart from ui_control_panel.py so that file stays readable:
  - settings undo / redo history
  - eyedropper + palette extraction hooks (handled by the main window)
  - Layer B (second look blended through a mask)
  - CRT / glitch FX, ASCII mode, custom ordered matrix, video animation
"""
from __future__ import annotations

import random
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox,
)

from .pipeline import ANIMATABLE, ANIM_CURVES, ASCII_COLOR_MODES, CHARSETS, FX_DEFAULTS, MASK_MODES
from .presets import list_presets, load_preset
from .theme import _FG2, fs
from .ui_widgets import make_slider

_HISTORY_MAX = 60
_LAYER_SKIP_KEYS = {"layer", "fx", "ascii", "animate"}


class PanelExtrasMixin:
    """Requires: self.params_changed / params_changed_preview signals,
    self._group(title), self.get_params(), self.set_params(p)."""

    # Signals (declared on ControlPanel itself):
    #   pick_requested(str)  "color" | "palette"
    #   extract_palette_requested()

    # ── helpers ────────────────────────────────────────────────────────────

    def _x_slider(self, layout, label, mn, mx, val, fmt="{v}", tip=""):
        _, vl, sl = make_slider(layout, label, mn, mx, val, fmt, tooltip=tip)
        sl.valueChanged.connect(lambda v, l=vl, f=fmt: l.setText(f.format(v=v)))
        sl.valueChanged.connect(lambda _: self.params_changed_preview.emit())
        sl.sliderReleased.connect(self.params_changed.emit)
        self._x_sliders.append((sl, vl, fmt, val))
        return sl

    @staticmethod
    def _caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{_FG2}; font-size:{fs(10)}; letter-spacing:1px; background:transparent;")
        return lbl

    def _emit(self, *_):
        self.params_changed.emit()

    # ── build ──────────────────────────────────────────────────────────────

    def _build_extras(self, layout, video: bool) -> None:
        self._x_sliders: list = []
        self._custom_matrix: Optional[list] = None
        self._layer_cache: dict[str, dict] = {}
        self._mask_path = ""

        # Layer B
        lg = self._group("Layer B")
        self.layer_cb = QCheckBox("ENABLE SECOND LAYER")
        self.layer_cb.setToolTip("Blend a second look (taken from a preset) into part of the image")
        self.layer_cb.toggled.connect(self._emit)
        lg.layout().addWidget(self.layer_cb)
        lg.layout().addWidget(self._caption("LOOK (PRESET)"))
        self.layer_preset_combo = QComboBox()
        self.layer_preset_combo.setMinimumHeight(26)
        self.refresh_layer_presets()
        self.layer_preset_combo.currentTextChanged.connect(self._emit)
        lg.layout().addWidget(self.layer_preset_combo)
        lg.layout().addWidget(self._caption("MASK"))
        self.mask_mode_combo = QComboBox()
        self.mask_mode_combo.setMinimumHeight(26)
        self.mask_mode_combo.addItems(MASK_MODES)
        self.mask_mode_combo.setToolTip("Where layer B shows: bright/dark areas, a split, the centre, or a mask image (white = layer B)")
        self.mask_mode_combo.currentTextChanged.connect(self._on_mask_mode)
        lg.layout().addWidget(self.mask_mode_combo)
        self.mask_pos_sl = self._x_slider(lg.layout(), "Position", 0, 100, 50, "{v}%",
                                          "Luminance threshold or split position")
        self.mask_feather_sl = self._x_slider(lg.layout(), "Feather", 0, 100, 10, "{v}%",
                                              "Softness of the transition")
        mrow = QHBoxLayout()
        self.mask_btn = QPushButton("▣  Load Mask…")
        self.mask_btn.setMinimumHeight(26)
        self.mask_btn.clicked.connect(self._load_mask)
        self.mask_lbl = self._caption("no mask")
        mrow.addWidget(self.mask_btn); mrow.addWidget(self.mask_lbl, 1)
        lg.layout().addLayout(mrow)
        layout.addWidget(lg)

        # FX
        fg = self._group("CRT / Glitch FX")
        fg.layout().addWidget(self._caption("CRT"))
        self.fx_sl = {}
        for key, label, tip in (
            ("scanlines", "Scanlines", "Dark horizontal lines"),
            ("chroma", "Chromatic", "RGB fringing towards the edges"),
            ("curvature", "Curvature", "Barrel distortion of a curved tube"),
            ("noise", "Noise", "Analog grain"),
            ("vignette", "Vignette", "Darker corners"),
        ):
            self.fx_sl[key] = self._x_slider(fg.layout(), label, 0, 100, 0, "{v}%", tip)
        fg.layout().addWidget(self._caption("GLITCH"))
        for key, label, tip in (
            ("rgb_split", "RGB Split", "Shift red and blue channels apart"),
            ("block_glitch", "Block Shift", "Displace random horizontal bands"),
            ("pixel_sort", "Pixel Sort", "Sort bright runs of pixels by luminance"),
        ):
            self.fx_sl[key] = self._x_slider(fg.layout(), label, 0, 100, 0, "{v}%", tip)
        frow = QHBoxLayout()
        self.fx_seed = 0
        reseed = QPushButton("⚄  Reseed")
        reseed.setMinimumHeight(26)
        reseed.setToolTip("New random glitch pattern")
        reseed.clicked.connect(self._reseed)
        clear = QPushButton("✕  Clear FX")
        clear.setMinimumHeight(26)
        clear.clicked.connect(self._clear_fx)
        frow.addWidget(reseed); frow.addWidget(clear)
        fg.layout().addLayout(frow)
        layout.addWidget(fg)

        # ASCII
        ag = self._group("ASCII")
        self.ascii_cb = QCheckBox("RENDER AS TEXT")
        self.ascii_cb.setToolTip("Replace the image by characters. Save as .txt to get the text itself")
        self.ascii_cb.toggled.connect(self._emit)
        ag.layout().addWidget(self.ascii_cb)
        self.ascii_cell_sl = self._x_slider(ag.layout(), "Cell Size", 4, 32, 8, "{v}px",
                                            "Character width in pixels (height is double)")
        self.ascii_charset = QComboBox(); self.ascii_charset.addItems(list(CHARSETS))
        self.ascii_colour = QComboBox(); self.ascii_colour.addItems(ASCII_COLOR_MODES)
        for c in (self.ascii_charset, self.ascii_colour):
            c.setMinimumHeight(26)
            c.currentTextChanged.connect(self._emit)
            ag.layout().addWidget(c)
        self.ascii_invert = QCheckBox("INVERT")
        self.ascii_invert.toggled.connect(self._emit)
        ag.layout().addWidget(self.ascii_invert)
        layout.addWidget(ag)

        # Animation (video only)
        self.anim_cb = None
        if video:
            vg = self._group("Animate")
            self.anim_cb = QCheckBox("ANIMATE OVER THE CLIP")
            self.anim_cb.setToolTip("Interpolate one setting from its current value to the end value across the video")
            self.anim_cb.toggled.connect(self._emit)
            vg.layout().addWidget(self.anim_cb)
            self.anim_param = QComboBox(); self.anim_param.addItems(list(ANIMATABLE))
            self.anim_curve = QComboBox(); self.anim_curve.addItems(ANIM_CURVES)
            self.anim_curve.setToolTip("Linear: start → end · Ping-Pong: start → end → start · Sine Loop: smooth loop")
            for c in (self.anim_param, self.anim_curve):
                c.setMinimumHeight(26)
                c.currentTextChanged.connect(self._emit)
            vg.layout().addWidget(self._caption("PARAMETER"))
            vg.layout().addWidget(self.anim_param)
            row = QHBoxLayout()
            row.addWidget(self._caption("END VALUE"))
            self.anim_end = QSpinBox(); self.anim_end.setRange(-1000, 1000); self.anim_end.setValue(255)
            self.anim_end.setToolTip("Value reached at the end (same units as the slider)")
            self.anim_end.valueChanged.connect(self._emit)
            row.addWidget(self.anim_end, 1)
            vg.layout().addLayout(row)
            vg.layout().addWidget(self.anim_curve)
            layout.addWidget(vg)

        self._on_mask_mode(self.mask_mode_combo.currentText(), emit=False)

        # settings history
        self._hist: list[dict] = []
        self._redo: list[dict] = []
        self._hist_timer = QTimer(self, singleShot=True, interval=350)
        self._hist_timer.timeout.connect(self._snapshot)
        self.params_changed.connect(self._hist_timer.start)

    # ── layer ──────────────────────────────────────────────────────────────

    def refresh_layer_presets(self) -> None:
        cur = self.layer_preset_combo.currentText()
        self.layer_preset_combo.blockSignals(True)
        self.layer_preset_combo.clear()
        self.layer_preset_combo.addItems(list_presets())
        if cur:
            self.layer_preset_combo.setCurrentText(cur)
        self.layer_preset_combo.blockSignals(False)
        self._layer_cache.clear()

    def _on_mask_mode(self, mode: str, emit: bool = True) -> None:
        is_img = mode == "Mask image"
        self.mask_btn.setVisible(is_img)
        self.mask_lbl.setVisible(is_img)
        self.mask_pos_sl.setEnabled(not is_img)
        if emit:
            self.params_changed.emit()

    def _load_mask(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Mask image (white = layer B)", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self._set_mask_path(path)
            self.params_changed.emit()

    def _set_mask_path(self, path: str) -> None:
        self._mask_path = path or ""
        from pathlib import Path
        self.mask_lbl.setText(Path(path).name if path else "no mask")

    def _layer_params(self, name: str) -> Optional[dict]:
        if not name:
            return None
        if name not in self._layer_cache:
            p = load_preset(name) or {}
            self._layer_cache[name] = {k: v for k, v in p.items() if k not in _LAYER_SKIP_KEYS}
        return self._layer_cache[name]

    # ── fx ─────────────────────────────────────────────────────────────────

    def _reseed(self) -> None:
        self.fx_seed = random.randint(1, 1_000_000)
        self.params_changed.emit()

    def _clear_fx(self) -> None:
        for sl in self.fx_sl.values():
            sl.blockSignals(True); sl.setValue(0); sl.blockSignals(False)
        self._refresh_extra_labels()
        self.params_changed.emit()

    # ── matrix ─────────────────────────────────────────────────────────────

    def edit_matrix(self) -> None:
        from .ui_dialogs import MatrixDialog
        dlg = MatrixDialog(self._custom_matrix, self)
        if dlg.exec():
            self._custom_matrix = dlg.matrix()
            self.method_picker.set_method("Custom Matrix")
            self._update_matrix_btn("Custom Matrix")
            self.params_changed.emit()

    def _update_matrix_btn(self, method: str) -> None:
        if hasattr(self, "matrix_btn"):
            self.matrix_btn.setVisible(method == "Custom Matrix")

    # ── params ─────────────────────────────────────────────────────────────

    def _extras_params(self) -> dict:
        name = self.layer_preset_combo.currentText()
        d = {
            "custom_matrix": self._custom_matrix,
            "layer": {
                "enabled": self.layer_cb.isChecked() and bool(name),
                "preset": name,
                "mask_mode": self.mask_mode_combo.currentText(),
                "mask_pos": self.mask_pos_sl.value(),
                "feather": self.mask_feather_sl.value(),
                "mask_path": self._mask_path,
                "params": self._layer_params(name) if self.layer_cb.isChecked() else None,
            },
            "fx": {**{k: sl.value() for k, sl in self.fx_sl.items()}, "seed": self.fx_seed},
            "ascii": {
                "enabled": self.ascii_cb.isChecked(),
                "cell": self.ascii_cell_sl.value(),
                "charset": self.ascii_charset.currentText(),
                "color_mode": self.ascii_colour.currentText(),
                "invert": self.ascii_invert.isChecked(),
            },
        }
        if self.anim_cb is not None:
            d["animate"] = {
                "enabled": self.anim_cb.isChecked(),
                "param": self.anim_param.currentText(),
                "end": self.anim_end.value(),
                "curve": self.anim_curve.currentText(),
            }
        return d

    def _extra_widgets(self) -> list:
        w = [self.layer_cb, self.layer_preset_combo, self.mask_mode_combo,
             self.ascii_cb, self.ascii_charset, self.ascii_colour, self.ascii_invert]
        w += [s for s, *_ in self._x_sliders]
        if self.anim_cb is not None:
            w += [self.anim_cb, self.anim_param, self.anim_curve, self.anim_end]
        return w

    def _set_extras(self, p: dict) -> None:
        ws = self._extra_widgets()
        for w in ws:
            w.blockSignals(True)
        try:
            self._custom_matrix = p.get("custom_matrix")
            lay = p.get("layer") or {}
            self.layer_cb.setChecked(bool(lay.get("enabled")))
            if lay.get("preset"):
                self.layer_preset_combo.setCurrentText(lay["preset"])
            self.mask_mode_combo.setCurrentText(lay.get("mask_mode", MASK_MODES[0]))
            self.mask_pos_sl.setValue(int(lay.get("mask_pos", 50)))
            self.mask_feather_sl.setValue(int(lay.get("feather", 10)))
            self._set_mask_path(lay.get("mask_path", ""))
            fx = {**FX_DEFAULTS, **(p.get("fx") or {})}
            for k, sl in self.fx_sl.items():
                sl.setValue(int(fx.get(k, 0)))
            self.fx_seed = int(fx.get("seed", 0))
            a = p.get("ascii") or {}
            self.ascii_cb.setChecked(bool(a.get("enabled")))
            self.ascii_cell_sl.setValue(int(a.get("cell", 8)))
            self.ascii_charset.setCurrentText(a.get("charset", "Standard"))
            self.ascii_colour.setCurrentText(a.get("color_mode", ASCII_COLOR_MODES[0]))
            self.ascii_invert.setChecked(bool(a.get("invert")))
            if self.anim_cb is not None:
                an = p.get("animate") or {}
                self.anim_cb.setChecked(bool(an.get("enabled")))
                self.anim_param.setCurrentText(an.get("param", "Threshold"))
                self.anim_end.setValue(int(an.get("end", 255)))
                self.anim_curve.setCurrentText(an.get("curve", "Linear"))
        finally:
            for w in ws:
                w.blockSignals(False)
        self._on_mask_mode(self.mask_mode_combo.currentText(), emit=False)
        self._update_matrix_btn(p.get("method", ""))
        self._refresh_extra_labels()

    def _reset_extras(self) -> None:
        self._set_extras({})

    def _refresh_extra_labels(self) -> None:
        for sl, vl, fmt, _ in self._x_sliders:
            vl.setText(fmt.format(v=sl.value()))

    # ── colour picking (window wires these to the active tab) ──────────────

    def _select_custom_palette(self) -> None:
        idx = self.palette_combo.findText("Custom")
        if idx < 0:
            self.palette_combo.addItem("Custom")
            idx = self.palette_combo.count() - 1
        self.palette_combo.blockSignals(True)
        self.palette_combo.setCurrentIndex(idx)
        self.palette_combo.blockSignals(False)
        self._refresh_palette_swatches()

    def apply_picked(self, target: str, rgb: tuple) -> None:
        if target == "palette":
            self._custom_palette.append(tuple(rgb))
            self._select_custom_palette()
        else:
            self.current_color = tuple(rgb)
            self._refresh_swatch()
        self.params_changed.emit()

    def set_custom_palette(self, colors: list) -> None:
        """Replace the custom palette (e.g. colours extracted from the image)."""
        self._custom_palette = [tuple(c) for c in colors]
        self._select_custom_palette()
        self.params_changed.emit()

    # ── settings history ───────────────────────────────────────────────────

    def _snapshot(self) -> None:
        s = self.get_params()
        if self._hist and self._hist[-1] == s:
            return
        self._hist.append(s)
        self._hist = self._hist[-_HISTORY_MAX:]
        if not getattr(self, "_restoring", False):
            self._redo.clear()

    def _restore(self, s: dict) -> None:
        self._restoring = True
        try:
            self.set_params(s)
        finally:
            self._hist_timer.stop()
            self._restoring = False

    def undo_settings(self) -> bool:
        self._hist_timer.stop()
        self._snapshot()
        if len(self._hist) < 2:
            return False
        self._redo.append(self._hist.pop())
        self._restore(self._hist[-1])
        return True

    def redo_settings(self) -> bool:
        if not self._redo:
            return False
        s = self._redo.pop()
        self._hist.append(s)
        self._restore(s)
        return True
