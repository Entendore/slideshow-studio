"""Rehearse timings: run the deck like a talk and record slide durations.

A full-screen runner shaped like present mode, but silent — *you* are the
narrator.  A stopwatch shows how long the current slide has been on
screen (plus the total run time); the time spent on every slide is
recorded and can be applied back to the deck as per-slide **minimum
durations**, so exports pace the slides the way you rehearsed them.

Keys:

    Right / Space / PgDown / click   next slide
    Left / PgUp / Backspace          previous slide
    Home / End                       first / last slide
    F                                toggle fullscreen
    Esc                              finish and show the summary

The window itself never touches the deck — ``finishedRun`` carries the
recorded seconds and the main window offers the *Apply* step (one undo).
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QLabel, QWidget

from .present import mmss
from .render import BASE_W, BASE_H, render_slide


def format_summary(times: list[float]) -> str:
    """Human-readable multi-line summary of recorded slide times."""
    lines = []
    for i, secs in enumerate(times):
        if secs > 0:
            lines.append(f"Slide {i + 1} — {mmss(secs)}")
        else:
            lines.append(f"Slide {i + 1} — (not rehearsed)")
    return "\n".join(lines) if lines else "Nothing recorded."


class RehearseWindow(QWidget):
    """Full-screen rehearsal runner that records per-slide seconds."""

    finishedRun = Signal(list)     # list[float] seconds per slide
    closed = Signal()

    BG = QColor("#000000")

    def __init__(self, deck, start: int = 0, parent=None):
        super().__init__(parent)
        self._deck = deck
        self._idx = 0
        self._pix: dict[int, object] = {}
        self._dead = False
        self._now = time.monotonic          # injectable clock for tests
        self._t0 = self._now()              # slide entered
        self._run_t0 = self._now()          # rehearsal started
        self._secs = [0.0] * len(deck.slides)

        self.setWindowTitle("Rehearse timings — Slideshow Studio")

        # big centred slide image
        self.screen = QLabel(self)
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setStyleSheet("background: #000; border: none;")

        # top-left: position, top-right: total
        self.pos_label = QLabel(self)
        self.pos_label.setStyleSheet(
            "color: rgba(255,255,255,200); background: rgba(0,0,0,110);"
            "border-radius: 8px; padding: 6px 14px; font-size: 14px;")
        # top-center: the big stopwatch for the current slide
        self.clock_label = QLabel(self)
        self.clock_label.setStyleSheet(
            "color: #ffffff; background: rgba(10,14,20,200);"
            "border: 1px solid rgba(255,255,255,40);"
            "border-radius: 10px; padding: 8px 22px; font-size: 30px;")
        # bottom hint
        self.hint = QLabel(self)
        self.hint.setText("←/→ navigate · Space next · F fullscreen · "
                          "Esc finish & apply")
        self.hint.setStyleSheet(
            "color: rgba(255,255,255,170); background: rgba(0,0,0,110);"
            "border-radius: 8px; padding: 4px 12px; font-size: 12px;")

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._update_clock)
        self._timer.start()

        self._wire_keys()
        self._update_labels()
        self._update_clock()
        self.go_to(max(0, min(start, len(deck.slides) - 1)))

    # ------------------------------------------------------------------ #
    # setup helpers
    # ------------------------------------------------------------------ #
    def _wire_keys(self) -> None:
        for seq, fn in (
                (QKeySequence(Qt.Key.Key_Right), self.go_next),
                (QKeySequence(Qt.Key.Key_Space), self.go_next),
                (QKeySequence(Qt.Key.Key_PageDown), self.go_next),
                (QKeySequence(Qt.Key.Key_Enter), self.go_next),
                (QKeySequence(Qt.Key.Key_Return), self.go_next),
                (QKeySequence(Qt.Key.Key_Left), self.go_prev),
                (QKeySequence(Qt.Key.Key_PageUp), self.go_prev),
                (QKeySequence(Qt.Key.Key_Backspace), self.go_prev),
                (QKeySequence(Qt.Key.Key_Home), lambda: self.go_to(0)),
                (QKeySequence(Qt.Key.Key_End),
                 lambda: self.go_to(len(self._deck.slides) - 1)),
                (QKeySequence(Qt.Key.Key_Escape), self.finish),
                (QKeySequence("F"), self._toggle_fullscreen)):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(fn)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def index(self) -> int:
        return self._idx

    def total(self) -> int:
        return len(self._deck.slides)

    def timings(self) -> list[float]:
        """Recorded seconds per slide (rehearsed time adds up)."""
        return list(self._secs)

    def total_elapsed(self) -> float:
        return max(0.0, self._now() - self._run_t0)

    def go_next(self) -> None:
        self.go_to(self._idx + 1)

    def go_prev(self) -> None:
        self.go_to(self._idx - 1)

    def go_to(self, idx: int) -> None:
        n = len(self._deck.slides)
        if n == 0:
            return
        idx = max(0, min(idx, n - 1))     # clamped: no wrap, ends hold
        if idx == self._idx and self._pix.get(idx) is not None:
            return
        self._book(self._idx)             # bank the time spent leaving
        self._idx = idx
        self._t0 = self._now()
        self._show_slide()
        self._update_labels()

    def finish(self) -> None:
        """Bank the current slide's time and report the run."""
        self._book(self._idx)
        self.finishedRun.emit(self.timings())
        self.close()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _book(self, idx: int) -> None:
        """Add the time spent on slide ``idx`` since it was shown."""
        if 0 <= idx < len(self._secs):
            self._secs[idx] += max(0.0, self._now() - self._t0)
        self._t0 = self._now()

    def _slide(self):
        if 0 <= self._idx < len(self._deck.slides):
            return self._deck.slides[self._idx]
        return None

    def _show_slide(self) -> None:
        if self._slide() is None:
            return
        self._render_pix()

    def _render_pix(self) -> None:
        if self._idx not in self._pix:
            self._pix[self._idx] = render_slide(
                self._slide(), self._deck.theme, BASE_W, BASE_H)
        img = self._pix[self._idx]
        w = max(200, self.width())
        h = max(112, self.height())
        m = 4
        pmw = w - m * 2
        pmh = int(pmw * BASE_H / BASE_W)
        if pmh > h - m * 2:
            pmh = h - m * 2
            pmw = int(pmh * BASE_W / BASE_H)
        self.screen.setGeometry((w - pmw) // 2, (h - pmh) // 2, pmw, pmh)
        self.screen.setPixmap(QPixmap.fromImage(img).scaled(
            self.screen.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _update_labels(self) -> None:
        self.pos_label.setText(
            f"REHEARSING · SLIDE {self._idx + 1}/{self.total()}")

    def _update_clock(self) -> None:
        if self._dead:
            return
        self.clock_label.setText(mmss(self.elapsed_slide_seconds()))
        self.clock_label.adjustSize()
        self.clock_label.move(
            (max(200, self.width()) - self.clock_label.width()) // 2, 14)

    def elapsed_slide_seconds(self) -> float:
        """Seconds the current slide has been on screen (unbanked)."""
        return max(0.0, self._now() - self._t0)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _reposition_overlays(self) -> None:
        w, h = max(200, self.width()), max(112, self.height())
        self.pos_label.adjustSize()
        self.pos_label.move(18, 16)
        self.clock_label.adjustSize()
        self.clock_label.move((w - self.clock_label.width()) // 2, 14)
        self.hint.adjustSize()
        self.hint.move(w - self.hint.width() - 18,
                       h - self.hint.height() - 14)

    # ------------------------------------------------------------------ #
    # Qt events
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() < self.width() / 4.0:
                self.go_prev()
            else:
                self.go_next()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.finish()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._render_pix()
        self._reposition_overlays()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        QTimer.singleShot(0, self._relayout)
        super().showEvent(event)

    def _relayout(self) -> None:
        if not self._dead:
            self._render_pix()
            self._reposition_overlays()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self.BG)
        p.end()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._dead = True
        self._timer.stop()
        self.closed.emit()
        super().closeEvent(event)
