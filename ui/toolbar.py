from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction

if TYPE_CHECKING:
    from ui.window import DitherGuy

class WindowToolbar:
    def _build_toolbar(self: 'DitherGuy') -> None:
        # 1. Top Menu Bar (Nav Bar)
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("FILE")
        view_menu = menubar.addMenu("VIEW")
        edit_menu = menubar.addMenu("EDIT")
        self.presets_menu = menubar.addMenu("PRESETS")
        help_menu = menubar.addMenu("HELP")
        
        def create_action(label: str, shortcut: str, slot, tip: str = "") -> QAction:
            a = QAction(label, self)
            if shortcut:
                a.setShortcut(shortcut)
            if tip:
                a.setStatusTip(tip)
                a.setToolTip(tip)
            a.triggered.connect(slot)
            return a
            
        a_open  = create_action("Open", "Ctrl+O", self._open, "Open image")
        a_save  = create_action("Save", "Ctrl+S", self._save, "Save output")
        a_batch = create_action("Batch Process", "Ctrl+B", self._batch, "Batch process folder")
        file_menu.addAction(a_open)
        file_menu.addAction(a_save)
        file_menu.addSeparator()
        file_menu.addAction(a_batch)
        
        a_undo = create_action("Undo", "Ctrl+Z", lambda: self.image_tab.undo(), "Undo last image operation")
        a_reset = create_action("Reset Defaults", "Ctrl+D", self._reset_all, "Reset settings")
        a_rand = create_action("Randomize", "Ctrl+R", self._randomize, "Randomize properties")
        edit_menu.addAction(a_undo)
        edit_menu.addAction(create_action("Undo Settings", "Ctrl+Alt+Z", self._undo_settings,
                                          "Go back to the previous slider / option state"))
        edit_menu.addAction(create_action("Redo Settings", "Ctrl+Y", self._redo_settings,
                                          "Re-apply a settings change you undid"))
        edit_menu.addSeparator()
        edit_menu.addAction(a_reset)
        edit_menu.addAction(a_rand)
        
        a_zin  = create_action("Zoom In", "Ctrl+=", self._zoom_in, "Zoom in")
        a_zout = create_action("Zoom Out", "Ctrl+-", self._zoom_out, "Zoom out")
        a_fit  = create_action("Fit on Screen", "Ctrl+0", self._fit, "Fit to window")
        a_1to1 = create_action("100%", "Ctrl+1", self._actual, "Actual pixels")
        view_menu.addAction(a_zin)
        view_menu.addAction(a_zout)
        view_menu.addAction(a_fit)
        view_menu.addAction(a_1to1)
        view_menu.addAction(create_action(
            "Before / After", "Ctrl+K",
            lambda: self.image_tab.compare_cb.toggle(),
            "Split view: original on the left, result on the right"))

        view_menu.addSeparator()
        self.a_crt = QAction("CRT Effects", self)
        self.a_crt.setCheckable(True)
        self.a_crt.setChecked(self._crt_enabled())
        self.a_crt.setStatusTip("Scanlines, grain, vignette and glow flicker on the interface (never on the image)")
        self.a_crt.toggled.connect(self._set_crt_enabled)
        view_menu.addAction(self.a_crt)

        view_menu.addSeparator()
        self.a_force_orig = QAction("Force Original Video", self)
        self.a_force_orig.setCheckable(True)
        self.a_force_orig.setChecked(False)

        def _on_force_orig_toggled(checked: bool):
            self.video_tab.force_original = checked
            if getattr(self.video_tab, 'video_path', None):
                from PySide6.QtWidgets import QMessageBox
                if QMessageBox.question(self, "Reload Video", "Reload the video now to apply this change?") == QMessageBox.StandardButton.Yes:
                    self.video_tab._load_video(self.video_tab.video_path)
        
        self.a_force_orig.toggled.connect(_on_force_orig_toggled)
        self.a_force_orig.setStatusTip("Always load full resolution video instead of generating a 720p proxy")
        view_menu.addAction(self.a_force_orig)

        a_shortcuts = create_action("Keyboard Shortcuts", "Ctrl+?", self._show_shortcuts, "View all keyboard shortcuts")
        help_menu.addAction(a_shortcuts)

        a_about = create_action("About This Project", "", self._show_about, "About this application")
        help_menu.addAction(a_about)

        self._build_presets_menu()

        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt
        from utils.theme import _MONO_FONT, _G0, fs
        
        self.zoom_lbl = QLabel("fit")
        self.zoom_lbl.setMinimumWidth(52)
        self.zoom_lbl.setAlignment(Qt.AlignCenter)
        self.zoom_lbl.setStyleSheet(f"font-family:{_MONO_FONT}; color:{_G0}; font-size:{fs(11)}; padding:0 8px; background:transparent;")
        self.zoom_lbl.setToolTip("Current zoom level")
        from utils.fx import glow, GlowTitle
        glow(self.zoom_lbl, radius=10)

        from utils.constants import VERSION
        self.logo = GlowTitle(f"DITHER GUY  v{VERSION}")
        self.logo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.logo.setContentsMargins(0, 0, 10, 0)
        menubar.setCornerWidget(self.logo, Qt.TopRightCorner)
        self.statusBar().addPermanentWidget(self.zoom_lbl)

    def _build_presets_menu(self: 'DitherGuy') -> None:
        from utils.presets import preset_categories, favorite_presets, recent_presets

        self.presets_menu.clear()

        def add(menu, label, slot, shortcut=""):
            a = QAction(label, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        add(self.presets_menu, "Browse Presets…", self._browse_presets, "Ctrl+P")
        add(self.presets_menu, "Save Preset", self._save_preset)
        add(self.presets_menu, "Toggle Favourite (last loaded)", self._toggle_last_favorite)
        add(self.presets_menu, "Manage Presets", self._manage_presets)
        add(self.presets_menu, "Download Presets from GitHub", self._download_presets)

        def load_slot(name):
            return lambda checked=False, n=name: self._load_preset(n)

        self.presets_menu.addSeparator()
        for title, names in (("★ Favourites", favorite_presets()), ("◷ Recent", recent_presets())):
            sub = self.presets_menu.addMenu(title)
            sub.setEnabled(bool(names))
            for n in names:
                add(sub, n, load_slot(n))

        self.presets_menu.addSeparator()
        for cat, names in preset_categories().items():
            sub = self.presets_menu.addMenu(f"{cat}  ({len(names)})")
            for n in names:
                add(sub, n, load_slot(n))

        # Layer B lists presets too.
        for panel in (getattr(self, "image_controls", None), getattr(self, "video_controls", None)):
            if panel is not None and hasattr(panel, "refresh_layer_presets"):
                panel.refresh_layer_presets()
