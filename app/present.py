"""Full-screen presentation mode: run the deck like a talk.

Renders every slide through the shared painter, plays the slide's TTS
narration through the speakers and auto-advances when the narration ends
(when auto-advance is on).  Keys:

    Right / Space / PgDown / click   next slide
    Left / PgUp                      previous slide
    Home / End                       first / last slide
    S                                toggle narration subtitles
    N                                toggle the presenter notes panel
                                     (speaker notes + slide clock)
    A                                toggle auto-advance
    Esc                              exit
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QLabel, QWidget

from .render import BASE_W, BASE_H, render_slide


class _SynthOne(QThread):
    """Synthesize one slide's narration in the background (cached)."""
    ok = Signal(str)
    err = Signal(str)

    def __init__(self, slide, deck, parent=None):
        super().__init__(parent)
        self.slide = slide
        self.deck = deck

    def run(self) -> None:
        from . import tts
        try:
            self.ok.emit(tts.synthesize_cached(self.slide, self.deck))
        except RuntimeError as exc:
            self.err.emit(str(exc))


# Synth threads that outlive the slide they were started for (navigation
# moved on, or the window closed).  They must NOT be destroyed while
# running, so they are parked here until they finish.
_orphan_synths: set = set()


def mmss(seconds: float) -> str:
    """Seconds as m:ss (module-level so other windows can reuse it)."""
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class PresentWindow(QWidget):
    closed = Signal()
    slideChanged = Signal(int)

    BG = QColor("#000000")

    def __init__(self, deck, start: int = 0, auto_advance: bool = True,
                 show_subtitles: bool = False, parent=None):
        super().__init__(parent)
        self._deck = deck
        self._idx = 0
        self._auto = bool(auto_advance)
        self._subs = bool(show_subtitles)
        self._pix: dict[int, object] = {}      # index -> QImage
        self._player = None
        self._audio = None
        self._synth: _SynthOne | None = None
        self._dead = False

        self.setWindowTitle("Presenting — Slideshow Studio")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # big centred slide image
        self.screen = QLabel(self)
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setStyleSheet("background: #000; border: none;")

        # narration subtitles
        self.sub_label = QLabel(self)
        self.sub_label.setWordWrap(True)
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignHCenter |
                                    Qt.AlignmentFlag.AlignTop)
        self.sub_label.setStyleSheet(
            "color: #ffffff; background: rgba(0,0,0,150);"
            "border-radius: 8px; padding: 8px 18px; font-size: 15px;")

        # bottom-right hints
        self.hint = QLabel(self)
        self.hint.setText("←/→ navigate · Space next · S subtitles · "
                          "N notes · A auto-advance · Esc exit")
        self.hint.setStyleSheet(
            "color: rgba(255,255,255,170); background: rgba(0,0,0,110);"
            "border-radius: 8px; padding: 4px 12px; font-size: 12px;")

        # presenter notes panel (toggle with N): speaker notes + clock
        self._notes = False
        self._now = time.monotonic          # injectable clock for tests
        self._slide_t0 = self._now()
        self.notes_label = QLabel(self)
        self.notes_label.setWordWrap(True)
        self.notes_label.setAlignment(Qt.AlignmentFlag.AlignLeft |
                                      Qt.AlignmentFlag.AlignTop)
        self.notes_label.setTextFormat(Qt.TextFormat.RichText)
        self.notes_label.setStyleSheet(
            "color: #e8eef4; background: rgba(10,14,20,215);"
            "border: 1px solid rgba(255,255,255,40);"
            "border-radius: 10px; padding: 12px 16px; font-size: 15px;")
        self.notes_label.setVisible(False)
        self._notes_timer = QTimer(self)
        self._notes_timer.setInterval(500)
        self._notes_timer.timeout.connect(self._update_notes)

        self._build_audio()
        self._wire_keys()
        self.go_to(max(0, min(start, len(deck.slides) - 1)))

    # ------------------------------------------------------------------ #
    # setup helpers
    # ------------------------------------------------------------------ #
    def _build_audio(self) -> None:
        try:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._audio.setVolume(1.0)
            self._player.mediaStatusChanged.connect(self._on_media_status)
        except Exception:
            self._player = None      # present silently without audio

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
                (QKeySequence(Qt.Key.Key_Escape), self.close),
                (QKeySequence(Qt.Key.Key_S), self._toggle_subs),
                (QKeySequence(Qt.Key.Key_N), self._toggle_notes),
                (QKeySequence(Qt.Key.Key_A), self._toggle_auto),
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

    def is_auto_advance(self) -> bool:
        return self._auto

    def is_showing_subtitles(self) -> bool:
        return self._subs

    def is_showing_notes(self) -> bool:
        return self._notes

    def notes_text(self) -> str:
        """Speaker notes of the current slide (what the panel shows)."""
        slide = self._slide()
        if slide is None:
            return ""
        return (slide.narration or "").strip() or \
            slide.effective_narration().strip()

    def elapsed_slide_seconds(self) -> float:
        """Seconds the current slide has been on screen."""
        return max(0.0, self._now() - self._slide_t0)

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
        self._idx = idx
        self.slideChanged.emit(idx)
        self._show_slide()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _slide(self):
        if 0 <= self._idx < len(self._deck.slides):
            return self._deck.slides[self._idx]
        return None

    def _show_slide(self) -> None:
        slide = self._slide()
        if slide is None:
            return
        self._slide_t0 = self._now()
        self._stop_synth()
        self._render_pix()
        self._update_subtitles()
        self._update_notes()
        self._play_narration(slide)

    def _render_pix(self) -> None:
        if self._idx not in self._pix:
            self._pix[self._idx] = render_slide(
                self._slide(), self._deck.theme, BASE_W, BASE_H)
        img = self._pix[self._idx]
        w = max(200, self.width())
        h = max(112, self.height())
        m = 4                                  # tiny letterbox margin
        pmw = w - m * 2
        pmh = int(pmw * BASE_H / BASE_W)
        if pmh > h - m * 2:
            pmh = h - m * 2
            pmw = int(pmh * BASE_W / BASE_H)
        self.screen.setGeometry((w - pmw) // 2, (h - pmh) // 2, pmw, pmh)
        self.screen.setPixmap(QPixmap.fromImage(img).scaled(
            self.screen.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _update_subtitles(self) -> None:
        slide = self._slide()
        text = (slide.effective_narration() if slide else "").strip()
        if self._subs and text:
            self.sub_label.setText(text)
            self.sub_label.setVisible(True)
            self._place_subtitles()
        else:
            self.sub_label.setVisible(False)

    def _place_subtitles(self) -> None:
        w = self.width()
        self.sub_label.setFixedWidth(min(1100, w - 160))
        self.sub_label.adjustSize()
        self.sub_label.move((w - self.sub_label.width()) // 2,
                            self.height() - self.sub_label.height() - 46)

    def _reposition_hint(self) -> None:
        self.hint.adjustSize()
        self.hint.move(self.width() - self.hint.width() - 18,
                       self.height() - self.hint.height() - 14)

    def _play_narration(self, slide) -> None:
        text = (slide.effective_narration() or "").strip()
        if not text or self._player is None:
            return
        self._stop_synth()
        self._synth = _SynthOne(slide, self._deck, None)
        self._synth.ok.connect(self._on_synth_ok)
        self._synth.err.connect(lambda _m: None)   # present silently
        self._synth.start()

    def _stop_synth(self) -> None:
        t = self._synth
        self._synth = None
        if t is None:
            return
        try:
            if t.isRunning():
                # park the thread so it is never destroyed while running
                for sig in ("ok", "err"):
                    try:
                        getattr(t, sig).disconnect()
                    except (RuntimeError, TypeError):
                        pass
                t.finished.connect(lambda th=t: _orphan_synths.discard(th))
                _orphan_synths.add(t)
        except RuntimeError:
            pass

    def _on_synth_ok(self, path: str) -> None:
        if self._dead or self._player is None or not os.path.isfile(path):
            return
        try:
            self._player.stop()
            self._player.setSource(
                QUrl_from_local(os.path.abspath(path)))
            self._player.play()
        except RuntimeError:
            pass

    def _on_media_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer as QMP
        if self._dead or status != QMP.MediaStatus.EndOfMedia:
            return
        if self._auto and self._idx < self.total() - 1:
            self.go_next()

    def _toggle_subs(self) -> None:
        self._subs = not self._subs
        self._update_subtitles()

    # ------------------------------------------------------------------ #
    # presenter notes
    # ------------------------------------------------------------------ #
    def _toggle_notes(self) -> None:
        self._notes = not self._notes
        self._update_notes()

    @staticmethod
    def _mmss(seconds: float) -> str:
        return mmss(seconds)

    def _update_notes(self) -> None:
        if not self._notes:
            self.notes_label.setVisible(False)
            self._notes_timer.stop()
            return
        text = self.notes_text()
        head = (f"<span style='color:#9fb0c0;font-size:12px;'>"
                f"NOTES · SLIDE {self._idx + 1}/{self.total()} · "
                f"{self._mmss(self.elapsed_slide_seconds())}</span>")
        body = text.replace("&", "&amp;").replace("<", "&lt;") \
            .replace(">", "&gt;") if text else \
            "<i style='color:#8a97a5;'>No speaker notes on this slide.</i>"
        self.notes_label.setText(head + "<br>" + body)
        self.notes_label.setVisible(True)
        self._place_notes()
        if not self._notes_timer.isActive():
            self._notes_timer.start()

    def _place_notes(self) -> None:
        w = max(200, self.width())
        h = max(112, self.height())
        self.notes_label.setFixedWidth(max(280, min(560, int(w * 0.42))))
        self.notes_label.adjustSize()
        self.notes_label.move(18, h - self.notes_label.height() - 18)

    def _toggle_auto(self) -> None:
        self._auto = not self._auto

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

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
        # fallback for platforms where QShortcut misses the key
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._render_pix()
        if self.sub_label.isVisible():
            self._place_subtitles()
        if self.notes_label.isVisible():
            self._place_notes()
        self._reposition_hint()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        # re-anchor the floating labels once the final window geometry is
        # known (offscreen/WM resize timing can beat the constructor)
        QTimer.singleShot(0, self._relayout_overlays)
        super().showEvent(event)

    def _relayout_overlays(self) -> None:
        if self._dead:
            return
        self._render_pix()
        if self.sub_label.isVisible():
            self._place_subtitles()
        if self.notes_label.isVisible():
            self._place_notes()
        self._reposition_hint()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self.BG)
        p.end()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._dead = True
        self._notes_timer.stop()
        self._stop_synth()
        if self._player:
            try:
                self._player.stop()
            except RuntimeError:
                pass
        self.closed.emit()
        super().closeEvent(event)


def QUrl_from_local(path: str):
    from PySide6.QtCore import QUrl
    return QUrl.fromLocalFile(path)
