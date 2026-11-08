from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QSpinBox, QWidget,
    QLineEdit, QFileDialog, QProgressBar, QMessageBox, QApplication,
)

from .batch import batch_process, _BATCH_IMAGE_EXTS
from .constants import _VIDEO_WORKERS
from .theme import _G0, _FG2, _P2, _MONO_FONT, fs
from .ui_widgets import hsep


# ---------------------------------------------------------------------------
# Crop dialog
# ---------------------------------------------------------------------------

class CropDialog(QDialog):
    """Let the user trim N pixels from each edge of an image."""

    _EDGES = ("left", "top", "right", "bottom")

    def __init__(self, img_w: int, img_h: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crop Image")
        self.setMinimumWidth(320)
        self.img_w = img_w
        self.img_h = img_h
        self._spins: dict[str, QSpinBox] = {}
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Remove pixels from each edge")
        title.setStyleSheet(f"font-family:{_MONO_FONT}; font-size:{fs(13)}; color:{_G0};")
        layout.addWidget(title)
        layout.addWidget(hsep())

        self._info = QLabel()
        self._info.setAlignment(Qt.AlignCenter)
        self._info.setStyleSheet(
            f"font-family:{_MONO_FONT}; font-size:{fs(11)}; color:{_G0};"
            f"padding:6px; background:{_P2}; border-radius:3px;"
        )
        layout.addWidget(self._info)

        # Spin-box form
        maxima = {
            "left":   self.img_w - 1,
            "top":    self.img_h - 1,
            "right":  self.img_w - 1,
            "bottom": self.img_h - 1,
        }
        form = QWidget()
        fl   = QGridLayout(form)
        fl.setSpacing(8)
        for row, name in enumerate(self._EDGES):
            lbl = QLabel(name.capitalize())
            lbl.setStyleSheet(f"color:{_FG2};")
            sp  = QSpinBox()
            sp.setMinimum(0)
            sp.setMaximum(max(maxima[name], 1))
            sp.setValue(0)
            sp.setSuffix(" px")
            sp.setMinimumHeight(28)
            sp.valueChanged.connect(self._update_info)
            fl.addWidget(lbl, row, 0)
            fl.addWidget(sp,  row, 1)
            self._spins[name] = sp

        layout.addWidget(form)
        layout.addWidget(hsep())

        btns = QHBoxLayout()
        ok   = QPushButton("Apply Crop")
        can  = QPushButton("Cancel")
        ok.setObjectName("accent")
        ok.setMinimumHeight(30)
        can.setMinimumHeight(30)
        ok.clicked.connect(self.accept)
        can.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(can)
        btns.addWidget(ok)
        layout.addLayout(btns)

        self._update_info()

    def _update_info(self) -> None:
        l = self._spins["left"].value()
        t = self._spins["top"].value()
        r = self._spins["right"].value()
        b = self._spins["bottom"].value()
        nw = max(1, self.img_w - l - r)
        nh = max(1, self.img_h - t - b)
        self._info.setText(f"{self.img_w}×{self.img_h} ──▶ {nw}×{nh}")

    def values(self) -> dict[str, int]:
        return {k: sp.value() for k, sp in self._spins.items()}


from PySide6.QtCore import QThread, Signal

class BatchWorker(QThread):
    progress = Signal(int, int, str)
    finished_batch = Signal(int, int)

    def __init__(self, in_dir, out_dir, params, cancel_list):
        super().__init__()
        self.in_dir = in_dir
        self.out_dir = out_dir
        self.params = params
        self.cancel_list = cancel_list

    def run(self):
        ok, err = batch_process(
            self.in_dir, self.out_dir, self.params,
            progress_cb=lambda d, t, n: self.progress.emit(d, t, n),
            cancel_flag=self.cancel_list,
        )
        self.finished_batch.emit(ok, err)

# ---------------------------------------------------------------------------
# Batch dialog
# ---------------------------------------------------------------------------

class BatchDialog(QDialog):
    """Apply current dither settings to every image in a folder."""

    def __init__(self, get_params, parent=None):
        super().__init__(parent)
        self.get_params = get_params
        self.setWindowTitle("Batch Process")
        self.setMinimumWidth(460)
        self._cancel = [False]
        self.worker = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Batch Dither — apply current settings to a folder")
        title.setStyleSheet(f"font-family:{_MONO_FONT}; font-size:{fs(12)}; color:{_G0};")
        layout.addWidget(title)
        layout.addWidget(hsep())

        for attr, placeholder, caption in (
            ("in_edit",  "Input folder…",  "Input :"),
            ("out_edit", "Output folder…", "Output:"),
        ):
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setMinimumHeight(28)
            btn = QPushButton("Browse")
            btn.setMinimumHeight(28)
            btn.clicked.connect(lambda _=None, e=edit: self._browse(e))
            row.addWidget(QLabel(caption))
            row.addWidget(edit)
            row.addWidget(btn)
            layout.addLayout(row)
            setattr(self, attr, edit)

        self.info_lbl = QLabel("Waiting…")
        self.info_lbl.setStyleSheet(
            f"font-family:{_MONO_FONT}; font-size:{fs(10)}; color:{_FG2};"
            f"background:{_P2}; padding:6px; border-radius:3px;"
        )
        layout.addWidget(self.info_lbl)

        self.prog = QProgressBar()
        self.prog.setVisible(False)
        self.prog.setFixedHeight(6)
        self.prog.setTextVisible(False)
        layout.addWidget(self.prog)
        layout.addWidget(hsep())

        btns = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run Batch")
        self.run_btn.setObjectName("accent")
        self.run_btn.setMinimumHeight(32)
        self.run_btn.clicked.connect(self._run)

        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setMinimumHeight(32)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.cancel_btn.setVisible(False)

        close_btn = QPushButton("Close")
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(self.reject)

        btns.addWidget(self.run_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _browse(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Folder", str(Path.home()))
        if d:
            edit.setText(d)

    def _run(self) -> None:
        in_dir  = self.in_edit.text().strip()
        out_dir = self.out_edit.text().strip()

        if not in_dir or not out_dir:
            QMessageBox.warning(self, "Batch", "Please set both input and output folders.")
            return
        if not Path(in_dir).is_dir():
            QMessageBox.warning(self, "Batch", f"Input folder not found:\n{in_dir}")
            return

        files = [f for f in Path(in_dir).iterdir() if f.suffix.lower() in _BATCH_IMAGE_EXTS]
        if not files:
            QMessageBox.warning(self, "Batch", "No supported images found in input folder.")
            return

        self._cancel[0] = False
        params = self.get_params()
        self.prog.setMaximum(len(files))
        self.prog.setValue(0)
        self.prog.setVisible(True)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.info_lbl.setText(f"Processing {len(files)} images with {_VIDEO_WORKERS} workers…")

        self.worker = BatchWorker(in_dir, out_dir, params, self._cancel)
        import time
        self._batch_start_time = time.time()
        self.worker.progress.connect(self._progress)
        self.worker.finished_batch.connect(self._on_done)
        self.worker.start()

    def _progress(self, done: int, total: int, name: str) -> None:
        self.prog.setValue(done)
        import time
        elapsed = time.time() - getattr(self, '_batch_start_time', time.time())
        fps = done / elapsed if elapsed > 0 else 0
        if fps > 0:
            eta_sec = (total - done) / fps
            m, s = divmod(int(eta_sec), 60)
            h, m = divmod(m, 60)
            eta_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
        else:
            eta_str = "..."
        pct = int((done / total) * 100) if total > 0 else 0
        short = name[:20] + "..." if len(name) > 20 else name
        self.info_lbl.setText(f"Processing {pct}%  •  [{done}/{total}]  •  {fps:.1f} img/s  •  ETA {eta_str}  •  {short}")

    def _on_done(self, ok: int, err: int) -> None:
        self.prog.setVisible(False)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        status = "cancelled" if self._cancel[0] else "complete"
        self.info_lbl.setText(
            f"Batch {status} · {ok} saved · {err} error(s) → {self.out_edit.text().strip()}"
        )

    def _cancel_batch(self) -> None:
        self._cancel[0] = True
        self.info_lbl.setText("Cancelling…")

    def reject(self) -> None:
        self._cancel_batch()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(500)
        super().reject()


# ---------------------------------------------------------------------------
# Custom ordered-dither matrix editor
# ---------------------------------------------------------------------------

class MatrixDialog(QDialog):
    """Edit a threshold matrix as rows of numbers; any range works (ranked)."""

    def __init__(self, matrix=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QPlainTextEdit, QComboBox
        from .matrices import MATRIX_TEMPLATES
        self.setWindowTitle("Custom Matrix")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        title = QLabel("CUSTOM DITHER MATRIX")
        title.setStyleSheet(f"font-family:{_MONO_FONT}; font-size:{fs(13)}; color:{_G0};")
        lay.addWidget(title)
        hint = QLabel("One row per line, numbers separated by spaces (up to 32x32).\n"
                      "Lower numbers turn on first. Equal numbers turn on together.")
        hint.setStyleSheet(f"color:{_FG2};")
        lay.addWidget(hint)
        self._tpl = QComboBox()
        self._tpl.addItem("-- Templates --")
        self._tpl.addItems(list(MATRIX_TEMPLATES))
        self._tpl.currentTextChanged.connect(self._apply_template)
        lay.addWidget(self._tpl)
        self._edit = QPlainTextEdit()
        self._edit.setPlainText(self._fmt(matrix or MATRIX_TEMPLATES["Bayer 4x4"]))
        self._edit.textChanged.connect(self._update_preview)
        lay.addWidget(self._edit, 1)
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumHeight(70)
        lay.addWidget(self._preview)
        self._err = QLabel("")
        self._err.setStyleSheet("color:#ff3b5c;")
        lay.addWidget(self._err)
        row = QHBoxLayout()
        ok = QPushButton("APPLY"); ok.setObjectName("accent"); ok.clicked.connect(self._accept)
        cancel = QPushButton("CANCEL"); cancel.clicked.connect(self.reject)
        row.addStretch(); row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)
        self._update_preview()

    def _apply_template(self, name: str) -> None:
        from .matrices import MATRIX_TEMPLATES
        if name in MATRIX_TEMPLATES:
            self._edit.setPlainText(self._fmt(MATRIX_TEMPLATES[name]))

    @staticmethod
    def _fmt(m) -> str:
        return "\n".join(" ".join(str(int(v)) for v in r) for r in m)

    def matrix(self):
        rows = [r.split() for r in self._edit.toPlainText().strip().splitlines() if r.strip()]
        try:
            m = [[float(v) for v in r] for r in rows]
        except ValueError:
            raise ValueError("Only numbers are allowed.")
        if not m or any(len(r) != len(m[0]) for r in m) or len(m) > 32 or len(m[0]) > 32 \
                or len(m) * len(m[0]) < 2:
            raise ValueError("All rows need the same number of values (2 to 32x32 cells).")
        return m

    def _update_preview(self) -> None:
        import numpy as np
        from PIL import Image
        from .matrices import normalize_matrix, tile
        from .ui_widgets import pil_to_pixmap
        try:
            mat = normalize_matrix(self.matrix())
            self._err.setText("")
        except ValueError as exc:
            self._err.setText(str(exc))
            return
        w, h = 360, 60
        grad = np.tile(np.linspace(0, 255, w, dtype=np.float32), (h, 1))
        out = np.where(grad > tile(mat, h, w), 255, 0).astype(np.uint8)
        self._preview.setPixmap(pil_to_pixmap(Image.fromarray(out, "L").convert("RGB")))

    def _accept(self) -> None:
        try:
            self.matrix()
        except ValueError as exc:
            self._err.setText(str(exc))
            return
        self.accept()


# ---------------------------------------------------------------------------
# Image export options
# ---------------------------------------------------------------------------

class ExportDialog(QDialog):
    """Pick a format and an integer upscale before choosing the file."""

    def __init__(self, size: tuple[int, int], parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox
        from .export import EXPORT_FORMATS, SCALES
        self._size = size
        self.setWindowTitle("Export Image")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        title = QLabel("EXPORT")
        title.setStyleSheet(f"font-family:{_MONO_FONT}; font-size:{fs(13)}; color:{_G0};")
        lay.addWidget(title)
        self.fmt = QComboBox(); self.fmt.addItems(list(EXPORT_FORMATS))
        self.scale = QComboBox(); self.scale.addItems([f"×{s}" for s in SCALES])
        self.desc = QLabel(); self.desc.setStyleSheet(f"color:{_FG2};"); self.desc.setWordWrap(True)
        self.dims = QLabel(); self.dims.setStyleSheet(f"color:{_G0};")
        for lbl, w in (("FORMAT", self.fmt), ("SCALE (sharp pixels)", self.scale)):
            cap = QLabel(lbl); cap.setStyleSheet(f"color:{_FG2};")
            lay.addWidget(cap); lay.addWidget(w)
        lay.addWidget(self.desc); lay.addWidget(self.dims)
        self.fmt.currentTextChanged.connect(self._update)
        self.scale.currentTextChanged.connect(self._update)
        row = QHBoxLayout()
        ok = QPushButton("CHOOSE FILE…"); ok.setObjectName("accent"); ok.clicked.connect(self.accept)
        cancel = QPushButton("CANCEL"); cancel.clicked.connect(self.reject)
        row.addStretch(); row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)
        self._update()

    def format(self) -> str:
        return self.fmt.currentText()

    def scale_factor(self) -> int:
        return int(self.scale.currentText().lstrip("×"))

    def _update(self, *_):
        from .export import EXPORT_FORMATS
        f = self.format()
        self.desc.setText(EXPORT_FORMATS[f][1])
        no_scale = f == "TXT (ASCII)"
        self.scale.setEnabled(not no_scale)
        w, h = self._size
        s = 1 if no_scale else self.scale_factor()
        self.dims.setText("" if no_scale else f"→ {w * s} × {h * s} px")
