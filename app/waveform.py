"""Audio waveform strip for the preview player.

The bar under the canvas shows the loudness shape of the current slide's
narration: mirrored peak bars, the already-played part highlighted, and
click / drag to seek inside the slide's audio.

Peaks are extracted by decoding the narration file to raw mono PCM with
ffmpeg (fast, no temp files — the samples arrive on ffmpeg's stdout) and
bucketed into a fixed number of peak values in 0..1. Extraction runs on
a worker thread so long narrations never block the UI, and stale results
are dropped if the user moves on before the decode finishes.
"""
from __future__ import annotations

import array
import os
import subprocess
import sys

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

BUCKETS = 900               # default resolution of the peak array
_DECODE_RATE = 8000         # decode sample rate (mono s16le)


def compute_peaks(path: str, buckets: int = BUCKETS) -> list[float]:
    """Decode *path* and return *buckets* peak amplitudes in 0..1.

    Raises FileNotFoundError when ffmpeg is missing and RuntimeError when
    ffmpeg cannot decode the file (bad/missing audio, unsupported file).
    """
    if buckets < 1:
        raise ValueError("buckets must be >= 1")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1",
         "-ar", str(_DECODE_RATE), "-f", "s16le", "-"],
        capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg could not decode {os.path.basename(path)}: "
            + proc.stderr.decode("utf-8", "replace").strip()[:160])
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    n = len(samples)
    peaks: list[float] = []
    step = n / buckets
    for i in range(buckets):
        a = int(i * step)
        b = max(a + 1, int((i + 1) * step))
        seg = samples[a:b]
        peaks.append((max(abs(s) for s in seg) / 32768.0) if seg else 0.0)
    return peaks


class WaveformLoader(QThread):
    """Decodes narration files to peak arrays, one request at a time.

    ``load(path)`` supersedes any running request: the run loop skips
    every result whose path no longer matches the newest request, so a
    burst of slide changes cannot flood the UI with stale waveforms.
    ``load("")`` cancels silently.
    """

    loaded = Signal(str, list)      # path, peaks
    failed = Signal(str, str)       # path, error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._want = ""
        self._gen = 0                # bumps on every load() request

    def load(self, path: str) -> None:
        self._want = path or ""
        self._gen += 1
        if not self.isRunning():
            self.start()

    def cancel(self) -> None:
        """Stop accepting work; an in-flight decode is left to finish."""
        self._want = ""

    def run(self) -> None:  # noqa: N802
        seen = 0
        while seen != self._gen:
            seen = self._gen
            path = self._want
            if not path:
                continue
            try:
                peaks = compute_peaks(path)
            except Exception as exc:      # noqa: BLE001 — reported to UI
                self.failed.emit(path, str(exc))
            else:
                self.loaded.emit(path, peaks)


class WaveformBar(QWidget):
    """Clickable loudness strip: peaks + playhead, themed via tokens."""

    seekRequested = Signal(float)     # fraction 0..1 within the audio

    HEIGHT = 64
    BAR_GAP = 1.0                     # px between bars

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: list[float] | None = None
        self._path = ""               # path the shown data belongs to
        self._pending = ""            # path a loader is working on
        self._frac = 0.0              # playhead 0..1
        self._playing = False
        self._msg = ""
        self._pressed = False
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Narration waveform — click or drag to seek")
        self._loader = WaveformLoader(self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def show_path(self, path: str, message: str = "") -> None:
        """Load + display the waveform of an audio file (async)."""
        path = path or ""
        if not path:
            self.set_message(message or "No narration on this slide")
            return
        if path == self._path and self._peaks is not None:
            self._frac = 0.0
            self.update()
            return
        if path == self._pending:
            return                     # already loading this file
        self._peaks = None
        self._path = path
        self._pending = path
        self._frac = 0.0
        self._msg = message or "Loading waveform …"
        self.update()
        self._loader.load(path)

    def set_message(self, text: str) -> None:
        """Show a hint instead of a waveform (clears any data)."""
        self._peaks = None
        self._path = ""
        self._pending = ""
        self._msg = text
        self._frac = 0.0
        self.update()

    def set_peaks(self, peaks: list[float], frac: float = 0.0) -> None:
        """Directly install peak data (no file attached)."""
        self._peaks = list(peaks) if peaks else None
        self._path = ""
        self._pending = ""
        self._msg = ""
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def set_progress(self, frac: float) -> None:
        """Move the playhead to *frac* (0..1) of the shown audio."""
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.update()

    def shutdown(self) -> None:
        """Stop the loader thread (called from the main window on close)."""
        self._loader.cancel()
        if self._loader.isRunning():
            self._loader.wait(3000)

    # ------------------------------------------------------------------ #
    # loader callbacks
    # ------------------------------------------------------------------ #
    def _on_loaded(self, path: str, peaks: list) -> None:
        if path != self._pending:
            return                     # stale result, user moved on
        self._peaks = list(peaks)
        self._pending = ""
        self._msg = ""
        self.update()

    def _on_failed(self, path: str, err: str) -> None:
        if path != self._pending:
            return
        self._peaks = None
        self._pending = ""
        self._msg = f"Waveform unavailable — {err}"
        self.update()

    # ------------------------------------------------------------------ #
    # painting
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802
        from . import styles
        t = styles.tokens()
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        bg = QColor(t["elevated"])
        p.setPen(QColor(t["border"]))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        if not self._peaks:
            self._paint_hint(p, w, h, t)
            p.end()
            return

        peaks = self._peaks
        n = len(peaks)
        mid = h / 2.0
        peak_max = max(peaks) or 1.0
        usable = w - 12                       # 6 px inner padding
        bar_w = max(1.0, usable / n - self.BAR_GAP)
        played_x = 6 + self._frac * usable

        played = QColor(t["accent"])
        idle = QColor(t["icon_dim"])
        idle.setAlpha(150)
        pen_played = QPen(played, 1)
        pen_idle = QPen(idle, 1)
        for i, v in enumerate(peaks):
            x = 6 + i * (bar_w + self.BAR_GAP)
            if x > w - 6:
                break
            amp = (v / peak_max) if peak_max > 0 else 0.0
            bh = max(1.5, amp * (h * 0.40))
            p.setPen(pen_played if x + bar_w * 0.5 <= played_x else pen_idle)
            p.drawLine(int(x), int(mid - bh), int(x), int(mid + bh))

        # playhead cursor
        p.setPen(QPen(QColor(t["text"]) if not self._playing
                      else QColor(t["accent_hover"]), 1))
        p.drawLine(int(played_x), 4, int(played_x), h - 4)
        p.end()

    def _paint_hint(self, p: QPainter, w: int, h: int, t: dict) -> None:
        p.setPen(QColor(t["text_dim"]))
        f = self.font()
        f.setPointSize(9)
        p.setFont(f)
        msg = self._msg or "Narration waveform"
        p.drawText(QRectF(6, 0, w - 12, h),
                   Qt.AlignmentFlag.AlignCenter, msg)

    # ------------------------------------------------------------------ #
    # interaction: click / drag to seek
    # ------------------------------------------------------------------ #
    def _frac_at(self, x: float) -> float:
        usable = max(1.0, self.width() - 12)
        return max(0.0, min(1.0, (x - 6) / usable))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and self._peaks):
            self._pressed = True
            frac = self._frac_at(event.position().x())
            self.set_progress(frac)
            self.seekRequested.emit(frac)
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pressed and self._peaks:
            frac = self._frac_at(event.position().x())
            self.set_progress(frac)
            self.seekRequested.emit(frac)
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        event.accept()
