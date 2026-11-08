from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import (
    QPixmap, QImage, QColor, QPainter, QLinearGradient, QBrush, QWheelEvent, QPen, QFont,
)
from PySide6.QtWidgets import (
    QLabel, QFrame, QSizePolicy, QWidget, QHBoxLayout, QSlider,
)

from .theme import _P0, _P2, _P4, _P5, _P6, _FG, _FG2, _FG3, _G0, _G3, _MONO_FONT, fs, _FW
from .fx import glow


# ---------------------------------------------------------------------------
# PIL → QPixmap
# ---------------------------------------------------------------------------

def pil_to_pixmap(img: Image.Image) -> QPixmap:
    """Convert a PIL RGB image to QPixmap without holding a ref to raw bytes."""
    raw = img.tobytes("raw", "RGB")
    qimg = QImage(raw, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


# ---------------------------------------------------------------------------
# Separator helpers
# ---------------------------------------------------------------------------

def _sep(shape: QFrame.Shape) -> QFrame:
    f = QFrame()
    f.setFrameShape(shape)
    f.setFrameShadow(QFrame.Sunken)
    if shape == QFrame.VLine:
        f.setFixedWidth(1)
    return f

def hsep() -> QFrame:
    return _sep(QFrame.HLine)

def vsep() -> QFrame:
    return _sep(QFrame.VLine)


# ---------------------------------------------------------------------------
# Histogram widget
# ---------------------------------------------------------------------------

class HistogramWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self._data: Optional[np.ndarray] = None
        self.setStyleSheet(
            f"background:{_P0}; border-top:1px solid {_P6}; border-radius:0px;"
        )
        self.setToolTip("Luminance histogram of processed output")

    def update_data(self, img: Image.Image) -> None:
        arr = np.array(img.convert("L"), dtype=np.uint8)
        hist, _ = np.histogram(arr, bins=64, range=(0, 256))
        self._data = hist.astype(np.float32)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._data is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mx = max(float(self._data.max()), 1.0)
        bw = w / len(self._data)
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, QColor(_G3))
        grad.setColorAt(1.0, QColor(_G0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        for i, v in enumerate(self._data):
            bh = int((v / mx) * (h - 4))
            painter.drawRect(int(i * bw), h - bh, max(1, int(bw) - 1), bh)
        # Horizontal scan gaps give the bars an LED-segment look.
        painter.setBrush(QColor(_P0))
        for y in range(h - 3, 0, -3):
            painter.drawRect(0, y, w, 1)
        painter.end()


# ---------------------------------------------------------------------------
# Zoomable canvas
# ---------------------------------------------------------------------------

_ZOOM_IN_FACTOR  = 1.25
_ZOOM_OUT_FACTOR = 0.80
_ZOOM_MIN        = 0.10
_ZOOM_MAX        = 8.00


class ZoomableLabel(QLabel):
    """Image canvas with zoom, a before/after split view and an eyedropper.

    - set_compare(pixmap): the "before" image; enable with set_compare_enabled.
      Drag anywhere on the image to move the split line.
    - start_pick(): next click emits picked(fx, fy) in 0..1 image coordinates.
    """
    picked = Signal(float, float)

    def __init__(self, placeholder: str = ""):
        super().__init__(placeholder)
        self.zoom_level: float = 0
        self.original_pixmap: Optional[QPixmap] = None
        self._compare_pm: Optional[QPixmap] = None
        self._compare_on = False
        self._split = 0.5
        self._picking = False
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(360, 260)
        self.setScaledContents(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(
            f"font-family:{_MONO_FONT}; font-size:{fs(13)};"
            f"color:{_FG3}; background:transparent;"
        )
        self._grid = self._make_grid_tile()

    @staticmethod
    def _make_grid_tile(step: int = 12) -> QPixmap:
        pm = QPixmap(step, step)
        pm.fill(QColor(_P0))
        p = QPainter(pm)
        p.setPen(QColor(_P5))
        p.drawPoint(step // 2, step // 2)
        p.end()
        return pm

    def paintEvent(self, event) -> None:
        # Backdrop (dot grid) first, then QLabel draws text / pixmap on top.
        p = QPainter(self)
        p.drawTiledPixmap(self.rect(), self._grid)
        p.end()
        super().paintEvent(event)
        r = self._image_rect()
        if self._compare_on and self._compare_pm is not None and r is not None:
            sx = r.left() + int(r.width() * self._split)
            p = QPainter(self)
            p.setClipRect(QRect(r.left(), r.top(), sx - r.left(), r.height()))
            p.drawPixmap(r, self._compare_pm)
            p.setClipping(False)
            p.setPen(QPen(QColor(_G0), 2))
            p.drawLine(sx, r.top(), sx, r.bottom())
            p.setBrush(QColor(_G0))
            p.drawRect(sx - 4, r.center().y() - 12, 8, 24)
            f = QFont(); f.setFamilies([s.strip(" '") for s in _MONO_FONT.split(",")]); f.setPixelSize(13)
            p.setFont(f)
            for txt, x, align in (("BEFORE", sx - 8, Qt.AlignRight), ("AFTER", sx + 8, Qt.AlignLeft)):
                box = QRect(x - 80 if align == Qt.AlignRight else x, r.top() + 6, 80, 18)
                p.setPen(QColor(0, 0, 0)); p.drawText(box.translated(1, 1), align | Qt.AlignVCenter, txt)
                p.setPen(QColor(_G0)); p.drawText(box, align | Qt.AlignVCenter, txt)
            p.end()

    # ── before / after + eyedropper ──────────────────────────────────

    def _image_rect(self) -> Optional[QRect]:
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return None
        x = (self.width() - pm.width()) // 2
        y = (self.height() - pm.height()) // 2
        return QRect(max(0, x), max(0, y), pm.width(), pm.height())

    def set_compare(self, pixmap: Optional[QPixmap]) -> None:
        self._compare_pm = pixmap
        self.update()

    def set_compare_enabled(self, on: bool) -> None:
        self._compare_on = on
        self._update_cursor()
        self.update()

    def start_pick(self) -> None:
        self._picking = True
        self._update_cursor()

    def cancel_pick(self) -> None:
        self._picking = False
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._picking:
            self.setCursor(Qt.CrossCursor)
        elif self._compare_on:
            self.setCursor(Qt.SplitHCursor)
        else:
            self.unsetCursor()

    def _move_split(self, pos: QPoint) -> None:
        r = self._image_rect()
        if r is not None and r.width() > 0:
            self._split = min(1.0, max(0.0, (pos.x() - r.left()) / r.width()))
            self.update()

    def mousePressEvent(self, event) -> None:
        r = self._image_rect()
        if self._picking and event.button() == Qt.LeftButton:
            self._picking = False
            self._update_cursor()
            if r is not None and r.contains(event.position().toPoint()):
                pt = event.position().toPoint()
                self.picked.emit((pt.x() - r.left()) / max(1, r.width()),
                                 (pt.y() - r.top()) / max(1, r.height()))
            event.accept()
            return
        if self._compare_on and event.button() == Qt.LeftButton:
            self._move_split(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._compare_on and event.buttons() & Qt.LeftButton:
            self._move_split(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    # public API

    def set_image(self, pixmap: QPixmap) -> None:
        self.original_pixmap = pixmap
        self._redraw()

    def zoom_in(self)  -> None: self._apply_zoom(self.zoom_level or 1.0, _ZOOM_IN_FACTOR)
    def zoom_out(self) -> None: self._apply_zoom(self.zoom_level or 1.0, _ZOOM_OUT_FACTOR)
    def fit(self)      -> None: self.zoom_level = 0;   self._redraw()
    def actual(self)   -> None: self.zoom_level = 1.0; self._redraw()

    # internals

    def _apply_zoom(self, base: float, factor: float) -> None:
        self.zoom_level = max(_ZOOM_MIN, min(_ZOOM_MAX, base * factor))
        self._redraw()

    def _redraw(self) -> None:
        if not self.original_pixmap:
            return
        if self.zoom_level == 0:
            scaled = self.original_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            w = int(self.original_pixmap.width()  * self.zoom_level)
            h = int(self.original_pixmap.height() * self.zoom_level)
            mode = Qt.SmoothTransformation if self.zoom_level < 2 else Qt.FastTransformation
            scaled = self.original_pixmap.scaled(w, h, Qt.KeepAspectRatio, mode)
        self.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.zoom_level == 0 and self.original_pixmap:
            self._redraw()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)


# ---------------------------------------------------------------------------
# Resettable slider
# Double-click resets to default value.
# Scroll-wheel only changes value when _scroll_enabled is True.
# ---------------------------------------------------------------------------

class ResettableSlider(QSlider):
    """QSlider with double-click-to-reset and opt-in scroll-wheel."""

    # Class-level flag shared across all instances; toggled by ControlPanel.
    _scroll_enabled: bool = False

    def __init__(self, orientation, default: int, parent=None):
        super().__init__(orientation, parent)
        self._default = default

    def mouseDoubleClickEvent(self, event) -> None:
        self.setValue(self._default)
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if ResettableSlider._scroll_enabled:
            super().wheelEvent(event)
        else:
            event.ignore()  # pass up to ScrollArea so panel still scrolls


# ---------------------------------------------------------------------------
# Compact slider factory
# ---------------------------------------------------------------------------

def make_slider(
    parent_layout,
    label_base: str,
    mn: int,
    mx: int,
    val: int,
    fmt: str = "{v}",
    tooltip: str = "",
):
    """
    Add a labelled slider row to *parent_layout*.
    Returns (label_widget, value_label_widget, slider_widget).
    """
    row = QWidget()
    rl  = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(4)

    lbl = QLabel(label_base.upper())
    lbl.setStyleSheet(
        f"color:{_FG2}; font-size:{fs(10)}; font-family:{_MONO_FONT}; letter-spacing:1px;"
    )
    lbl.setMinimumWidth(72)
    lbl.setMaximumWidth(100)
    if tooltip:
        lbl.setToolTip(tooltip)

    val_lbl = QLabel(fmt.format(v=val))
    val_lbl.setStyleSheet(
        f"color:{_G0}; font-size:{fs(11)}; font-family:{_MONO_FONT};"
        f"font-weight:{_FW}; min-width:32px; background:transparent;"
    )
    val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    glow(val_lbl, radius=10, alpha=150)

    rl.addWidget(lbl)
    rl.addStretch()
    rl.addWidget(val_lbl)
    parent_layout.addWidget(row)

    sl = ResettableSlider(Qt.Horizontal, default=val)
    sl.setMinimum(mn)
    sl.setMaximum(mx)
    sl.setValue(val)
    sl.setFixedHeight(20)
    if tooltip:
        sl.setToolTip(f"{tooltip}  ·  double-click to reset")
    parent_layout.addWidget(sl)

    return lbl, val_lbl, sl
