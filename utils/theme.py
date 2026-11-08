from __future__ import annotations

import tempfile
from pathlib import Path

# ── Palette: "neon violet terminal" ───────────────────────────────────────────
# Near-black, violet-tinted surfaces; neon violet accent; hot pink secondary.
# Token names are kept from the original theme so every module that imports
# them picks up the look automatically.
_P0 = "#060409"  # Darkest (canvas bg)
_P1 = "#0b0811"  # Main background
_P2 = "#0f0b17"  # Panel background
_P3 = "#1c1229"  # Hover background
_P4 = "#130e1d"  # Button background
_P5 = "#261b36"  # Borders
_P6 = "#3d2b57"  # Lighter border
_P7 = "#5f4886"

_G0 = "#c06bff"  # Neon violet (accent / glow)
_G1 = "#9d4ee6"
_G2 = "#6f33a8"
_G3 = "#24123a"  # Subdued violet for selections

_AE  = "#ff5fcf"  # Hot pink (progress, warnings)
_AE2 = "#3a0f2f"

_AM = "#ff5fcf"   # Section titles
_RE = "#ff3b5c"

_FG  = "#dccbf5"  # Main text (pale lavender)
_FG2 = "#8e79ad"  # Secondary text
_FG3 = "#5a4a72"  # Disabled / hint text
_FG4 = "#0b0811"

_HILITE = "#f3e8ff"  # Slider handle hover


# ── Fonts ─────────────────────────────────────────────────────────────────────
# VT323 (SIL OFL, bundled in fonts/) gives the pixel-terminal look. It draws
# smaller than regular monospace at the same px size, so sizes go through fs().

def _resource_dir() -> Path:
    import sys
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


_FONT_FILE = _resource_dir() / "fonts" / "VT323-Regular.ttf"
_PIXEL_FONT = _FONT_FILE.exists()
_FONT_SCALE = 1.45 if _PIXEL_FONT else 1.0
_FW = "normal" if _PIXEL_FONT else "bold"  # VT323 has no bold; synthetic bold smears

_MONO_FONT = ("'VT323', " if _PIXEL_FONT else "") +     "'Cascadia Mono', 'Consolas', 'JetBrains Mono', 'Lucida Console', 'Courier New', monospace"
_SANS_FONT = _MONO_FONT  # everything monospace for the terminal look


def fs(px: float) -> str:
    """Scaled font size for stylesheets, e.g. f"font-size:{fs(11)};"."""
    return f"{round(px * _FONT_SCALE)}px"


def load_fonts() -> None:
    """Register bundled fonts. Call once, after QApplication is created."""
    if not _PIXEL_FONT:
        return
    from PySide6.QtGui import QFontDatabase
    QFontDatabase.addApplicationFont(str(_FONT_FILE))


# ── Texture assets (generated once, referenced from the stylesheet) ───────────

def _build_assets() -> dict[str, str]:
    """Write tiny PNG tiles used by the stylesheet; return {name: posix path}."""
    out = Path(tempfile.gettempdir()) / "dither_guy_fx"
    paths: dict[str, str] = {}
    try:
        from PIL import Image
        out.mkdir(exist_ok=True)

        def rgb(h: str) -> tuple[int, int, int]:
            h = h.lstrip("#")
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore

        # Segmented "LED bar" fill: 3px lit, 1px gap.
        def segments(name: str, color: str, gap: str, h: int) -> None:
            img = Image.new("RGB", (4, h), rgb(gap))
            for x in range(3):
                for y in range(h):
                    img.putpixel((x, y), rgb(color))
            p = out / name
            img.save(p)
            paths[name] = p.as_posix()

        segments("seg_green.png", _G0, _P0, 16)
        segments("seg_amber.png", _AE, _P0, 16)
        segments("seg_dim.png", _P5, _P0, 16)

        # Pixel-art down arrow for combo boxes.
        arrow = Image.new("RGBA", (9, 5), (0, 0, 0, 0))
        for y in range(5):
            for x in range(y, 9 - y):
                arrow.putpixel((x, y), rgb(_G0) + (255,))
        p = out / "arrow_down.png"
        arrow.save(p)
        paths["arrow_down.png"] = p.as_posix()
    except Exception:
        pass
    return paths


_ASSETS = _build_assets()


def _bg_img(name: str, fallback: str) -> str:
    p = _ASSETS.get(name)
    return f"background: {fallback}; background-image: url({p}); background-repeat: repeat-x;" if p \
        else f"background: {fallback};"


# ── Stylesheet ────────────────────────────────────────────────────────────────
_THEME = f"""
* {{ outline: none; }}

/* ── Global ──────────────────────────────────────────────────────────────── */
QMainWindow, QWidget {{
    background-color: {_P1};
    color: {_FG};
    font-family: {_MONO_FONT};
    font-size: {fs(11)};
    selection-background-color: {_G0};
    selection-color: {_P0};
}}

/* ── Menu Bar ────────────────────────────────────────────────────────────── */
QMenuBar {{
    background: {_P0};
    color: {_FG2};
    font-size: {fs(11)};
    border-bottom: 1px solid {_P6};
    padding: 2px 4px;
}}
QMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background: {_G3};
    color: {_G0};
}}
QMenuBar::item:pressed {{
    background: {_G0};
    color: {_P0};
}}
QMenu {{
    background: {_P0};
    border: 1px solid {_G2};
    padding: 3px 0;
    color: {_FG};
    font-size: {fs(11)};
}}
QMenu::item {{
    padding: 4px 28px 4px 16px;
}}
QMenu::item:selected {{
    background: {_G0};
    color: {_P0};
}}
QMenu::item:disabled {{ color: {_FG3}; }}
QMenu::separator {{
    height: 1px;
    background: {_P5};
    margin: 4px 8px;
}}
QMenu::indicator {{ width: 10px; height: 10px; margin-left: 4px; }}
QMenu::indicator:checked {{ background: {_G0}; border: 1px solid {_G0}; }}
QMenu::indicator:unchecked {{ background: transparent; border: 1px solid {_P6}; }}

/* ── ToolBar ─────────────────────────────────────────────────────────────── */
QToolBar {{
    background: {_P0};
    border: none;
    border-bottom: 1px solid {_P5};
    padding: 2px 4px;
    spacing: 2px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    padding: 4px 8px;
    color: {_FG2};
}}
QToolBar QToolButton:hover {{ color: {_G0}; border-color: {_G2}; }}
QToolBar QToolButton:checked {{ color: {_P0}; background: {_G0}; }}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
QTabWidget::pane {{ border: 1px solid {_P5}; background: {_P0}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {_P2};
    border: 1px solid {_P5};
    border-bottom: none;
    padding: 5px 14px;
    color: {_FG2};
    margin-right: 1px;
    min-width: 60px;
}}
QTabBar::tab:selected {{ background: {_P0}; color: {_G0}; border-top: 2px solid {_G0}; }}
QTabBar::tab:hover:!selected {{ color: {_FG}; background: {_P3}; }}

/* ── GroupBox (property panels) ──────────────────────────────────────────── */
QGroupBox {{
    border: 1px dashed {_P6};
    border-radius: 0px;
    margin-top: 16px;
    padding-top: 12px;
    font-size: {fs(10)};
    font-weight: {_FW};
    color: {_AM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 6px;
    top: 1px;
    padding: 0 4px;
    color: {_AM};
    background: {_P1};
}}

/* ── Push Buttons ────────────────────────────────────────────────────────── */
QPushButton {{
    background: {_P4};
    border: 1px solid {_P6};
    border-radius: 0px;
    padding: 4px 10px;
    font-size: {fs(11)};
    color: {_FG};
    min-height: 22px;
}}
QPushButton:hover {{
    border-color: {_G0};
    color: {_G0};
    background: {_P3};
}}
QPushButton:pressed {{
    background: {_G0};
    color: {_P0};
    border-color: {_G0};
}}
QPushButton:checked {{
    background: {_G3};
    color: {_G0};
    border-color: {_G0};
}}
QPushButton:disabled {{
    background: {_P1};
    color: {_FG3};
    border: 1px dotted {_P5};
}}
QPushButton#accent {{
    background: {_G3};
    border: 1px solid {_G0};
    color: {_G0};
    font-weight: {_FW};
}}
QPushButton#accent:hover {{
    background: {_G0};
    color: {_P0};
}}
QPushButton#accent:pressed {{
    background: {_G1};
    color: {_P0};
}}
QPushButton#danger {{
    background: #2a0814;
    border: 1px solid {_RE};
    color: {_RE};
    font-weight: {_FW};
}}
QPushButton#danger:hover {{ background: {_RE}; color: {_P0}; }}

/* ── CheckBox ────────────────────────────────────────────────────────────── */
QCheckBox {{ color: {_FG2}; spacing: 6px; background: transparent; }}
QCheckBox:hover {{ color: {_G0}; }}
QCheckBox::indicator {{
    width: 10px; height: 10px;
    border: 1px solid {_P7};
    background: {_P0};
}}
QCheckBox::indicator:hover {{ border-color: {_G0}; }}
QCheckBox::indicator:checked {{
    background: {_G0};
    border: 1px solid {_G0};
}}
QCheckBox:checked {{ color: {_FG}; }}

/* ── ComboBox ────────────────────────────────────────────────────────────── */
QComboBox {{
    background: {_P0};
    border: 1px solid {_P6};
    border-radius: 0px;
    padding: 2px 6px;
    color: {_G0};
    font-size: {fs(11)};
    min-height: 20px;
}}
QComboBox:hover {{ border-color: {_G0}; }}
QComboBox:focus {{ border-color: {_G0}; }}
QComboBox::drop-down {{ border: none; border-left: 1px solid {_P5}; width: 18px; }}
QComboBox::down-arrow {{
    image: url({_ASSETS.get("arrow_down.png", "")});
    width: 9px;
    height: 5px;
}}
QComboBox QAbstractItemView {{
    background: {_P0};
    border: 1px solid {_G2};
    color: {_FG};
    selection-background-color: {_G0};
    selection-color: {_P0};
    font-size: {fs(11)};
}}

/* ── Slider: segmented LED bar ───────────────────────────────────────────── */
QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{
    height: 6px;
    {_bg_img("seg_dim.png", _P0)}
    border: 1px solid {_P5};
    margin: 0 3px;
}}
QSlider::sub-page:horizontal {{
    {_bg_img("seg_green.png", _G0)}
    border: 1px solid {_G2};
}}
QSlider::handle:horizontal {{
    background: {_FG};
    width: 5px;
    margin: -5px 0;
    border: 1px solid {_P0};
}}
QSlider::handle:horizontal:hover {{ background: {_HILITE}; }}
QSlider::handle:horizontal:pressed {{ background: {_G0}; }}
QSlider::sub-page:horizontal:disabled {{ {_bg_img("seg_dim.png", _P5)} border-color: {_P5}; }}
QSlider::handle:horizontal:disabled {{ background: {_P6}; }}

/* ── Progress bar ────────────────────────────────────────────────────────── */
QProgressBar {{
    background: {_P0};
    border: 1px solid {_P5};
    color: {_FG};
    text-align: center;
    font-size: {fs(10)};
}}
QProgressBar::chunk {{ {_bg_img("seg_amber.png", _AE)} }}

/* ── ScrollBar ───────────────────────────────────────────────────────────── */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: {_P0};
    width: 8px;
    border-left: 1px solid {_P5};
    margin: 0;
}}
QScrollBar:horizontal {{
    background: {_P0};
    height: 8px;
    border-top: 1px solid {_P5};
    margin: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {_P6};
    min-height: 20px;
    min-width: 20px;
    margin: 1px;
}}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{ background: {_G1}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Splitter ────────────────────────────────────────────────────────────── */
QSplitter::handle {{ background: {_P5}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {_G0}; }}

/* ── SpinBox / LineEdit ──────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {_P0};
    border: 1px solid {_P6};
    border-radius: 0px;
    padding: 3px 5px;
    color: {_G0};
    font-size: {fs(11)};
}}
QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{ border-color: {_G0}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; border: none; }}

/* ── StatusBar ───────────────────────────────────────────────────────────── */
QStatusBar {{
    background: {_P0};
    color: {_G0};
    font-size: {fs(11)};
    border-top: 1px solid {_P6};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ background: transparent; }}

/* ── Frames / separators ─────────────────────────────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {_P5};
    background: {_P5};
    border: none;
}}

/* ── Dialog / MessageBox / ToolTip ───────────────────────────────────────── */
QDialog, QMessageBox {{ background: {_P1}; }}
QMessageBox QLabel {{ color: {_FG}; }}
QToolTip {{
    background: {_P0};
    color: {_G0};
    border: 1px solid {_G2};
    padding: 3px 5px;
    font-size: {fs(11)};
}}
"""

THEME = _THEME
