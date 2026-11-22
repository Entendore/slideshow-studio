"""Application design system.

A single palette of design tokens drives the whole stylesheet — the GUI is
built twice (a professional dark theme and a clean light theme) from the
same template, so switching themes is one call.

Tokens are plain dicts; ``build_qss()`` renders the QSS from them and
``apply_theme()`` wires everything up (it also generates the small glyph
PNGs that QSS needs for checkboxes / radio buttons / combo arrows).
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------- #
# palettes
# ---------------------------------------------------------------------- #
THEMES: dict[str, dict] = {
    "dark": dict(
        window="#15191f", panel="#1a2027", elevated="#212935",
        hover="#28313d", pressed="#2f3a48",
        border="#2b3541", border_strong="#3d4a59",
        text="#dce4ec", text_dim="#8b98a6", text_disabled="#5f6b78",
        accent="#4d9dff", accent_hover="#69aeff", accent_pressed="#3a89ef",
        on_accent="#ffffff",
        selection="#2c5d8f", selection_text="#ffffff",
        danger="#e5534b", success="#46c489", warning="#d9a53f",
        icon="#b9c4cf", icon_dim="#7f8b98",
        canvas_bg="#101418", canvas_border="#39434f",
        scrollbar="#39434f", scrollbar_hover="#4d5a68",
        tooltip_bg="#232c37", shadow_qcolor=170,
        accent_soft="#253850",
    ),
    "light": dict(
        window="#eef1f4", panel="#f6f8fa", elevated="#ffffff",
        hover="#e6ebf0", pressed="#d9e0e7",
        border="#d2d9e0", border_strong="#b8c2cc",
        text="#232a31", text_dim="#66727d", text_disabled="#a4aeb7",
        accent="#0b66d0", accent_hover="#1f77e0", accent_pressed="#0a57b4",
        on_accent="#ffffff",
        selection="#c8def6", selection_text="#0f3a63",
        danger="#d3392f", success="#178f5c", warning="#a86f12",
        icon="#4d5761", icon_dim="#8b96a0",
        canvas_bg="#dde3e9", canvas_border="#b3bec8",
        scrollbar="#c0c9d2", scrollbar_hover="#a6b2bd",
        tooltip_bg="#ffffff", shadow_qcolor=90,
        accent_soft="#dbe9fb",
    ),
}

FONT_STACK = ('"Segoe UI", "Inter", "SF Pro Text", "Noto Sans", '
              '"Helvetica Neue", Arial, sans-serif')

_current_name = "dark"
_current: dict = THEMES["dark"]


def tokens() -> dict:
    """Design tokens of the currently applied theme."""
    return _current


def theme_name() -> str:
    return _current_name


# ---------------------------------------------------------------------- #
# glyph assets used inside the stylesheet
# ---------------------------------------------------------------------- #
_ASSETS: dict[str, str] = {}


def _assets_dir() -> str:
    from . import workspace
    d = os.path.join(workspace.workspace_dir(), "ui-assets")
    os.makedirs(d, exist_ok=True)
    return d


def _ensure_assets(theme_name_: str) -> dict[str, str]:
    """(Re)generate the tiny PNGs the stylesheet references, per theme."""
    global _ASSETS
    t = THEMES[theme_name_]
    d = _assets_dir()
    out: dict[str, str] = {}
    from . import icons
    jobs = {
        "tick": ("check", t["accent"]),
        "tick_dis": ("check", t["text_disabled"]),
        "radio": ("radio-dot", t["accent"]),
        "combo": ("chevron-down", t["text_dim"]),
        "spin_up": ("chevron-up-sm", t["text_dim"]),
        "spin_down": ("chevron-down", t["text_dim"]),
    }
    for key, (glyph, color) in jobs.items():
        path = os.path.join(d, f"{theme_name_}-{key}.png")
        if not os.path.isfile(path):
            if glyph == "radio-dot":
                _make_dot_png(color, path)
            elif glyph == "chevron-up-sm":
                _make_chevron_png(color, path, up=True)
            else:
                icons.save_asset(glyph, color, path, size=10 if key != "tick"
                                 else 12)
        out[key] = path
    _ASSETS = out
    return out


def _make_dot_png(color: str, path: str, size: int = 8) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(int(size * 0.3), int(size * 0.3), int(size * 0.7),
                  int(size * 0.7))
    p.end()
    pm.setDevicePixelRatio(2.0)
    pm.save(path, "PNG")


def _make_chevron_png(color: str, path: str, up: bool = False,
                      size: int = 8) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QPixmap,
                               QTransform)
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    pathobj = QPainterPath(QPointF(1.2, 2.6))
    pathobj.lineTo(QPointF(4.0, 5.4))
    pathobj.lineTo(QPointF(6.8, 2.6))
    if up:
        t = QTransform()
        t.translate(size, size)
        t.rotate(180)
        p.setTransform(t)
    p.drawPath(pathobj)
    p.end()
    pm.setDevicePixelRatio(2.0)
    pm.save(path, "PNG")


# ---------------------------------------------------------------------- #
# the stylesheet
# ---------------------------------------------------------------------- #
def build_qss(t: dict, a: dict[str, str] | None = None) -> str:
    """Render the application stylesheet from design tokens *t*.

    *a* maps asset keys to PNG paths; when omitted, no image assets are
    referenced (checkbox glyphs fall back to styled boxes).
    """
    a = a or {}
    tick = f"url({a['tick']})" if "tick" in a else "none"
    tick_dis = f"url({a['tick_dis']})" if "tick_dis" in a else "none"
    radio = f"url({a['radio']})" if "radio" in a else "none"
    combo = f"url({a['combo']})" if "combo" in a else "none"
    spin_up = f"url({a['spin_up']})" if "spin_up" in a else "none"
    spin_down = f"url({a['spin_down']})" if "spin_down" in a else "none"

    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {t['text']};
    selection-background-color: {t['selection']};
    selection-color: {t['selection_text']};
}}
QMainWindow, QDialog {{
    background-color: {t['window']};
}}
QWidget {{ background: transparent; }}
QMainWindow {{ background-color: {t['window']}; }}

/* ---------------- menus ---------------- */
QMenuBar {{
    background: {t['panel']};
    border-bottom: 1px solid {t['border']};
    padding: 2px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 9px;
    border-radius: 6px;
}}
QMenuBar::item:selected {{ background: {t['hover']}; }}
QMenu {{
    background: {t['elevated']};
    border: 1px solid {t['border_strong']};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 26px 6px 14px;
    border-radius: 6px;
    background: transparent;
}}
QMenu::item:selected {{ background: {t['selection']}; color: {t['selection_text']}; }}
QMenu::item:disabled {{ color: {t['text_disabled']}; }}
QMenu::separator {{
    height: 1px;
    background: {t['border']};
    margin: 5px 8px;
}}
QMenu::icon {{ padding-left: 8px; }}

/* ---------------- toolbar ---------------- */
QToolBar {{
    background: {t['panel']};
    border-bottom: 1px solid {t['border']};
    spacing: 3px;
    padding: 5px 8px;
}}
QToolBar::separator {{
    background: {t['border']};
    width: 1px;
    margin: 5px 7px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 9px;
    color: {t['text']};
}}
QToolBar QToolButton:hover {{ background: {t['hover']}; }}
QToolBar QToolButton:pressed {{ background: {t['pressed']}; }}
QToolBar QToolButton:checked {{ background: {t['accent_soft']}; color: {t['accent']}; }}
QToolBar QToolButton:disabled {{ color: {t['text_disabled']}; }}

/* ---------------- buttons ---------------- */
QPushButton {{
    background: {t['elevated']};
    border: 1px solid {t['border_strong']};
    border-radius: 7px;
    padding: 6px 14px;
    color: {t['text']};
}}
QPushButton:hover {{ background: {t['hover']}; border-color: {t['border_strong']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['text_disabled']}; background: {t['panel']}; border-color: {t['border']}; }}
QPushButton:focus {{ border-color: {t['accent']}; }}
QPushButton[primary="true"] {{
    background: {t['accent']};
    border: 1px solid {t['accent']};
    color: {t['on_accent']};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[primary="true"]:pressed {{ background: {t['accent_pressed']}; }}
QPushButton[danger="true"] {{
    background: transparent;
    border: 1px solid {t['danger']};
    color: {t['danger']};
}}
QPushButton[danger="true"]:hover {{ background: {t['danger']}; color: #ffffff; }}
QPushButton[ghost="true"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t['text_dim']};
}}
QPushButton[ghost="true"]:hover {{ background: {t['hover']}; color: {t['text']}; }}

QToolButton[panelBtn="true"] {{
    background: transparent;
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 4px;
}}
QToolButton[panelBtn="true"]:hover {{ background: {t['hover']}; border-color: {t['border_strong']}; }}
QToolButton[panelBtn="true"]:pressed {{ background: {t['pressed']}; }}
QToolButton[panelBtn="true"]:disabled {{ color: {t['text_disabled']}; border-color: {t['border']}; }}
QToolButton[sectionHeader="true"] {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 2px;
    font-weight: 700;
    font-size: 11px;
    color: {t['text_dim']};
    text-align: left;
}}
QToolButton[sectionHeader="true"]:hover {{ color: {t['text']}; }}

/* guided workflow pipeline bar */
QLabel[wfArrow="true"] {{
    color: {t['text_disabled']};
    background: transparent;
}}
QToolButton[wfStep="true"] {{
    background: {t['panel']};
    border: 1px solid {t['border']};
    border-radius: 13px;
    padding: 4px 12px;
    color: {t['text_dim']};
}}
QToolButton[wfStep="true"]:hover {{
    background: {t['hover']};
    border-color: {t['border_strong']};
    color: {t['text']};
}}
QToolButton[wfStep="true"][wfState="current"] {{
    background: {t['accent_soft']};
    border: 1px solid {t['accent']};
    color: {t['text']};
    font-weight: 600;
}}
QToolButton[wfStep="true"][wfState="done"] {{
    background: transparent;
    border-color: {t['border']};
    color: {t['success']};
}}

/* ---------------- inputs ---------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t['elevated']};
    border: 1px solid {t['border_strong']};
    border-radius: 7px;
    padding: 5px 8px;
    color: {t['text']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {t['accent']};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled {{
    color: {t['text_disabled']};
    background: {t['panel']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: {combo};
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {t['elevated']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {t['selection']};
    selection-color: {t['selection_text']};
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
    margin: 1px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: {spin_up}; width: 8px; height: 8px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: {spin_down}; width: 8px; height: 8px;
}}

/* ---------------- check & radio ---------------- */
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t['text_disabled']}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {t['border_strong']};
    background: {t['elevated']};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {t['accent']};
}}
QCheckBox::indicator:checked {{ image: {tick}; border-color: {t['accent']}; }}
QCheckBox::indicator:checked:disabled {{ image: {tick_dis}; border-color: {t['border']}; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QRadioButton::indicator:checked {{ image: {radio}; border-color: {t['accent']}; }}

/* ---------------- lists / views ---------------- */
QListWidget, QTreeWidget, QListView {{
    background: {t['panel']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 5px;
    border-radius: 6px;
    margin: 1px 2px;
    color: {t['text']};
}}
QListWidget::item:selected {{
    background: {t['selection']};
    color: {t['selection_text']};
}}
QListWidget::item:hover:!selected {{ background: {t['hover']}; }}

/* ---------------- tabs ---------------- */
QTabWidget::pane {{
    border: 1px solid {t['border']};
    border-radius: 8px;
    background: {t['panel']};
    top: -1px;
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {t['text_dim']};
    padding: 7px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{
    color: {t['text']};
    border-bottom: 2px solid {t['accent']};
    font-weight: 600;
}}

/* ---------------- sliders ---------------- */
QSlider {{ background: transparent; min-height: 22px; }}
QSlider::groove:horizontal {{
    height: 5px;
    background: {t['border_strong']};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {t['accent']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {t['elevated']};
    border: 2px solid {t['accent']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: {t['accent_soft']}; }}
QSlider::handle:horizontal:disabled {{
    border-color: {t['border_strong']};
    background: {t['panel']};
}}

/* ---------------- progress ---------------- */
QProgressBar {{
    background: {t['elevated']};
    border: 1px solid {t['border_strong']};
    border-radius: 7px;
    text-align: center;
    color: {t['text']};
    height: 18px;
}}
QProgressBar::chunk {{
    background: {t['accent']};
    border-radius: 6px;
}}

/* ---------------- bars & splitters ---------------- */
QStatusBar {{
    background: {t['panel']};
    border-top: 1px solid {t['border']};
    color: {t['text_dim']};
}}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{
    background: {t['border']};
    width: 3px;
}}
QSplitter::handle:hover {{ background: {t['accent']}; }}

/* ---------------- scrollbars ---------------- */
QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t['scrollbar']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['scrollbar_hover']}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t['scrollbar']};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t['scrollbar_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- misc ---------------- */
QGroupBox {{
    border: 1px solid {t['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    background: {t['panel']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {t['text_dim']};
}}
QToolTip {{
    background: {t['tooltip_bg']};
    color: {t['text']};
    border: 1px solid {t['border_strong']};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 12px;
}}
QLabel {{
    background: transparent;
}}
QLabel[heading="true"] {{
    font-size: 11px;
    font-weight: 700;
    color: {t['text_dim']};
    background: transparent;
    padding: 2px 0;
}}
QLabel[hint="true"] {{
    color: {t['text_dim']};
    font-size: 11px;
    background: transparent;
}}
QLabel[cardTitle="true"] {{
    font-size: 13px;
    font-weight: 600;
    color: {t['text']};
    background: transparent;
}}
QFrame[hrule="true"] {{
    border: none;
    border-top: 1px solid {t['border']};
    max-height: 1px;
}}
QMessageBox {{ background: {t['window']}; }}
QMessageBox QLabel {{ color: {t['text']}; font-size: 13px; }}
QSizeGrip {{ background: transparent; width: 8px; height: 8px; }}
"""


# ---------------------------------------------------------------------- #
# application-level helpers
# ---------------------------------------------------------------------- #
def apply_theme(app, name: str = "dark") -> None:
    """Apply a built-in theme by name ("dark" or "light")."""
    global _current, _current_name
    if name not in THEMES:
        name = "dark"
    _current = THEMES[name]
    _current_name = name
    assets = _ensure_assets(name)
    app.setStyleSheet(build_qss(_current, assets))


def themed_qss(name: str = "dark") -> str:
    assets = _ensure_assets(name)
    return build_qss(THEMES[name], assets)


# Backwards-compatible alias: module import used to expose a plain dark QSS.
DARK_QSS = build_qss(THEMES["dark"])
