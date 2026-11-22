"""Programmatically drawn icon set (no external assets needed).

Every icon is painted with QPainter on a 24x24 grid with a consistent
1.7 px stroke, round caps and round joins, rendered at 2x for crispness
and cached per (name, colour).  ``icon(name)`` returns a QIcon tinted
with the current application palette's icon colour.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)

_GRID = 24.0
_STROKE = 1.7
_PAINT = 48          # render at 2x for retina crispness

# mid-contrast grey that reads well on BOTH the dark and the light theme,
# so cached icons never need re-tinting when the theme switches
DEFAULT_COLOR = "#8a95a3"

_cache: dict[tuple, QIcon] = {}


# ---------------------------------------------------------------------- #
# small drawing helpers
# ---------------------------------------------------------------------- #
def _pen(color: QColor, width: float = _STROKE) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setWidthF(width)
    return pen


def _path(*points: tuple[float, float]) -> QPainterPath:
    p = QPainterPath(QPointF(points[0][0], points[0][1]))
    for x, y in points[1:]:
        p.lineTo(QPointF(x, y))
    return p


def _round_rect(x, y, w, h, r=2.0) -> QRectF:
    return QRectF(x, y, w, h)


def _paint_icon(name: str, color: QColor) -> QPixmap:
    pm = QPixmap(_PAINT, _PAINT)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # scale the 24-grid onto the 48-px pixmap
    s = _PAINT / _GRID
    p.scale(s, s)
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)

    filled = color

    def line(*pts):
        p.drawPath(_path(*pts))

    def rrect(r, radius=2.0, fill=False):
        p.setBrush(filled if fill else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(*r), radius, radius)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def circle(cx, cy, r, fill=False):
        p.setBrush(filled if fill else Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def tri(x1, y1, x2, y2, x3, y3, fill=True):
        p.setBrush(filled if fill else Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(x1, y1), QPointF(x2, y2),
                                 QPointF(x3, y3)]))
        p.setBrush(Qt.BrushStyle.NoBrush)

    # ------------------------------------------------------------- #
    if name == "new":                       # document with a plus
        p.drawPath(_path((7, 3.5), (13.5, 3.5), (17.5, 7.5), (17.5, 20.5),
                         (7, 20.5)))
        line((7, 3.5), (7, 8), (13.5, 8))
        line((12.25, 12), (12.25, 17.5))
        line((9.5, 14.75), (15, 14.75))

    elif name == "open":                    # folder
        p.drawPath(_path((3.5, 19.5), (3.5, 6), (9.5, 6), (11.5, 8),
                         (17.5, 8), (17.5, 10)))
        p.drawPath(_path((3.5, 19.5), (6.6, 10), (21.4, 10), (18.6, 19.5),
                         (3.5, 19.5)))

    elif name == "save":                    # floppy disk
        rrect((4.5, 4.5, 15, 15), 2.0)
        line((8.5, 4.5), (8.5, 9), (15.5, 9), (15.5, 4.5))
        rrect((8, 13.5, 8, 6), 1.0)

    elif name == "undo":
        line((7.5, 4.5), (3.5, 8.5), (7.5, 12.5))
        p.drawPath(_path((3.5, 8.5), (13, 8.5)))
        p.drawArc(QRectF(8, 8.5, 12, 12), 0, 90 * 16)
        line((20, 14.5), (20, 18))

    elif name == "redo":
        line((16.5, 4.5), (20.5, 8.5), (16.5, 12.5))
        p.drawPath(_path((20.5, 8.5), (11, 8.5)))
        p.drawArc(QRectF(4, 8.5, 12, 12), 90 * 16, 90 * 16)
        line((4, 14.5), (4, 18))

    elif name == "import":                  # arrow into a tray
        line((12, 3.5), (12, 13.5))
        line((8, 10), (12, 14), (16, 10))
        line((4, 14), (4, 18.5), (20, 18.5), (20, 14))

    elif name == "export":                  # film frame (video out)
        rrect((3.5, 5.5, 17, 13), 2.0)
        line((3.5, 9), (20.5, 9))
        line((8, 5.5), (8, 9))
        line((16, 5.5), (16, 9))
        tri(10.6, 11.6, 10.6, 15.9, 15.4, 13.75)

    elif name == "script":                  # text lines
        line((5.5, 5), (18.5, 5))
        line((5.5, 9.5), (18.5, 9.5))
        line((5.5, 14), (14.5, 14))
        line((5.5, 18.5), (11.5, 18.5))

    elif name == "search":
        circle(10.5, 10.5, 6)
        line((15.2, 15.2), (20, 20))

    elif name == "plus":
        line((12, 5), (12, 19))
        line((5, 12), (19, 12))

    elif name == "copy":
        rrect((9, 9, 11, 11), 2.0)
        p.drawPath(_path((5, 15), (5, 5), (15, 5)))

    elif name == "trash":
        line((4.5, 7), (19.5, 7))
        p.drawPath(_path((9.5, 7), (9.5, 4.5), (14.5, 4.5), (14.5, 7)))
        p.drawPath(_path((6.5, 7), (7.5, 19.5), (16.5, 19.5), (17.5, 7)))
        line((10, 10.5), (10, 16))
        line((14, 10.5), (14, 16))

    elif name == "up":
        line((12, 19), (12, 5.5))
        line((6, 11), (12, 5), (18, 11))

    elif name == "down":
        line((12, 5), (12, 18.5))
        line((6, 13), (12, 19), (18, 13))

    elif name == "play":
        tri(8.5, 5.5, 8.5, 18.5, 18.5, 12)

    elif name == "pause":
        rrect((7, 5.5, 3.4, 13), 1.2, fill=True)
        rrect((13.6, 5.5, 3.4, 13), 1.2, fill=True)

    elif name == "stop":
        rrect((7, 7, 10, 10), 1.6, fill=True)

    elif name == "mic":
        p.drawRoundedRect(QRectF(9.5, 3.5, 5, 10), 2.5, 2.5)
        p.drawArc(QRectF(5.5, 8, 13, 12), -190 * 16, 200 * 16)
        line((12, 18), (12, 20.5))
        line((9, 20.5), (15, 20.5))

    elif name == "image":
        rrect((4, 5, 16, 14), 2.0)
        circle(9, 10, 1.5)
        p.drawPath(_path((4, 16.5), (9.5, 11.5), (13, 15), (15.5, 12.5),
                         (20, 16.5)))

    elif name == "sun":
        circle(12, 12, 3.6)
        for ang in range(0, 360, 45):
            a = math.radians(ang)
            x1 = 12 + 6.2 * math.cos(a)
            y1 = 12 + 6.2 * math.sin(a)
            x2 = 12 + 8.2 * math.cos(a)
            y2 = 12 + 8.2 * math.sin(a)
            line((x1, y1), (x2, y2))

    elif name == "moon":
        path = QPainterPath(QPointF(19.5, 14.5))
        path.arcTo(QRectF(4.5, 4.5, 15, 15), 40, 230)
        path.arcTo(QRectF(8.5, 8, 11.5, 11.5), 200, -140)
        path.closeSubpath()
        p.drawPath(path)

    elif name in ("zoom-in", "zoom-out"):
        circle(10.5, 10.5, 6)
        line((15.2, 15.2), (20, 20))
        line((8, 10.5), (13, 10.5))
        if name == "zoom-in":
            line((10.5, 8), (10.5, 13))

    elif name == "fit":                     # corner brackets
        p.drawPath(_path((9, 4.5), (5.5, 4.5), (5.5, 8)))
        p.drawPath(_path((15, 4.5), (18.5, 4.5), (18.5, 8)))
        p.drawPath(_path((9, 19.5), (5.5, 19.5), (5.5, 16)))
        p.drawPath(_path((15, 19.5), (18.5, 19.5), (18.5, 16)))
        rrect((9.5, 9.5, 5, 5), 1.0)

    elif name == "refresh":
        p.drawArc(QRectF(5, 5, 14, 14), 30 * 16, 280 * 16)
        line((17.5, 3.5), (17.5, 8.5), (12.5, 8.5))

    elif name == "music":
        p.drawPath(_path((9.5, 17.5), (9.5, 5), (19, 3.5), (19, 15.5)))
        circle(7, 17.5, 2.5)
        circle(16.5, 15.5, 2.5)

    elif name == "gear":
        circle(12, 12, 3.1)
        for ang in range(0, 360, 45):
            a = math.radians(ang)
            line((12 + 5.4 * math.cos(a), 12 + 5.4 * math.sin(a)),
                 (12 + 8.3 * math.cos(a), 12 + 8.3 * math.sin(a)))

    elif name == "globe":
        circle(12, 12, 8)
        p.drawEllipse(QPointF(12, 12), 3.6, 8)
        line((4, 12), (20, 12))

    elif name == "check":
        line((5, 12.5), (9.5, 17), (19, 7))

    elif name == "close":
        line((6.5, 6.5), (17.5, 17.5))
        line((17.5, 6.5), (6.5, 17.5))

    elif name == "present":                 # monitor with play
        rrect((3.5, 4.5, 17, 12), 1.8)
        tri(10.5, 8, 10.5, 13, 15, 10.5)
        line((12, 16.5), (12, 19.5))
        line((8, 19.5), (16, 19.5))

    elif name == "chevron-down":
        line((7, 9.5), (12, 14.5), (17, 9.5))

    elif name == "chevron-right":
        line((9.5, 7), (14.5, 12), (9.5, 17))

    elif name == "help":
        circle(12, 12, 8)
        p.drawArc(QRectF(9, 6.5, 6, 6), 40 * 16, 240 * 16)
        line((12, 12.5), (12, 14.5))
        line((12, 17), (12, 17.01))

    elif name == "wand":
        line((5, 19), (13.5, 10.5))
        line((15, 4), (15, 8))
        line((13, 6), (17, 6))
        line((19.5, 9.5), (19.5, 12.5))
        line((18, 11), (21, 11))
        line((17.5, 16), (17.5, 18))
        line((16.5, 17), (18.5, 17))

    elif name == "clock":
        circle(12, 12, 8)
        line((12, 7), (12, 12), (15.5, 14))

    elif name == "film":                    # clapperboard
        rrect((3.5, 7.5, 17, 12), 2.0)
        p.drawPath(_path((3.5, 7.5), (5.5, 3.5), (20.5, 3.5), (18.8, 7.5)))
        line((9.5, 3.9), (8, 7.5))
        line((15.5, 3.9), (14, 7.5))

    else:                                   # fallback: small square
        rrect((6, 6, 12, 12), 2.0)

    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


# ---------------------------------------------------------------------- #
# public API
# ---------------------------------------------------------------------- #
def pixmap(name: str, color: str | QColor | None = None) -> QPixmap:
    """A 24x24 (logical) icon pixmap, painted at 2x."""
    if color is None:
        color = DEFAULT_COLOR
    color = QColor(color) if isinstance(color, str) else color
    key = (name, color.name())
    pm = _cache.get(key)
    if pm is None:
        pm = _paint_icon(name, color)
        _cache[key] = pm
    return pm


def icon(name: str, color: str | QColor | None = None) -> QIcon:
    if color is None:
        color = DEFAULT_COLOR
    color = QColor(color) if isinstance(color, str) else color
    key = (name, color.name(), "icon")
    ic = _cache.get(key)
    if ic is None:
        ic = QIcon(pixmap(name, color))
        _cache[key] = ic
    return ic


AVAILABLE = (
    "new open save undo redo import export script search plus copy "
    "trash up down play pause stop mic image sun moon zoom-in zoom-out "
    "fit refresh music gear globe check close present chevron-down "
    "chevron-right help wand film clock"
).split()


def available() -> list[str]:
    return list(AVAILABLE)


# asset helpers for the stylesheet (checkbox ticks, combo arrows...) ----- #
def save_asset(name: str, color: str, path: str, size: int = 14) -> None:
    """Render a small glyph to a PNG file for use inside QSS url()."""
    pm = pixmap(name, color)
    img = pm.toImage().scaled(size * 2, size * 2,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
    img.setDevicePixelRatio(2.0)
    img.save(path, "PNG")


def icon_size() -> QSize:
    return QSize(20, 20)
