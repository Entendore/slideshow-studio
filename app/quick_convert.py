"""Quick convert: input files -> narrated MP4 videos in one dialog.

The fast lane of the input -> MP4 workflow: pick one or more supported
files (PPTX, PDF, HTML, TXT, MD or a .slideshow project), press Convert,
and every file is imported, its empty narrations are auto-written from the
slide text and a finished MP4 (plus optional .srt subtitles) lands in the
output folder. For fine-grained control use the editor + Export dialog;
for many files at once with every option, use Batch export.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from . import folders, icons, paths, tts, workspace
from .batch_dialog import scan_folder, unique_path
from .export_worker import RESOLUTIONS, TRANSITIONS, ExportOptions, \
    ExportWorker
from .importers import import_file
from .models import Deck, VoiceSettings

PROJECT_EXTS = set(paths.IMPORTABLE_EXTS) | {".slideshow"}

FILE_FILTER = (
    "All supported (*.slideshow *.pptx *.ppt *.pdf *.html *.htm *.txt "
    "*.md *.markdown);;"
    "Slideshow project (*.slideshow);;PowerPoint (*.pptx *.ppt);;"
    "PDF (*.pdf);;HTML (*.html *.htm);;Text (*.txt);;"
    "Markdown (*.md *.markdown)"
)


class QuickConvertDialog(QDialog):
    """One dialog: supported input files in, narrated MP4 files out."""

    exported = Signal(str)          # emitted once per finished MP4

    def __init__(self, parent=None, ffmpeg_ok: bool = True):
        super().__init__(parent)
        self.ffmpeg_ok = ffmpeg_ok
        self.worker: ExportWorker | None = None
        self.settings = QSettings("ZaiStudio", "SlideshowStudio")
        self.setWindowTitle("Quick convert to MP4")
        self.setMinimumWidth(620)
        self.setAcceptDrops(True)

        self._cancel_requested = False
        self._running = False
        self._queue: list[str] = []
        self._current = ""
        self._n_label = ""
        self._total = 0
        self._n_done = 0
        self._ok_count = 0
        self._fail_count = 0
        self._last_out = ""
        self._failures: list[str] = []
        self._out_dir = ""

        self._build()
        self._restore_settings()
        self._sync_convert_enabled()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        head = QLabel("Quick convert — files to MP4")
        head.setProperty("heading", True)
        lay.addWidget(head)

        hint = QLabel(
            "Each file becomes one narrated MP4: the slides are imported, "
            "empty narrations are written from the slide text, and the "
            "video is rendered. For fine control use File ▸ Export; for "
            "every option use Batch export.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # input files -----------------------------------------------------
        files_head = QHBoxLayout()
        files_head.addWidget(QLabel("Input files"))
        files_head.addStretch(1)
        self.btn_add_files = QPushButton("Add files…")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_folder = QPushButton("Add folder…")
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_add_files, self.btn_add_folder, self.btn_remove,
                  self.btn_clear):
            files_head.addWidget(b)
        lay.addLayout(files_head)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setMinimumHeight(96)
        self.file_list.setMaximumHeight(150)
        lay.addWidget(self.file_list)

        # options -----------------------------------------------------------
        row = QHBoxLayout()
        self.voice_combo = QComboBox()
        self._populate_voices()
        self.voice_combo.setToolTip(
            "Voice used for every exported video. “Deck default” keeps "
            "each deck's own voice (en-US-AriaNeural unless changed).")
        row.addWidget(QLabel("Voice"))
        row.addWidget(self.voice_combo, 1)
        self.res_combo = QComboBox()
        self.res_combo.addItems(list(RESOLUTIONS.keys()))
        self.res_combo.setCurrentText("Full HD 1920×1080")
        row.addWidget(QLabel("Resolution"))
        row.addWidget(self.res_combo, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.trans_combo = QComboBox()
        self.trans_combo.addItems(list(TRANSITIONS.keys()))
        self.trans_combo.setCurrentText("None")
        row.addWidget(QLabel("Transition"))
        row.addWidget(self.trans_combo, 1)
        self.trans_dur = QDoubleSpinBox()
        self.trans_dur.setRange(0.2, 2.0)
        self.trans_dur.setSingleStep(0.1)
        self.trans_dur.setValue(0.8)
        self.trans_dur.setSuffix(" s")
        row.addWidget(self.trans_dur)
        self.pad_spin = QDoubleSpinBox()
        self.pad_spin.setRange(0.0, 5.0)
        self.pad_spin.setSingleStep(0.1)
        self.pad_spin.setValue(0.7)
        self.pad_spin.setSuffix(" s")
        self.pad_spin.setToolTip(
            "Silent pause appended after each slide's narration")
        row.addWidget(QLabel("Pause"))
        row.addWidget(self.pad_spin)
        lay.addLayout(row)
        self.trans_combo.currentIndexChanged.connect(
            lambda _: self.trans_dur.setEnabled(
                self.trans_combo.currentText() != "None"))
        self.trans_dur.setEnabled(False)

        checks = QHBoxLayout()
        self.narr_check = QCheckBox(
            "Write narration from slide text when a slide has none")
        self.narr_check.setChecked(True)
        self.narr_check.setToolTip(
            "Slides without a narration box speak their title + body — "
            "this copies that text into the narration so you can tweak "
            "it in the editor afterwards")
        checks.addWidget(self.narr_check)
        checks.addStretch(1)
        self.srt_check = QCheckBox("Save .srt subtitles next to each video")
        self.srt_check.setChecked(True)
        checks.addWidget(self.srt_check)
        lay.addLayout(checks)

        # output folder ------------------------------------------------------
        lay.addLayout(self._row("Output folder", self._out_row()))

        self.warn_label = QLabel(
            "✗ ffmpeg is required for MP4 export — install it and restart, "
            "or use File ▸ Export with the HTML format instead.")
        self.warn_label.setProperty("hint", True)
        self.warn_label.setWordWrap(True)
        self.warn_label.setVisible(not self.ffmpeg_ok)
        lay.addWidget(self.warn_label)

        # progress -------------------------------------------------------------
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        lay.addWidget(self.progress)
        self.status_label = QLabel("Add one or more files, then Convert.")
        self.status_label.setProperty("hint", True)
        lay.addWidget(self.status_label)

        # buttons ----------------------------------------------------------------
        row = QHBoxLayout()
        self.btn_open = QPushButton("Open folder")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_folder)
        row.addWidget(self.btn_open)
        self.btn_play = QPushButton("Play last")
        self.btn_play.setEnabled(False)
        self.btn_play.setToolTip("Play the most recently converted video "
                                 "in your default player")
        self.btn_play.clicked.connect(self._play_last)
        row.addWidget(self.btn_play)
        row.addStretch(1)
        self.btn_cancel = QPushButton("Close")
        self.btn_cancel.clicked.connect(self._cancel_or_close)
        row.addWidget(self.btn_cancel)
        self.btn_convert = QPushButton("Convert ▸")
        self.btn_convert.setObjectName("primary")
        self.btn_convert.setDefault(True)
        self.btn_convert.clicked.connect(self._convert)
        row.addWidget(self.btn_convert)
        lay.addLayout(row)

    @staticmethod
    def _row(label: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(90)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        return row

    def _out_row(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText(
            f"{folders.output_root(create=False)}  "
            "(File \u25b8 Input & output folders changes this)")
        h.addWidget(self.out_edit, 1)
        btn = QPushButton("Choose…")
        btn.clicked.connect(self._pick_out)
        h.addWidget(btn)
        return w

    def _populate_voices(self) -> None:
        self.voice_combo.addItem("Deck default voice", "")
        try:
            for v in tts.voices_for_engine("edge"):
                self.voice_combo.addItem(f"edge · {v['ShortName']}",
                                         v["ShortName"])
        except Exception:
            pass
        try:
            for v in tts.PIPER_VOICES:
                if tts.piper_voice_installed(v["ShortName"]):
                    self.voice_combo.addItem(
                        f"piper · {v['ShortName'].split(':', 1)[1]}",
                        v["ShortName"])
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # input list management
    # ------------------------------------------------------------------ #
    def queued_paths(self) -> list[str]:
        out = []
        for i in range(self.file_list.count()):
            out.append(self.file_list.item(i).data(Qt.ItemDataRole.UserRole))
        return out

    def add_paths(self, paths_: list[str]) -> int:
        """Append supported files (deduped); returns how many were added."""
        added = 0
        for p in paths_:
            p = os.path.abspath(p)
            ext = os.path.splitext(p)[1].lower()
            if ext not in PROJECT_EXTS or not os.path.isfile(p):
                continue
            if p in self.queued_paths():
                continue                    # duplicate — silently skipped
            self.file_list.addItem(p)
            item = self.file_list.item(self.file_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setText(os.path.basename(p) + "   —   " + os.path.dirname(p))
            item.setIcon(icons.icon("film"))
            item.setToolTip(p)
            added += 1
        if added:
            self.status_label.setText(f"Added {added} file(s) to convert.")
        self._sync_convert_enabled()
        return added

    def _sync_convert_enabled(self) -> None:
        self.btn_convert.setEnabled(
            bool(self.queued_paths()) and not self._running
            and self.ffmpeg_ok)
        self.btn_remove.setEnabled(
            bool(self.file_list.selectedItems()) and not self._running)
        for b in (self.btn_add_files, self.btn_add_folder, self.btn_clear):
            b.setEnabled(not self._running)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add slideshows to convert", folders.browse_dir("input"),
            FILE_FILTER)
        if files:
            folders.remember_folder(os.path.dirname(files[0]))
            self.add_paths(files)

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Add a folder of slideshows", folders.browse_dir("input"))
        if not d:
            return
        folders.remember_folder(d)
        n = self.add_paths(scan_folder(d))
        if not n:
            self.status_label.setText(
                "No importable slideshows found in that folder.")

    def _remove_selected(self) -> None:
        for it in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(it))
        self._sync_convert_enabled()

    def _clear(self) -> None:
        if self._running:
            return
        self.file_list.clear()
        self._sync_convert_enabled()
        self.status_label.setText("List cleared.")

    # drag & drop ---------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                ext = os.path.splitext(url.toLocalFile())[1].lower()
                if ext in PROJECT_EXTS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths_ = [url.toLocalFile() for url in event.mimeData().urls()
                  if url.isLocalFile()]
        if self.add_paths(paths_):
            event.acceptProposedAction()

    # ------------------------------------------------------------------ #
    # settings
    # ------------------------------------------------------------------ #
    def _restore_settings(self) -> None:
        s = self.settings
        res = s.value("quick/res")
        if res and self.res_combo.findText(res) >= 0:
            self.res_combo.setCurrentText(res)
        tr = s.value("quick/transition")
        if tr and self.trans_combo.findText(tr) >= 0:
            self.trans_combo.setCurrentText(tr)
        self.trans_dur.setValue(float(s.value("quick/trans_dur", 0.8)))
        self.trans_dur.setEnabled(self.trans_combo.currentText() != "None")
        self.pad_spin.setValue(float(s.value("quick/pad", 0.7)))
        self.narr_check.setChecked(
            s.value("quick/auto_narr", "true") in (True, "true", "1"))
        self.srt_check.setChecked(
            s.value("quick/srt", "true") in (True, "true", "1"))
        vid = str(s.value("quick/voice", "") or "")
        i = self.voice_combo.findData(vid)
        if i >= 0:
            self.voice_combo.setCurrentIndex(i)
        out = str(s.value("quick/out_dir", "") or "").strip()
        if out and os.path.isdir(out):
            self.out_edit.setText(out)

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("quick/res", self.res_combo.currentText())
        s.setValue("quick/transition", self.trans_combo.currentText())
        s.setValue("quick/trans_dur", self.trans_dur.value())
        s.setValue("quick/pad", self.pad_spin.value())
        s.setValue("quick/auto_narr", self.narr_check.isChecked())
        s.setValue("quick/srt", self.srt_check.isChecked())
        s.setValue("quick/voice", self.voice_combo.currentData() or "")
        if self._out_dir:
            s.setValue("quick/out_dir", self._out_dir)

    # ------------------------------------------------------------------ #
    # deck preparation (kept testable)
    # ------------------------------------------------------------------ #
    def _load_deck(self, path: str) -> Deck:
        """Import a queued file into a fresh Deck."""
        if path.lower().endswith(".slideshow"):
            return workspace.load_project(path)
        slides = import_file(path)
        if not slides:
            raise ValueError("No slides were found in the file.")
        deck = Deck()
        deck.name = os.path.splitext(os.path.basename(path))[0] or "deck"
        deck.slides = list(slides)
        return deck

    def _prepare_deck(self, deck: Deck) -> Deck:
        """Apply the quick-convert conveniences: auto-narration + voice."""
        if self.narr_check.isChecked():
            for s in deck.slides:
                if not (s.narration or "").strip():
                    text = s.effective_narration().strip()
                    if text:
                        s.narration = text
        vid = self.voice_combo.currentData()
        if vid:
            deck.default_voice = VoiceSettings(voice=vid)
        return deck

    # ------------------------------------------------------------------ #
    # running the conversions
    # ------------------------------------------------------------------ #
    def _convert(self) -> None:
        files = self.queued_paths()
        if not files or self._running:
            return
        if not self.ffmpeg_ok:
            self.status_label.setText("✗ ffmpeg is required for MP4 export.")
            return
        out_dir = self.out_edit.text().strip() or folders.output_root()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.status_label.setText(f"✗ Output folder unusable: {exc}")
            return
        self._out_dir = out_dir
        self._save_settings()
        self._cancel_requested = False
        self._ok_count = 0
        self._fail_count = 0
        self._n_done = 0
        self._total = len(files)
        self._failures = []
        self._queue = list(files)
        for i in range(self.file_list.count()):
            self.file_list.item(i).setIcon(icons.icon("film"))
        self._set_running(True)
        self.progress.setValue(0)
        self.status_label.setText(f"Converting {self._total} file(s) to "
                                  "MP4 …")
        QTimer.singleShot(30, self._next_file)

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.btn_convert.setText("Converting …" if running
                                 else "Convert ▸")
        self.btn_cancel.setText("Cancel" if running else "Close")
        self.out_edit.setEnabled(not running)
        self.narr_check.setEnabled(not running)
        self.srt_check.setEnabled(not running)
        for w in (self.voice_combo, self.res_combo, self.trans_combo,
                  self.trans_dur, self.pad_spin):
            w.setEnabled(not running)
        self.btn_play.setEnabled(not running and bool(self._last_out))
        self.btn_open.setEnabled(not running and bool(self._last_out))
        self.btn_convert.setEnabled(not running)
        if not running:
            self._sync_convert_enabled()

    def _next_file(self) -> None:
        if self._cancel_requested:
            self._queue.clear()
            self._finish_all()
            return
        if not self._queue:
            self._finish_all()
            return
        path = self._queue.pop(0)
        self._current = path
        self._n_label = os.path.basename(path)
        self.status_label.setText(
            f"[{self._n_done + 1}/{self._total}] {self._n_label} — "
            "importing …")
        QApplication.processEvents()

        try:
            deck = self._load_deck(path)
        except Exception as exc:
            self._row_failed(path, str(exc))
            self._advance()
            return
        if not deck.slides:
            self._row_failed(path, "The file produced no slides.")
            self._advance()
            return
        deck = self._prepare_deck(deck)
        stem = deck.name or os.path.splitext(self._n_label)[0] or "slideshow"
        out = unique_path(self._out_dir, stem, "mp4")
        self.status_label.setText(
            f"[{self._n_done + 1}/{self._total}] {self._n_label} — "
            "rendering …")
        opts = ExportOptions(
            mode="mp4",
            resolution=self.res_combo.currentText(),
            pad=self.pad_spin.value(),
            use_music=False,
            duck_music=True,
            audio_format="mp3",
            out_path=out,
            transition=self.trans_combo.currentText(),
            transition_dur=self.trans_dur.value(),
            save_srt=self.srt_check.isChecked(),
            burn_subtitles=False,
        )
        self.worker = ExportWorker(deck, opts, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_ok)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    # ---- worker signal handlers -------------------------------------------
    def _on_progress(self, pct: int, msg: str) -> None:
        overall = int(100 * (self._n_done + pct / 100.0)
                      / max(1, self._total))
        self.progress.setValue(overall)
        self.status_label.setText(
            f"[{self._n_done + 1}/{self._total}] {self._n_label} — {msg}")

    def _on_ok(self, path: str) -> None:
        self._n_done += 1
        self._ok_count += 1
        self._last_out = path
        it = self._row_item(path)
        if it is not None:
            it.setIcon(icons.icon("check"))
        self.exported.emit(path)

    def _on_failed(self, msg: str) -> None:
        self._row_failed(self._current, msg)

    def _on_cancelled(self) -> None:
        self._row_failed(self._current, "cancelled")

    def _on_worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if self._cancel_requested:
            self._queue.clear()
            self._finish_all()
            return
        self._advance()

    def _advance(self) -> None:
        QTimer.singleShot(60, self._next_file)

    # ---- row / bookkeeping helpers ------------------------------------------
    def _row_item(self, path: str):
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                return it
        return None

    def _row_failed(self, path: str, reason: str) -> None:
        self._n_done += 1
        self._fail_count += 1
        short = f"{os.path.basename(path)}: {reason}"
        self._failures.append(short)
        it = self._row_item(path)
        if it is not None:
            it.setIcon(icons.icon("close"))
            it.setToolTip(f"{it.toolTip()}\n✗ {reason}")
        self.status_label.setText(f"✗ {short}")

    def _finish_all(self) -> None:
        self._set_running(False)
        if self._fail_count:
            first = self._failures[0] if self._failures else ""
            self.status_label.setText(
                f"✓ {self._ok_count} MP4(s) exported, ✗ {self._fail_count} "
                "failed — see the list for reasons."
                + (f"  First failure: {first}" if not self._ok_count
                   and first else ""))
        else:
            self.status_label.setText(
                f"✓ {self._ok_count} MP4(s) exported to {self._out_dir}")
        self.progress.setValue(100 if self._ok_count else 0)

    # ---- cancel / post-export actions ----------------------------------------
    def _cancel_or_close(self) -> None:
        if self._running:
            self._cancel_requested = True
            self.status_label.setText(
                "Cancelling after the current video …")
            if self.worker is not None:
                self.worker.cancel()
            return
        self.reject()

    def reject(self) -> None:  # noqa: N802
        # Esc must not kill a running conversion (same rule as batch)
        if self._running:
            return
        super().reject()

    def _open_folder(self) -> None:
        folder = self._out_dir or self.out_edit.text().strip() \
            or folders.output_root()
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _play_last(self) -> None:
        if self._last_out and os.path.isfile(self._last_out):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_out))

    def _pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Choose the output folder",
            self.out_edit.text().strip() or folders.output_root())
        if d:
            self.out_edit.setText(d)
            folders.remember_folder(d)
