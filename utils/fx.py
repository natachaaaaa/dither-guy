"""Retro / CRT visual effects for the UI chrome.

- glow(widget)      : phosphor bloom around a widget (QGraphicsDropShadowEffect).
- GlowTitle         : logo label with chromatic aberration + flickering bloom.
- CRTOverlay        : scanlines, grain and vignette painted over the window,
                      with "clean" holes so the dithered image is never altered.
"""
from __future__ import annotations

import random
from typing import Callable, Iterable

import numpy as np
from PySide6.QtCore import Qt, QTimer, QRect, QRectF, QPoint, QEvent, QObject
from PySide6.QtGui import (
    QColor, QPainter, QPixmap, QImage, QRadialGradient, QBrush, QRegion, QFont,
    QFontMetrics,
)
from PySide6.QtWidgets import QWidget, QGraphicsDropShadowEffect, QLabel

from .theme import _G0, _MONO_FONT, _FONT_SCALE, _PIXEL_FONT


# ---------------------------------------------------------------------------
# Glow
# ---------------------------------------------------------------------------

def glow(widget: QWidget, color: str = _G0, radius: float = 14, alpha: int = 170) -> QGraphicsDropShadowEffect:
    """Attach a centred, coloured drop shadow that reads as a phosphor bloom."""
    c = QColor(color)
    c.setAlpha(alpha)
    eff = QGraphicsDropShadowEffect(widget)
    eff.setOffset(0, 0)
    eff.setBlurRadius(radius)
    eff.setColor(c)
    widget.setGraphicsEffect(eff)
    return eff


# ---------------------------------------------------------------------------
# Glowing logo with RGB split
# ---------------------------------------------------------------------------

class GlowTitle(QLabel):
    """Bold monospace text drawn with a red/cyan offset and a flickering bloom."""

    def __init__(self, text: str, color: str = _G0, size: int = 11, parent=None):
        super().__init__(text, parent)
        self._color = QColor(color)
        f = QFont()
        f.setFamilies([s.strip(" '") for s in _MONO_FONT.split(",")])
        f.setPointSizeF(size * _FONT_SCALE)
        f.setBold(not _PIXEL_FONT)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2.5)
        self.setFont(f)
        self.setStyleSheet("background: transparent;")
        fm = QFontMetrics(f)
        self.setMinimumWidth(fm.horizontalAdvance(text) + 24)
        self._fx = glow(self, color, radius=18, alpha=200)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flicker)
        self._timer.start(90)

    def set_flicker(self, on: bool) -> None:
        if on:
            self._timer.start(90)
        else:
            self._timer.stop()
            self._fx.setBlurRadius(18)

    def _flicker(self) -> None:
        # Mostly steady, with an occasional brief dip like a tired tube.
        r = random.random()
        self._fx.setBlurRadius(8 if r < 0.04 else 16 + random.random() * 4)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self.font())
        rect = self.rect()
        flags = int(self.alignment()) or int(Qt.AlignCenter)
        for dx, col in ((-1, QColor(255, 60, 170, 120)), (1, QColor(60, 220, 255, 110))):
            p.setPen(col)
            p.drawText(rect.translated(dx, 0), flags, self.text())
        p.setPen(self._color)
        p.drawText(rect, flags, self.text())
        p.end()


# ---------------------------------------------------------------------------
# CRT overlay
# ---------------------------------------------------------------------------

def _make_grain(size: int = 160, alpha: int = 22) -> QPixmap:
    rng = np.random.default_rng()
    v = rng.integers(0, 256, (size, size), dtype=np.uint8)
    a = (rng.random((size, size)) * alpha).astype(np.uint8)
    arr = np.dstack([v, v, v, a])  # RGBA
    img = QImage(arr.tobytes(), size, size, size * 4, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(img)


def _make_scanlines(period: int = 3, alpha: int = 75) -> QPixmap:
    pm = QPixmap(8, period)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.fillRect(0, period - 1, 8, 1, QColor(0, 0, 0, alpha))
    p.end()
    return pm


class CRTOverlay(QWidget):
    """Transparent, click-through layer on top of the main window.

    `clean_widgets` returns the widgets whose area must stay untouched
    (the image / video canvas), so the preview stays faithful to the output.
    """

    def __init__(self, host: QWidget, clean_widgets: Callable[[], Iterable[QWidget]]):
        super().__init__(host)
        self.setObjectName("crtOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self._clean = clean_widgets
        self._scan = _make_scanlines()
        self._grain = _make_grain()
        self._enabled = True
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.raise_()

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        self.setVisible(on)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded):
            self.setGeometry(self.parentWidget().rect())
            self.raise_()
        return False

    def _clean_region(self) -> QRegion:
        reg = QRegion()
        for w in self._clean():
            if w is None or not w.isVisible():
                continue
            tl = w.mapTo(self.parentWidget(), QPoint(0, 0))
            reg = reg.united(QRect(tl, w.size()))
        return reg

    def paintEvent(self, event) -> None:
        if not self._enabled:
            return
        dirty = QRegion(event.region())
        draw = dirty.subtracted(self._clean_region())
        if draw.isEmpty():
            return
        p = QPainter(self)
        p.setClipRegion(draw)
        r = self.rect()
        p.drawTiledPixmap(r, self._scan)
        p.drawTiledPixmap(r, self._grain)

        # Vignette: dark, slightly green-tinted corners.
        g = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.75)
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(0.65, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(8, 0, 14, 125))
        p.fillRect(r, QBrush(g))
        p.end()


# ---------------------------------------------------------------------------
# Canvas backdrop: faint dot grid behind the image
# ---------------------------------------------------------------------------

def paint_dot_grid(p: QPainter, rect: QRect, color: str, step: int = 12) -> None:
    c = QColor(color)
    p.setPen(c)
    for y in range(rect.top() + step // 2, rect.bottom(), step):
        for x in range(rect.left() + step // 2, rect.right(), step):
            p.drawPoint(x, y)
