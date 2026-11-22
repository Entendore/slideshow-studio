"""Center canvas: WYSIWYG 16:9 slide preview using the shared renderer.

Adds editor-grade viewport behaviour: Ctrl+wheel zoom anchored at the
cursor, drag-to-pan, zoom-to-fit / 100 % controls, a soft drop shadow
and a friendly empty state.  All chrome colours follow the active app
theme.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QImage, QPainter, QPen,
                           QPolygonF)
from PySide6.QtWidgets import QWidget

from .render import BASE_W, BASE_H, overlay_info, render_slide

_MARGIN = 24          # breathing room around the slide, device px

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}


class SlideCanvas(QWidget):
    clicked = Signal()
    zoomChanged = Signal()          # zoom level or pan changed
    backgroundDropped = Signal(str)  # local image path dropped on the slide

    MIN_ZOOM = 0.08
    MAX_ZOOM = 4.0
    ZOOM_STEP = 1.25

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck = None
        self._index = -1
        self._img: QImage | None = None
        self._img_key = None
        self._zoom: float | None = None       # None = fit to window
        self._pan = QPointF(0, 0)
        self._drag_start: QPointF | None = None
        self._pan_start: QPointF | None = None
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)      # image drop -> slide background

    # ------------------------------------------------------------------ #
    # deck plumbing (unchanged API)
    # ------------------------------------------------------------------ #
    def set_deck(self, deck) -> None:
        self._deck = deck
        self.invalidate()

    def set_index(self, index: int) -> None:
        self._index = index
        self.invalidate()

    def invalidate(self) -> None:
        self._img = None
        self._img_key = None
        self.update()

    # ------------------------------------------------------------------ #
    # zoom API
    # ------------------------------------------------------------------ #
    def _fit_scale(self) -> float:
        aw, ah = self.width() - _MARGIN * 2, self.height() - _MARGIN * 2
        if aw <= 10 or ah <= 10:
            return 0.2
        return min(aw / BASE_W, ah / BASE_H)

    def _scale(self) -> float:
        return self._fit_scale() if self._zoom is None else self._zoom

    def is_fit(self) -> bool:
        return self._zoom is None

    def zoom_pct(self) -> int:
        """Current zoom as a percentage of the 1600x900 design size."""
        return int(round(self._scale() * 100))

    def zoom_in(self) -> None:
        base = self._zoom if self._zoom is not None else self._fit_scale()
        self._set_zoom(max(self.MIN_ZOOM,
                           min(self.MAX_ZOOM, base * self.ZOOM_STEP)))

    def zoom_out(self) -> None:
        base = self._zoom if self._zoom is not None else self._fit_scale()
        self._set_zoom(max(self.MIN_ZOOM,
                           min(self.MAX_ZOOM, base / self.ZOOM_STEP)))

    def zoom_fit(self) -> None:
        self._zoom = None
        self._pan = QPointF(0, 0)
        self._img_key = None
        self.update()
        self.zoomChanged.emit()

    def zoom_100(self) -> None:
        self._set_zoom(1.0)

    def _set_zoom(self, scale: float) -> None:
        scale = max(self.MIN_ZOOM, min(self.MAX_ZOOM, scale))
        if self._zoom == scale:
            return
        self._zoom = scale
        self._clamp_pan()
        self._img_key = None
        self.update()
        self.zoomChanged.emit()

    def _zoom_at(self, factor: float, pos: QPointF) -> None:
        """Zoom keeping the design point under *pos* stationary."""
        old_scale = self._scale()
        old_rect = self._target_rect()
        design = ((pos.x() - old_rect.left()) / old_scale,
                  (pos.y() - old_rect.top()) / old_scale)
        new_scale = max(self.MIN_ZOOM,
                        min(self.MAX_ZOOM, old_scale * factor))
        if self._zoom is None and abs(new_scale - old_scale) < 1e-6:
            new_scale = old_scale * factor
        self._zoom = new_scale
        cw, ch = BASE_W * new_scale, BASE_H * new_scale
        self._pan = QPointF((self.width() - cw) / 2.0
                            - (pos.x() - design[0] * new_scale),
                            (self.height() - ch) / 2.0
                            - (pos.y() - design[1] * new_scale))
        self._clamp_pan()
        self._img_key = None
        self.update()
        self.zoomChanged.emit()

    # ------------------------------------------------------------------ #
    # geometry helpers
    # ------------------------------------------------------------------ #
    def _target_rect(self) -> QRectF:
        scale = self._scale()
        cw, ch = BASE_W * scale, BASE_H * scale
        x = (self.width() - cw) / 2.0 - self._pan.x()
        y = (self.height() - ch) / 2.0 - self._pan.y()
        return QRectF(x, y, cw, ch)

    def _overflows(self) -> bool:
        scale = self._scale()
        return (BASE_W * scale > self.width() - _MARGIN * 2 or
                BASE_H * scale > self.height() - _MARGIN * 2)

    def _clamp_pan(self) -> None:
        scale = self._scale()
        cw, ch = BASE_W * scale, BASE_H * scale
        mx = max(0.0, (cw - (self.width() - _MARGIN * 2)) / 2.0)
        my = max(0.0, (ch - (self.height() - _MARGIN * 2)) / 2.0)
        self._pan.setX(max(-mx, min(mx, self._pan.x())))
        self._pan.setY(max(-my, min(my, self._pan.y())))

    # ------------------------------------------------------------------ #
    # painting
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802
        from . import styles
        t = styles.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(t["canvas_bg"]))

        rect = self._target_rect()
        if rect.isEmpty() or rect.width() < 2:
            p.end()
            return

        # soft drop shadow under the slide
        shadow_alpha = int(38 * t.get("shadow_qcolor", 170) / 170.0)
        p.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((2, shadow_alpha), (6, int(shadow_alpha * 0.6)),
                            (12, int(shadow_alpha * 0.35))):
            c = QColor(0, 0, 0, max(4, alpha))
            p.setBrush(c)
            p.drawRoundedRect(rect.adjusted(-grow / 2, -grow / 2,
                                            grow / 2, grow / 2), 10, 10)

        p.setPen(QColor(t["canvas_border"]))
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(rect, 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)

        if self._deck is None or not self._deck.slides:
            self._paint_empty(p, rect)
            p.end()
            return

        idx = max(0, min(self._index, len(self._deck.slides) - 1))
        slide = self._deck.slides[idx]
        ov = overlay_info(self._deck, idx)
        key = (idx, int(rect.width()), int(rect.height()),
               slide.title, slide.body, slide.body_format, slide.image,
               repr(sorted(self._deck.theme.to_dict().items())),
               repr(sorted(ov.items())) if ov else None)
        if self._img is None or self._img_key != key:
            self._img = render_slide(slide, self._deck.theme,
                                     int(rect.width()) or 640,
                                     int(rect.height()) or 360,
                                     overlay=ov)
            self._img_key = key
        p.setOpacity(1.0)
        p.drawImage(rect, self._img)
        p.end()

    def _paint_empty(self, p: QPainter, rect: QRectF) -> None:
        from . import styles
        t = styles.tokens()
        dim = QColor(t["text_dim"])
        # simple frame glyph
        icon_r = QRectF(0, 0, 44, 34)
        icon_r.moveCenter(QRectF(rect).center()
                          + QPointF(0, -46))
        p.setPen(QPen(dim, 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(icon_r, 6, 6)
        cx, cy = icon_r.center().x(), icon_r.center().y()
        p.setBrush(dim)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(cx - 5, cy - 7),
                                 QPointF(cx - 5, cy + 7),
                                 QPointF(cx + 8, cy)]))
        f = self.font()
        f.setPointSize(12)
        p.setFont(f)
        p.setPen(dim)
        p.drawText(QRectF(rect.left(), rect.center().y() + 6,
                          rect.width(), 80),
                   Qt.AlignmentFlag.AlignHCenter |
                   Qt.AlignmentFlag.AlignTop,
                   "No slides yet\n\nUse  File ▸ Import  or the  +  button "
                   "in the Slides panel to begin")
        p.setBrush(Qt.BrushStyle.NoBrush)

    # ------------------------------------------------------------------ #
    # interaction: pan + wheel zoom
    # ------------------------------------------------------------------ #
    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = delta.y() / 120.0
            self._zoom_at(1.15 ** steps, event.position())
            event.accept()
            return
        if self._overflows():
            dx, dy = 0.0, 0.0
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                dx = delta.y() / 2.0
            else:
                dy = delta.y() / 2.0
                if delta.x():
                    dx = delta.x() / 2.0
            self._pan -= QPointF(dx, dy)
            self._clamp_pan()
            self.update()
            self.zoomChanged.emit()
            event.accept()
            return
        event.ignore()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        if self._overflows() and \
                event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._pan_start = QPointF(self._pan)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._pan = self._pan_start + (event.position()
                                           - self._drag_start)
            self._clamp_pan()
            self.update()
            event.accept()
            return
        if self._overflows():
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._drag_start = None
            self._pan_start = None
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._clamp_pan()
        super().resizeEvent(event)

    # ------------------------------------------------------------------ #
    # image paste / drop -> slide background
    # ------------------------------------------------------------------ #
    def paste_background(self) -> bool:
        """Use the clipboard image as the current slide's background."""
        from PySide6.QtGui import QGuiApplication
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return False
        try:
            from .workspace import stage_image
            path = stage_image(img)
        except Exception:
            return False
        self.backgroundDropped.emit(path)
        return True

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._mime_has_image(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._mime_has_image(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        if md.hasUrls():
            for url in md.urls():
                if not url.isLocalFile():
                    continue
                path = url.toLocalFile()
                if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
                    event.acceptProposedAction()
                    self.backgroundDropped.emit(path)
                    return
        event.ignore()

    @staticmethod
    def _mime_has_image(md) -> bool:
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile() and \
                        os.path.splitext(url.toLocalFile())[1].lower() \
                        in IMAGE_EXTS:
                    return True
        return False
