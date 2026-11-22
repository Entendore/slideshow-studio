"""Left panel: slide list with live thumbnails and drag-to-reorder."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QListWidget, QListWidgetItem,
                               QMenu)

from .render import overlay_info, render_slide

THUMB_W, THUMB_H = 208, 117


class SlideListWidget(QListWidget):
    slideSelected = Signal(int)          # user picked a slide
    orderChanged = Signal(int, int)      # from, to
    deleteRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck = None
        self._thumbs: dict[str, QPixmap] = {}
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setSpacing(6)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.currentRowChanged.connect(self._on_row_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    # ------------------------------------------------------------------ #
    def set_deck(self, deck) -> None:
        self._deck = deck
        self._thumbs.clear()
        self.refresh()

    def refresh(self, keep_current: bool = True) -> None:
        cur = self.currentRow() if keep_current else -1
        self.blockSignals(True)
        self.clear()
        if self._deck:
            for i, slide in enumerate(self._deck.slides):
                item = QListWidgetItem(QIcon(self._thumb(i)), "")
                item.setText(self._label(i, slide))
                item.setToolTip(self._tooltip(i, slide))
                self.addItem(item)
        self.blockSignals(False)
        if 0 <= cur < self.count():
            self.setCurrentRow(cur)
        elif self.count():
            self.setCurrentRow(0)

    def update_thumb(self, index: int) -> None:
        if not self._deck or not (0 <= index < len(self._deck.slides)):
            return
        slide = self._deck.slides[index]
        self._thumbs.pop(self._ckey(index), None)
        if 0 <= index < self.count():
            item = self.item(index)
            item.setIcon(QIcon(self._thumb(index)))
            item.setText(self._label(index, slide))
            item.setToolTip(self._tooltip(index, slide))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _label(index: int, slide) -> str:
        label = slide.title.strip() or "(untitled)"
        if len(label) > 38:
            label = label[:36] + "…"
        marks = ""
        if slide.voice:
            marks += " ·V"
        if slide.duration_override:
            marks += " ·T"
        if getattr(slide, "motion", "none") != "none":
            marks += " ·M"
        if slide.image:
            marks += " ·I"
        return f"{index + 1}.  {label}{marks}"

    @staticmethod
    def _tooltip(index: int, slide) -> str:
        bits = [f"Slide {index + 1}"]
        if slide.title.strip():
            bits.append(slide.title.strip())
        bits.append("")
        bits.append(f"Narration: {len(slide.narration.strip())} chars")
        vs = slide.voice
        bits.append("Voice: " + (vs.voice if vs else "deck default"))
        if vs and (vs.rate or vs.volume or vs.pitch):
            bits.append(f"  rate {vs.rate:+d}%  volume {vs.volume:+d}%  "
                        f"pitch {vs.pitch:+d}Hz")
        if slide.duration_override:
            bits.append(f"Duration override: {slide.duration_override:g} s")
        if getattr(slide, "motion", "none") != "none":
            bits.append(f"Motion: {slide.motion}")
        if slide.image:
            bits.append(f"Image: {os.path.basename(slide.image)}")
        bits.append("")
        bits.append("V=voice  T=timing  M=motion  I=image")
        return "\n".join(bits)

    # ------------------------------------------------------------------ #
    def _ckey(self, index: int) -> tuple:
        """Thumbnail cache key: slide id + deck overlay signature."""
        slide = self._deck.slides[index]
        ov = overlay_info(self._deck, index)
        return (slide.id, repr(sorted(ov.items())) if ov else None)

    def _thumb(self, index: int) -> QPixmap:
        key = self._ckey(index)
        if key in self._thumbs and key[0]:
            return self._thumbs[key]
        slide = self._deck.slides[index]
        img = render_slide(slide, self._deck.theme if self._deck else None,
                           THUMB_W * 2, THUMB_H * 2,
                           overlay=overlay_info(self._deck, index))
        pm = QPixmap.fromImage(img).scaled(
            QSize(THUMB_W, THUMB_H), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        pm = self._round(pm, 6)
        self._thumbs[key] = pm
        return pm

    @staticmethod
    def _round(pm: QPixmap, radius: int = 6) -> QPixmap:
        """Give a thumbnail rounded corners so the list reads as cards."""
        from PySide6.QtGui import QPainter, QPainterPath
        out = QPixmap(pm.size())
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, pm.width(), pm.height(), radius, radius)
        p.setClipPath(path)
        p.drawPixmap(0, 0, pm)
        p.end()
        return out

    def _on_row_changed(self, row: int) -> None:
        if row >= 0:
            self.slideSelected.emit(row)

    def dropEvent(self, event) -> None:  # noqa: N802
        src_row = self.currentRow()
        super().dropEvent(event)
        dst_row = self.currentRow()
        if src_row != dst_row and src_row >= 0 and dst_row >= 0:
            self.orderChanged.emit(src_row, dst_row)

    def _context_menu(self, pos) -> None:
        row = self.currentRow()
        if row < 0 or not self._deck:
            return
        menu = QMenu(self)
        act_dup = menu.addAction("Duplicate Slide")
        act_del = menu.addAction("Delete Slide")
        menu.addSeparator()
        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_del:
            self.deleteRequested.emit(row)
        elif chosen is act_dup:
            self.window().duplicate_current_slide()
        elif chosen is act_up and row > 0:
            self.orderChanged.emit(row, row - 1)
        elif chosen is act_down and row < self.count() - 1:
            self.orderChanged.emit(row, row + 1)
