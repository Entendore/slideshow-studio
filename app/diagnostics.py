"""Diagnostics report: environment, tools, engines, storage, deck state.

Shown via Help ▸ Diagnostics… (non-modal dialog with a copy-to-clipboard
button, handy for bug reports). The data collector is pure Python so tests
can assert on it without a QApplication.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys

from PySide6.QtWidgets import QDialog

from . import APP_VERSION, folders, media, memory, paths, tts, workspace

# on Windows keep console-less subprocess calls quiet
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #
def _dir_stats(path: str, recursive: bool = True) -> tuple[int, str]:
    """(file count, human size) for a directory; (0, '—') when missing."""
    if not os.path.isdir(path):
        return 0, "—"
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
                count += 1
            except OSError:
                pass
    if total < 1024:
        return count, f"{total} B"
    if total < 1024 * 1024:
        return count, f"{total / 1024:.1f} KB"
    return count, f"{total / (1024 * 1024):.1f} MB"


def _module_version(distro: str, module: str) -> str:
    try:
        importlib.import_module(module)
        return importlib.metadata.version(distro)
    except Exception:
        return "not installed"


def _first_line(cmd: list[str]) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=6,
            creationflags=_CREATE_NO_WINDOW)
        for line in (out.stdout or "").splitlines():
            if line.strip():
                return line.split(" Copyright")[0].strip()
    except Exception:
        pass
    return "—"


def _human_bytes(n: float) -> str:
    if n <= 0:
        return "0 B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _edge_voice_count() -> int:
    try:
        cached = tts._read_cache()
        return len(cached) if cached else 0
    except Exception:
        return 0


# ------------------------------------------------------------------ #
# data collection
# ------------------------------------------------------------------ #
def collect_info(deck=None) -> list[tuple[str, list[tuple[str, str]]]]:
    """Ordered sections of (label, value) pairs describing this install."""
    ffmpeg = media.ffmpeg_path()
    ffprobe = media.ffprobe_path()
    soffice = (shutil.which("soffice") or shutil.which("soffice.bin")
               or "not installed (legacy .ppt import disabled)")

    narr_cache = workspace.narr_cache_dir()
    n_cache, s_cache = _dir_stats(narr_cache)
    ws_dir = workspace.workspace_dir()
    n_ws, s_ws = _dir_stats(ws_dir)
    out_dir = paths.output_dir(create=False)
    n_out, s_out = _dir_stats(out_dir)
    custom_out = folders.output_root(create=False)
    n_custom, s_custom = _dir_stats(custom_out)
    inp_dir = folders.input_dir()
    n_inp, s_inp = _dir_stats(inp_dir)
    tmp_dir = folders.temp_dir()
    n_tmp, s_tmp = _dir_stats(tmp_dir)
    n_ex = len(paths.list_examples())
    autosave = workspace.autosave_path()

    qwen_key = tts.get_qwen_api_key()
    edge_vers = _module_version("edge-tts", "edge_tts")
    piper_vers = _module_version("piper-tts", "piper")

    sections: list[tuple[str, list[tuple[str, str]]]] = [
        ("Application", [
            ("Version", APP_VERSION),
            ("App folder", paths.app_dir()),
        ]),
        ("Environment", [
            ("Python", sys.version.split()[0]),
            ("Qt", _qt_version()),
            ("PySide6", _pyside_version()),
            ("Platform", platform.platform()),
            ("Display backend",
             os.environ.get("QT_QPA_PLATFORM") or "desktop default"),
        ]),
        ("Media tools", [
            ("ffmpeg", ffmpeg or "NOT FOUND — MP4/audio export disabled"),
            ("ffmpeg version",
             _first_line([ffmpeg, "-version"]) if ffmpeg else "—"),
            ("ffprobe", ffprobe or "missing (fallback probing used)"),
            ("LibreOffice", soffice),
        ]),
        ("Speech engines", [
            ("edge-tts (online)", edge_vers),
            ("Edge voices cached", str(_edge_voice_count())),
            ("piper-tts (offline)", piper_vers),
            ("Piper voices downloaded",
             str(tts.piper_installed_count())),
            ("Qwen TTS key",
             "configured" if qwen_key else "not set (engine disabled)"),
            ("Qwen endpoint", tts.get_qwen_region()),
        ]),
        ("Storage", [
            ("Workspace", f"{ws_dir}  ({n_ws} files, {s_ws})"),
            ("Narration cache", f"{narr_cache}  ({n_cache} files, {s_cache})"),
            ("Voice models", f"{tts.piper_installed_count()} of "
             f"{len(tts.PIPER_VOICES)} Piper voices "
             f"({_human_bytes(tts.piper_total_size())})"),
            ("Autosave", "present" if os.path.isfile(autosave)
             else "none yet"),
            ("Session snapshot", "present (Tools ▸ Reopen last session)"
             if memory.session_info() else "none yet"),
            ("Reopen at startup",
             "on" if memory.reopen_last_enabled() else "off"),
        ]),
        ("Folders", [
            ("Input folder", f"{inp_dir}  ({n_inp} files, {s_inp})"
             if inp_dir else
             "not configured — dialogs open where you last browsed"),
            ("Output folder",
             f"{custom_out}  ({n_custom} files, {s_custom})"
             if not folders.using_default_output() else
             f"{out_dir}  ({n_out} files, {s_out})  (bundled default)"),
            ("Output layout", folders.LAYOUT_LABELS[folders.output_layout()]
             + ("" if not folders.using_default_output()
                else "  (layout applies to a custom output folder)")),
            ("Working (temp) folder",
             f"{tmp_dir}  ({n_tmp} files, {s_tmp})  "
             f"[{folders.temp_source()}]"
             + (f"  — fallback: {folders.temp_fallback_reason()}"
                if folders.temp_fallback_reason() else "")),
            ("Recent folders", str(len(folders.recent_folders(all=True)))),
            ("Examples", f"{paths.examples_dir()}  ({n_ex} decks)"),
        ]),
    ]

    if deck is not None:
        narrated = sum(1 for s in deck.slides if s.narration)
        moving = sum(1 for s in deck.slides if s.motion != "none")
        html_bodies = sum(1 for s in deck.slides
                          if s.body_format == "html")
        with_imgs = sum(1 for s in deck.slides if s.image)
        engine = tts.engine_of(deck.default_voice.voice)
        overlays = [n for n, on in (
            ("slide numbers", deck.overlay_slide_numbers),
            ("progress bar", deck.overlay_progress),
            ("watermark", bool(deck.watermark_text)),
        ) if on]
        sections.append(("Current deck", [
            ("Name", deck.name or "Untitled"),
            ("Slides", str(len(deck.slides))),
            ("Narrations written", f"{narrated} / {len(deck.slides)}"),
            ("Slides with motion", str(moving)),
            ("Per-slide transition overrides",
             str(sum(1 for s in deck.slides if s.transition))),
            ("Minimum durations set",
             str(sum(1 for s in deck.slides
                     if s.duration_override > 0))),
            ("Rich-text bodies", str(html_bodies)),
            ("Background images", str(with_imgs)),
            ("Default engine / voice",
             f"{engine} · {tts.bare_voice_name(deck.default_voice.voice)}"),
            ("Overlays", ", ".join(overlays) or "none"),
            ("Music track", deck.music_path or "none"),
            ("Project file", deck.project_path or "unsaved"),
        ]))
    return sections


def _qt_version() -> str:
    try:
        from PySide6.QtCore import qVersion
        return qVersion()
    except Exception:
        return "—"


def _pyside_version() -> str:
    try:
        import PySide6
        return PySide6.__version__
    except Exception:
        return "—"


def format_report(sections) -> str:
    """Plain-text rendering of collect_info() output."""
    lines = [f"Slideshow Studio {APP_VERSION} — diagnostics",
             "=" * (24 + len(APP_VERSION))]
    for title, rows in sections:
        lines.append("")
        lines.append(f"[{title}]")
        width = max((len(k) for k, _v in rows), default=0)
        for k, v in rows:
            lines.append(f"  {k.ljust(width)} : {v}")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# dialog
# ------------------------------------------------------------------ #
def build_dialog(deck=None, parent=None):
    """Create the diagnostics dialog (kept as a stable factory entry)."""
    return DiagnosticsDialog(deck, parent)


class DiagnosticsDialog(QDialog):
    """Non-modal report window; `refresh(deck)` re-collects everything."""

    def __init__(self, deck=None, parent=None):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import (QHBoxLayout, QPlainTextEdit,
                                       QPushButton, QVBoxLayout)
        super().__init__(parent)
        self.setWindowTitle("Diagnostics — Slideshow Studio")
        self.setModal(False)
        self.resize(680, 560)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.text.setFont(font)
        lay.addWidget(self.text, 1)
        self.refresh(deck)

        btns = QHBoxLayout()

        btn_copy = QPushButton("Copy report")
        btn_copy.setToolTip("Copy the full diagnostics text to the "
                            "clipboard — paste it into a bug report")
        btn_copy.clicked.connect(self._copy)
        btns.addWidget(btn_copy)

        btn_ws = QPushButton("Open workspace folder")
        btn_ws.clicked.connect(lambda: self._open(
            workspace.workspace_dir()))
        btns.addWidget(btn_ws)

        btn_out = QPushButton("Open output folder")
        btn_out.clicked.connect(
            lambda: self._open(paths.output_dir()))
        btns.addWidget(btn_out)

        btn_tmp = QPushButton("Open temp folder")
        btn_tmp.setToolTip("Show the working folder that holds the "
                           "temporary render files")
        btn_tmp.clicked.connect(lambda: self._open(folders.temp_dir()))
        btns.addWidget(btn_tmp)

        btns.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

    # ---------------------------------------------------------------- #
    def refresh(self, deck=None) -> None:
        self.text.setPlainText(format_report(collect_info(deck)))

    def _open(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self.text.toPlainText())
        # main window status bar, when parented to one
        bar = getattr(self.parent(), "statusBar", None)
        if callable(bar):
            try:
                self.parent().statusBar().showMessage(
                    "Diagnostics report copied to the clipboard.", 4000)
            except Exception:
                pass
