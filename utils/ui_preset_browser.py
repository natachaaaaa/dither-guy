"""Preset browser: categories, search, favourites, recents and live thumbnails.

Thumbnails are rendered in a background thread with the real pipeline, on the
image currently loaded (or a built-in sample), so you see what each preset
does to *your* picture.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QIcon, QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QLineEdit,
    QPushButton, QLabel, QListView, QAbstractItemView,
)

from .presets import (
    list_presets, load_preset, preset_categories, favorite_presets, recent_presets,
    toggle_favorite,
)
from .theme import _G0, _FG2, _P0, _P5, fs

THUMB_W, THUMB_H = 150, 104
ALL, FAVS, RECENT = "All", "★ Favourites", "◷ Recent"


def sample_image(w: int = 300, h: int = 208) -> Image.Image:
    """Colourful test card: hue sweep, luminance ramp, a ring and a dark block."""
    x = np.linspace(0, 1, w)[None, :]
    y = np.linspace(0, 1, h)[:, None]
    hsv = np.zeros((h, w, 3), np.float32)
    hsv[..., 0] = x * 255
    hsv[..., 1] = 190
    hsv[..., 2] = (1 - y * 0.85) * 255
    img = Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB")
    d = ImageDraw.Draw(img)
    d.ellipse((28, 36, 128, 136), fill=(250, 250, 250))
    d.ellipse((58, 66, 98, 106), fill=(10, 10, 10))
    d.rectangle((180, 110, 280, 190), fill=(20, 20, 30))
    return img


def _to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGB")
    raw = img.tobytes("raw", "RGB")
    return QImage(raw, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()


class ThumbWorker(QThread):
    thumb_ready = Signal(str, QImage)

    def __init__(self, names: list[str], src: Image.Image):
        super().__init__()
        self._names = names
        self._src = src
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from .pipeline import render
        for name in self._names:
            if self._stop:
                return
            p = load_preset(name)
            if not p:
                continue
            try:
                p = dict(p)
                p.pop("layer", None)          # keep thumbnails fast
                out = render(self._src, p).resize((THUMB_W, THUMB_H), Image.NEAREST)
                self.thumb_ready.emit(name, _to_qimage(out))
            except Exception:
                continue


class PresetBrowser(QDialog):
    preset_chosen = Signal(str)

    _cache: dict[tuple, QPixmap] = {}   # (source id, name) -> pixmap, shared across openings

    def __init__(self, source: Optional[Image.Image] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preset Browser")
        self.resize(900, 600)
        if source is not None:
            src = source.convert("RGB").copy()
            src.thumbnail((THUMB_W * 2, THUMB_H * 2))
            self._src_key = id(source)
        else:
            src = sample_image()
            self._src_key = "sample"
        self._src = src
        self._worker: Optional[ThumbWorker] = None

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.cat_list = QListWidget()
        self.cat_list.setFixedWidth(170)
        self.cat_list.currentTextChanged.connect(self._fill)
        left.addWidget(self.cat_list)
        root.addLayout(left)

        right = QVBoxLayout()
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("search presets…")
        self.search.textChanged.connect(lambda _: self._fill(self.cat_list.currentItem().text()
                                                             if self.cat_list.currentItem() else ALL))
        top.addWidget(self.search, 1)
        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{_FG2}; font-size:{fs(10)};")
        top.addWidget(self.info)
        right.addLayout(top)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(THUMB_W, THUMB_H))
        self.grid.setGridSize(QSize(THUMB_W + 18, THUMB_H + 34))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setStyleSheet(
            f"QListWidget {{ background:{_P0}; border:1px solid {_P5}; }}"
            f"QListWidget::item {{ color:{_FG2}; padding:4px; }}"
            f"QListWidget::item:selected {{ background:transparent; color:{_G0}; border:1px solid {_G0}; }}"
        )
        self.grid.itemDoubleClicked.connect(lambda it: self._apply(it))
        self.grid.currentItemChanged.connect(lambda *_: self._update_buttons())
        right.addWidget(self.grid, 1)

        bottom = QHBoxLayout()
        self.fav_btn = QPushButton("☆  Favourite")
        self.fav_btn.clicked.connect(self._toggle_fav)
        hint = QLabel("double-click to apply")
        hint.setStyleSheet(f"color:{_FG2};")
        apply_btn = QPushButton("APPLY")
        apply_btn.setObjectName("accent")
        apply_btn.clicked.connect(lambda: self._apply(self.grid.currentItem()))
        close_btn = QPushButton("CLOSE")
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(self.fav_btn)
        bottom.addWidget(hint)
        bottom.addStretch()
        bottom.addWidget(close_btn)
        bottom.addWidget(apply_btn)
        right.addLayout(bottom)
        root.addLayout(right, 1)

        self._cats = preset_categories()
        self.cat_list.addItems([ALL, FAVS, RECENT] + list(self._cats))
        self.cat_list.setCurrentRow(0)
        self._start_thumbs()

    # ── content ─────────────────────────────────────────────────────────────

    def _names_for(self, cat: str) -> list[str]:
        if cat == FAVS:
            return favorite_presets()
        if cat == RECENT:
            return recent_presets()
        if cat == ALL:
            return list_presets()
        return self._cats.get(cat, [])

    def _placeholder(self) -> QPixmap:
        pm = QPixmap(THUMB_W, THUMB_H)
        pm.fill(QColor(_P5))
        return pm

    def _fill(self, cat: str) -> None:
        q = self.search.text().strip().lower()
        names = [n for n in self._names_for(cat or ALL) if q in n.lower()]
        favs = set(favorite_presets())
        self.grid.clear()
        for n in names:
            pm = self._cache.get((self._src_key, n)) or self._placeholder()
            it = QListWidgetItem(QIcon(pm), ("★ " if n in favs else "") + n)
            it.setData(Qt.UserRole, n)
            self.grid.addItem(it)
        self.info.setText(f"{len(names)} presets")
        self._update_buttons()

    def _start_thumbs(self) -> None:
        todo = [n for n in list_presets() if (self._src_key, n) not in self._cache]
        if not todo:
            return
        self._worker = ThumbWorker(todo, self._src)
        self._worker.thumb_ready.connect(self._on_thumb)
        self._worker.start()

    def _on_thumb(self, name: str, qimg: QImage) -> None:
        pm = QPixmap.fromImage(qimg)
        self._cache[(self._src_key, name)] = pm
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            if it.data(Qt.UserRole) == name:
                it.setIcon(QIcon(pm))
                break

    # ── actions ─────────────────────────────────────────────────────────────

    def _update_buttons(self) -> None:
        it = self.grid.currentItem()
        on = it is not None and it.data(Qt.UserRole) in favorite_presets()
        self.fav_btn.setText("★  Unfavourite" if on else "☆  Favourite")
        self.fav_btn.setEnabled(it is not None)

    def _toggle_fav(self) -> None:
        it = self.grid.currentItem()
        if it is None:
            return
        name = it.data(Qt.UserRole)
        on = toggle_favorite(name)
        it.setText(("★ " if on else "") + name)
        self._update_buttons()

    def _apply(self, it: Optional[QListWidgetItem]) -> None:
        if it is not None:
            self.preset_chosen.emit(it.data(Qt.UserRole))

    def done(self, r: int) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(3000)
        super().done(r)
