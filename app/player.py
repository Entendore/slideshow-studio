"""In-app preview playback: slides shown in sync with their TTS narration.

Narration files are synthesized in a background thread (cached), then a
QMediaPlayer walks the deck slide by slide.  The player also publishes
playback position + the current narration file so the main window can
render a live audio waveform under the canvas (click to seek).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QMessageBox

from . import tts


class _SynthAllThread(QThread):
    """Pre-synthesize every slide's narration (skips cached ones)."""
    progress = Signal(int, int)      # done, total
    finished_ok = Signal()
    error = Signal(str)

    def __init__(self, deck, parent=None):
        super().__init__(parent)
        self.deck = deck
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        slides = [s for s in self.deck.slides if s.effective_narration().strip()]
        total = len(slides)
        for i, slide in enumerate(slides):
            if self._stop:
                return
            try:
                tts.synthesize_cached(slide, self.deck)
            except RuntimeError as exc:
                self.error.emit(f"Slide {i + 1}: {exc}")
                return
            self.progress.emit(i + 1, total)
        self.finished_ok.emit()


class PreviewPlayer(QObject):
    stateChanged = Signal(bool)          # playing
    slideEntered = Signal(int)           # index of the slide now showing
    status = Signal(str)
    positionChanged = Signal(int, int)   # position ms, duration ms
    narrationChanged = Signal(str)       # narration file now playing ("")

    def __init__(self, window):
        super().__init__(window)
        self._win = window
        self._deck = None
        self._playing = False
        self._paused = False
        self._idx = 0
        self._player: QMediaPlayer | None = None
        self._audio: QAudioOutput | None = None
        self._synth: _SynthAllThread | None = None
        self._single_mode = False
        self._dur = 0                     # current media duration (ms)

    # ------------------------------------------------------------------ #
    def is_playing(self) -> bool:
        return self._playing

    def toggle_pause(self) -> None:
        """Pause / resume the current narration playback."""
        if not self._playing or self._player is None:
            return
        try:
            if self._paused:
                self._player.play()
                self._paused = False
                self.status.emit("Playback resumed.")
            else:
                self._player.pause()
                self._paused = True
                self.status.emit("Playback paused.")
        except RuntimeError:
            pass

    def is_paused(self) -> bool:
        return self._paused

    def play_deck(self, deck) -> None:
        """Play the whole deck from the current slide."""
        if not deck.slides:
            QMessageBox.information(self._win, "Nothing to play",
                                    "The deck has no slides.")
            return
        self._deck = deck
        self._single_mode = False
        self._idx = max(0, self._win.current_index())
        self._prepare()

    def play_current(self, deck) -> None:
        if not deck.slides:
            return
        self._deck = deck
        self._single_mode = True
        self._idx = max(0, self._win.current_index())
        self._prepare()

    def stop(self) -> None:
        self._playing = False
        self._paused = False
        self._dur = 0
        if self._player:
            try:
                self._player.stop()
            except RuntimeError:
                pass
        if self._synth and self._synth.isRunning():
            self._synth.stop()
        self.stateChanged.emit(False)
        self.status.emit("Playback stopped.")

    # ------------------------------------------------------------------ #
    def _prepare(self) -> None:
        if self._playing:
            self.stop()
        self.status.emit("Synthesizing narration (cached where possible) …")
        self._synth = _SynthAllThread(self._deck, self)
        self._synth.progress.connect(
            lambda d, t: self.status.emit(f"Synthesizing narration {d}/{t} …"))
        self._synth.error.connect(self._synth_error)
        self._synth.finished_ok.connect(self._begin)
        self._synth.start()

    def _synth_error(self, msg: str) -> None:
        self._playing = False
        self.stateChanged.emit(False)
        self.status.emit("Playback failed.")
        QMessageBox.warning(self._win, "TTS failed", msg)

    def _begin(self) -> None:
        if not self._deck or not self._deck.slides:
            return
        try:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._audio.setVolume(1.0)
            self._player.mediaStatusChanged.connect(self._on_status)
            self._player.positionChanged.connect(self._on_position)
            self._player.durationChanged.connect(self._on_duration)
        except Exception as exc:
            QMessageBox.warning(self._win, "Playback unavailable",
                                f"Audio playback could not start: {exc}")
            return
        self._paused = False
        self._playing = True
        self._dur = 0
        self.stateChanged.emit(True)
        self._enter(self._idx)

    def _enter(self, idx: int) -> None:
        if not self._playing:
            return
        n = len(self._deck.slides)
        if idx >= n:
            if self._single_mode:
                self.stop()
                return
            self.status.emit("Playback finished.")
            self.stop()
            return
        self._idx = idx
        self.slideEntered.emit(idx)
        slide = self._deck.slides[idx]
        text = slide.effective_narration()
        if text.strip():
            try:
                path = tts.synthesize_cached(slide, self._deck)
            except RuntimeError as exc:
                self._synth_error(str(exc))
                return
            self._paused = False
            self.narrationChanged.emit(path)
            self._player.setSource(_url(path))
            self._player.play()
            self.status.emit(
                f"Playing slide {idx + 1}/{n} — {slide.title or '(untitled)'}")
        else:
            self.narrationChanged.emit("")
            self.status.emit(f"Slide {idx + 1}/{n} has no narration — skipped.")
            self._enter(idx + 1)

    def _on_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer as QMP
        if not self._playing or self._player is None:
            return
        if status == QMP.MediaStatus.EndOfMedia:
            nxt = self._idx + 1
            if self._single_mode:
                self.stop()
            else:
                self._enter(nxt)

    # ------------------------------------------------------------------ #
    # position / seeking (used by the waveform strip)
    # ------------------------------------------------------------------ #
    def _on_position(self, pos: int) -> None:
        self.positionChanged.emit(pos, self._dur)

    def _on_duration(self, dur: int) -> None:
        self._dur = max(0, int(dur))
        pos = 0
        if self._player is not None:
            try:
                pos = self._player.position()
            except RuntimeError:
                pos = 0
        self.positionChanged.emit(pos, self._dur)

    def seek_fraction(self, frac: float) -> None:
        """Jump to *frac* (0..1) of the current narration, if playing."""
        frac = max(0.0, min(1.0, frac))
        if self._player is None or self._dur <= 0:
            return
        try:
            self._player.setPosition(int(frac * self._dur))
        except RuntimeError:
            pass


def _url(path: str):
    from PySide6.QtCore import QUrl
    return QUrl.fromLocalFile(os.path.abspath(path))
