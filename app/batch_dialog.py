"""Batch export: queue many slideshows and render them all in one run.

File ▸ Batch export… opens a queue that accepts .slideshow projects, any
importable file (PPTX / PPT / PDF / HTML / TXT / MD), whole folders, or the
deck currently open in the editor. Jobs are exported sequentially with the
regular ExportWorker pipeline (or the fast inline HTML exporter), each row
showing its own status and details.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QProgressBar, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import folders, paths, workspace
from .export_worker import RESOLUTIONS, TRANSITIONS, ExportOptions, ExportWorker
from .importers import import_file
from .models import Deck

# job states (kept as module constants so tests can import them)
JOB_PENDING = "Pending"
JOB_RUNNING = "Running…"
JOB_DONE = "Done"
JOB_FAILED = "Failed"
JOB_SKIPPED = "Skipped"
JOB_CANCELLED = "Cancelled"

_KINDS = {
    ".slideshow": "Project",
    ".pptx": "PowerPoint", ".ppt": "PowerPoint",
    ".pdf": "PDF", ".html": "HTML", ".htm": "HTML",
    ".txt": "Text script", ".md": "Markdown", ".markdown": "Markdown",
}

_STATUS_COLORS = {
    JOB_DONE: "#6fd08c",
    JOB_FAILED: "#e05a4e",
    JOB_RUNNING: "#4da3ff",
    JOB_SKIPPED: "#8a95a3",
    JOB_CANCELLED: "#8a95a3",
}

ALL_SUPPORTED_FILTER = (
    "All supported (*.slideshow *.pptx *.ppt *.pdf *.html *.htm *.txt "
    "*.md *.markdown);;"
    "Slideshow project (*.slideshow);;PowerPoint (*.pptx *.ppt);;"
    "PDF (*.pdf);;HTML (*.html *.htm);;Text (*.txt);;"
    "Markdown (*.md *.markdown)"
)


def kind_label(path: str) -> str:
    """Friendly type tag for a queued file."""
    return _KINDS.get(os.path.splitext(path)[1].lower(), "?")


def unique_path(folder: str, stem: str, ext: str) -> str:
    """'<stem>.<ext>' inside folder, adding -2, -3 … on collision."""
    stem = paths.sanitize_stem(stem)
    ext = ext.lstrip(".")
    base = os.path.join(folder, f"{stem}.{ext}")
    if not os.path.exists(base):
        return base
    i = 2
    while os.path.exists(os.path.join(folder, f"{stem}-{i}.{ext}")):
        i += 1
    return os.path.join(folder, f"{stem}-{i}.{ext}")


def scan_folder(folder: str) -> list[str]:
    """Every importable file below folder (hidden folders skipped)."""
    found: list[str] = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in paths.IMPORTABLE_EXTS:
                found.append(os.path.join(root, fn))
    return sorted(found)


class BatchJob:
    """One queued slideshow (a source file, or the deck open on screen)."""

    def __init__(self, path: str | None = None, deck: Deck | None = None,
                 label: str | None = None):
        self.path = path
        self.deck = deck
        if label:
            self.label = label
        elif deck is not None:
            self.label = deck.name or "Current deck"
        else:
            self.label = os.path.splitext(os.path.basename(path or ""))[0] \
                or "deck"
        self.kind = "Current deck" if deck is not None else kind_label(path)
        self.status = JOB_PENDING
        self.detail = ""
        self.out_path = ""
        self.item: QTreeWidgetItem | None = None


class BatchExportDialog(QDialog):
    """Queue slideshows and export them all with one click."""

    def __init__(self, parent=None, ffmpeg_ok: bool = True,
                 current_deck: Deck | None = None):
        super().__init__(parent)
        self.ffmpeg_ok = ffmpeg_ok
        self.current_deck = current_deck
        self.jobs: list[BatchJob] = []
        self.worker: ExportWorker | None = None
        self._running = False
        self._cancel_requested = False
        self._current: BatchJob | None = None
        self._queue: list[BatchJob] = []
        self._total = 0
        self._n_done = 0
        self._ok_count = 0
        self._fail_count = 0
        self._skip_count = 0
        self._out_dir = ""
        self.settings = QSettings("ZaiStudio", "SlideshowStudio")
        self.setWindowTitle("Batch export")
        self.setMinimumSize(760, 600)
        self._build()
        self._restore_settings()
        self._update_buttons()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel("Batch export")
        head.setProperty("heading", True)
        lay.addWidget(head)

        intro = QLabel("Queue slideshows (projects or importable files) and "
                       "export them all in one run. Each deck keeps its own "
                       "theme, voices, motion and narration.")
        intro.setProperty("hint", True)
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # ---- job queue --------------------------------------------------
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Slideshow", "Type", "Status", "Details"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setMinimumHeight(170)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_add_files = QPushButton("Add files…")
        self.btn_add_files.setToolTip("Pick one or more slideshow files "
                                      "(multi-select)")
        self.btn_add_folder = QPushButton("Add folder…")
        self.btn_add_folder.setToolTip("Scan a folder for every importable "
                                       "slideshow")
        self.btn_add_deck = QPushButton("Add current deck")
        self.btn_add_deck.setToolTip("Queue the deck that is open in the "
                                     "editor right now")
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setToolTip("Remove the selected jobs from the queue")
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip("Empty the queue")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_add_deck.clicked.connect(self._add_current_deck)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear_jobs)
        for b in (self.btn_add_files, self.btn_add_folder, self.btn_add_deck):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        lay.addLayout(row)

        # ---- format ------------------------------------------------------
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["MP4 video (narrated slideshow)",
                                  "Audio only (MP3 / WAV)",
                                  "HTML slideshow (web page)"])
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        lay.addLayout(self._row("Format", self.mode_combo))

        self.res_combo = QComboBox()
        self.res_combo.addItems(list(RESOLUTIONS.keys()))
        self.res_combo.setCurrentText("Full HD 1920×1080")
        self.res_row = self._row("Resolution", self.res_combo)
        lay.addLayout(self.res_row)

        self.aud_combo = QComboBox()
        self.aud_combo.addItems(["mp3", "wav"])
        self.aud_row = self._row("Audio codec", self.aud_combo)
        lay.addLayout(self.aud_row)

        self.trans_combo = QComboBox()
        self.trans_combo.addItems(list(TRANSITIONS.keys()))
        self.trans_combo.setCurrentText("None")
        self.trans_combo.setToolTip("Transition applied when each video is "
                                    "assembled")
        self.trans_row = self._row("Transition", self.trans_combo)
        lay.addLayout(self.trans_row)

        self.trans_dur = QDoubleSpinBox()
        self.trans_dur.setRange(0.2, 2.0)
        self.trans_dur.setSingleStep(0.1)
        self.trans_dur.setValue(0.8)
        self.trans_dur.setSuffix(" s")
        self.trans_dur_row = self._row("Trans. length", self.trans_dur)
        lay.addLayout(self.trans_dur_row)

        self.pad_spin = QDoubleSpinBox()
        self.pad_spin.setRange(0.0, 5.0)
        self.pad_spin.setSingleStep(0.1)
        self.pad_spin.setValue(0.7)
        self.pad_spin.setSuffix(" s")
        self.pad_spin.setToolTip("Silent pause appended after each slide's "
                                 "narration")
        self.pad_row = self._row("Pause / slide", self.pad_spin)
        lay.addLayout(self.pad_row)

        self.music_check = QCheckBox(
            "Mix each deck's background music (where set)")
        self.music_check.setChecked(True)
        lay.addWidget(self.music_check)
        self.srt_check = QCheckBox("Save subtitles file (.srt) per deck")
        self.srt_check.setToolTip("Write each deck's narration as an .srt "
                                  "file next to its output")
        lay.addWidget(self.srt_check)

        # ---- output folder -----------------------------------------------
        lay.addLayout(self._row("Output folder", self._out_row()))

        self.open_check = QCheckBox("Open output folder when finished")
        self.open_check.setChecked(True)
        lay.addWidget(self.open_check)

        self.warn_label = QLabel(
            "✗ ffmpeg is required for video/audio export — install it or "
            "choose the HTML format.")
        self.warn_label.setProperty("hint", True)
        self.warn_label.setWordWrap(True)
        lay.addWidget(self.warn_label)

        # ---- progress ------------------------------------------------------
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        lay.addWidget(self.progress)
        self.status_label = QLabel("Ready — add slideshows to the queue.")
        self.status_label.setProperty("hint", True)
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        # ---- buttons -------------------------------------------------------
        row = QHBoxLayout()
        self.btn_open = QPushButton("Open folder")
        self.btn_open.clicked.connect(self._open_folder)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._cancel_or_close)
        row.addWidget(self.btn_cancel)
        self.btn_start = QPushButton("Start batch export")
        self.btn_start.setObjectName("primary")
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self._start)
        row.addWidget(self.btn_start)
        lay.addLayout(row)

    @staticmethod
    def _row(label: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(90)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        return row

    @staticmethod
    def _set_row_visible(row: QHBoxLayout, visible: bool) -> None:
        for i in range(row.count()):
            item = row.itemAt(i)
            if item.widget():
                item.widget().setVisible(visible)

    def _out_row(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Where the exported files go …")
        h.addWidget(self.out_edit, 1)
        btn = QPushButton("…")
        btn.setFixedWidth(34)
        btn.clicked.connect(self._pick_out)
        h.addWidget(btn)
        return w

    def _pick_out(self) -> None:
        start = self.out_edit.text().strip() or folders.browse_dir("output")
        d = QFileDialog.getExistingDirectory(self, "Choose output folder",
                                             start)
        if d:
            self.out_edit.setText(d)
            folders.remember_folder(d)
            self._update_buttons()

    # ------------------------------------------------------------------ #
    # queue management
    # ------------------------------------------------------------------ #
    def _add_job(self, job: BatchJob) -> None:
        job.item = QTreeWidgetItem([job.label, job.kind, job.status, ""])
        job.item.setToolTip(0, job.path or job.label)
        self.tree.addTopLevelItem(job.item)
        self.jobs.append(job)
        self._update_buttons()

    def add_paths(self, files) -> int:
        """Queue files programmatically (menu handlers + tests). Dedupes."""
        seen = {os.path.abspath(j.path) for j in self.jobs if j.path}
        added = 0
        for f in files:
            if not f or not os.path.isfile(f):
                continue
            ap = os.path.abspath(f)
            if ap in seen:
                continue
            seen.add(ap)
            self._add_job(BatchJob(path=f))
            added += 1
        return added

    def _add_files(self) -> None:
        start = folders.browse_dir("input")
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add slideshows to the batch", start, ALL_SUPPORTED_FILTER)
        if not files:
            return
        self.settings.setValue("last_dir", os.path.dirname(files[0]))
        folders.remember_folder(os.path.dirname(files[0]))
        n = self.add_paths(files)
        if n:
            self.status_label.setText(f"Added {n} slideshow(s) to the queue.")
        else:
            self.status_label.setText(
                "Nothing added — those files are already in the queue.")

    def _add_folder(self) -> None:
        start = self.out_edit.text().strip() or folders.browse_dir("input")
        d = QFileDialog.getExistingDirectory(
            self, "Choose a folder of slideshows", start)
        if not d:
            return
        folders.remember_folder(d)
        files = scan_folder(d)
        n = self.add_paths(files)
        if n:
            self.status_label.setText(
                f"Added {n} slideshow(s) found in {d}.")
        else:
            self.status_label.setText(
                "No importable slideshows found in that folder.")

    def _add_current_deck(self) -> None:
        deck = self.current_deck
        if deck is None or not deck.slides:
            self.status_label.setText(
                "The deck on screen has no slides to export.")
            return
        for j in self.jobs:
            if j.deck is deck:
                self.status_label.setText(
                    "The current deck is already in the queue.")
                return
        self._add_job(BatchJob(deck=deck,
                               label=deck.name or "Current deck"))
        self.status_label.setText("Added the deck currently on screen.")

    def _remove_selected(self) -> None:
        for it in self.tree.selectedItems():
            idx = self.tree.indexOfTopLevelItem(it)
            if idx < 0:
                continue
            self.tree.takeTopLevelItem(idx)
            for j in list(self.jobs):
                if j.item is it:
                    self.jobs.remove(j)
                    break
        self._update_buttons()

    def _clear_jobs(self) -> None:
        if self._running:
            return
        self.tree.clear()
        self.jobs.clear()
        self.status_label.setText("Queue cleared.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_jobs = bool(self.jobs)
        mode_html = self.mode_combo.currentIndex() == 2
        self.btn_start.setEnabled(
            has_jobs and not self._running
            and (mode_html or self.ffmpeg_ok))
        self.btn_remove.setEnabled(has_jobs and not self._running
                                   and bool(self.tree.selectedItems()))
        self.btn_clear.setEnabled(has_jobs and not self._running)
        for b in (self.btn_add_files, self.btn_add_folder):
            b.setEnabled(not self._running)
        deck_ok = bool(self.current_deck is not None
                       and self.current_deck.slides)
        self.btn_add_deck.setEnabled(deck_ok and not self._running
            and not any(j.deck is self.current_deck for j in self.jobs))

    # ------------------------------------------------------------------ #
    # settings
    # ------------------------------------------------------------------ #
    def _restore_settings(self) -> None:
        s = self.settings
        self.mode_combo.setCurrentIndex(int(s.value("batch/mode_idx", 0)))
        res = s.value("batch/res")
        if res and self.res_combo.findText(res) >= 0:
            self.res_combo.setCurrentText(res)
        aud = s.value("batch/audio_fmt")
        if aud and self.aud_combo.findText(aud) >= 0:
            self.aud_combo.setCurrentText(aud)
        tr = s.value("batch/transition")
        if tr and self.trans_combo.findText(tr) >= 0:
            self.trans_combo.setCurrentText(tr)
        self.trans_dur.setValue(float(s.value("batch/trans_dur", 0.8)))
        self.pad_spin.setValue(float(s.value("batch/pad", 0.7)))
        self.music_check.setChecked(
            s.value("batch/music", "true") in (True, "true", "1"))
        self.srt_check.setChecked(
            s.value("batch/srt", "false") in (True, "true", "1"))
        self.open_check.setChecked(
            s.value("batch/open_folder", "true") in (True, "true", "1"))
        out = str(s.value("batch/out_dir", "") or "").strip()
        if out and os.path.isdir(out):
            self.out_edit.setText(out)
        else:
            self.out_edit.setText(paths.output_dir())
        self._mode_changed(self.mode_combo.currentIndex())

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("batch/mode_idx", self.mode_combo.currentIndex())
        s.setValue("batch/res", self.res_combo.currentText())
        s.setValue("batch/audio_fmt", self.aud_combo.currentText())
        s.setValue("batch/transition", self.trans_combo.currentText())
        s.setValue("batch/trans_dur", self.trans_dur.value())
        s.setValue("batch/pad", self.pad_spin.value())
        s.setValue("batch/music", self.music_check.isChecked())
        s.setValue("batch/srt", self.srt_check.isChecked())
        s.setValue("batch/open_folder", self.open_check.isChecked())
        if self._out_dir:
            s.setValue("batch/out_dir", self._out_dir)

    def _mode_changed(self, idx: int) -> None:
        video = idx == 0
        audio = idx == 1
        html = idx == 2
        self._set_row_visible(self.res_row, video)
        self.res_combo.setVisible(video)
        self._set_row_visible(self.aud_row, audio)
        self.aud_combo.setVisible(audio)
        self._set_row_visible(self.trans_row, video)
        self.trans_combo.setVisible(video)
        self._set_row_visible(self.trans_dur_row, video)
        self.trans_dur.setVisible(video)
        self._set_row_visible(self.pad_row, not html)
        self.pad_spin.setVisible(not html)
        self.music_check.setVisible(not html)
        self.srt_check.setVisible(not html)
        self.warn_label.setVisible(not html and not self.ffmpeg_ok)
        self._update_buttons()

    # ------------------------------------------------------------------ #
    # running the batch
    # ------------------------------------------------------------------ #
    def _start(self) -> None:
        if not self.jobs or self._running:
            return
        mode_html = self.mode_combo.currentIndex() == 2
        if not mode_html and not self.ffmpeg_ok:
            self.status_label.setText(
                "✗ ffmpeg is required for video/audio export — install it "
                "or choose the HTML format.")
            return
        out_dir = self.out_edit.text().strip() or paths.output_dir()
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
        self._skip_count = 0
        self._n_done = 0
        self._total = len(self.jobs)
        for j in self.jobs:
            j.status = JOB_PENDING
            j.detail = ""
            j.out_path = ""
            self._paint(j)
        self._queue = list(self.jobs)
        self._set_running(True)
        self.progress.setValue(0)
        self.status_label.setText(
            f"Starting batch — {self._total} slideshow(s) …")
        QTimer.singleShot(30, self._next_job)

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_start.setText("Exporting …" if running
                               else "Start batch export")
        self.btn_cancel.setText("Cancel batch" if running else "Close")
        self.open_check.setEnabled(not running)
        self.out_edit.setEnabled(not running)
        for w in (self.mode_combo, self.res_combo, self.aud_combo,
                  self.trans_combo, self.trans_dur, self.pad_spin,
                  self.music_check, self.srt_check):
            w.setEnabled(not running)
        for b in (self.btn_add_files, self.btn_add_folder, self.btn_add_deck,
                  self.btn_remove, self.btn_clear):
            b.setEnabled(not running)
        if not running:
            self._update_buttons()

    def _load_deck(self, job: BatchJob) -> Deck:
        """Turn a queued job into a Deck (project load or importer)."""
        if job.deck is not None:
            return job.deck
        p = job.path or ""
        if p.lower().endswith(".slideshow"):
            return workspace.load_project(p)
        slides = import_file(p)
        if not slides:
            raise ValueError("No slides were found in the file.")
        deck = Deck()
        deck.name = os.path.splitext(os.path.basename(p))[0] or "deck"
        deck.slides = list(slides)
        return deck

    def _next_job(self) -> None:
        if self._cancel_requested:
            for j in self._queue:
                if j.status == JOB_PENDING:
                    j.status = JOB_SKIPPED
                    self._paint(j)
                    self._skip_count += 1
            self._queue.clear()
            self._finish_all()
            return
        if not self._queue:
            self._finish_all()
            return
        job = self._queue.pop(0)
        self._current = job
        job.status = JOB_RUNNING
        self._paint(job)
        idx = self.mode_combo.currentIndex()
        mode = "mp4" if idx == 0 else "audio" if idx == 1 else "html"
        if idx == 0:
            ext = "mp4"
        elif idx == 1:
            ext = self.aud_combo.currentText()
        else:
            ext = "html"
        self.status_label.setText(
            f"[{self._n_done + 1}/{self._total}] {job.label} — loading …")

        try:
            deck = self._load_deck(job)
        except Exception as exc:
            self._job_failed(job, str(exc))
            return
        if not deck.slides:
            self._job_failed(job, "The deck has no slides to export.")
            return
        job.out_path = unique_path(self._out_dir, deck.name or job.label, ext)

        if mode == "html":
            self._run_html_job(job, deck)
            return

        opts = ExportOptions(
            mode=mode,
            resolution=self.res_combo.currentText(),
            pad=self.pad_spin.value(),
            use_music=self.music_check.isChecked(),
            duck_music=True,
            audio_format=self.aud_combo.currentText(),
            out_path=job.out_path,
            transition=(self.trans_combo.currentText()
                        if mode == "mp4" else "None"),
            transition_dur=self.trans_dur.value(),
            save_srt=self.srt_check.isChecked(),
            burn_subtitles=False,
        )
        self.worker = ExportWorker(deck, opts, self)
        self.worker.progress.connect(self._on_job_progress)
        self.worker.finished_ok.connect(self._on_job_ok)
        self.worker.failed.connect(self._on_job_failed_sig)
        self.worker.cancelled.connect(self._on_job_cancelled)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _run_html_job(self, job: BatchJob, deck: Deck) -> None:
        """HTML export needs no ffmpeg — run it inline (fast)."""
        from . import html_export
        self.status_label.setText(
            f"[{self._n_done + 1}/{self._total}] {job.label} — building "
            "HTML …")
        QApplication.processEvents()
        try:
            html_export.export_html(deck, job.out_path)
        except Exception as exc:
            self._job_failed(job, str(exc))
            return
        self._job_ok(job, job.out_path)

    def _advance(self) -> None:
        QTimer.singleShot(60, self._next_job)

    # ---- per-job signal handlers --------------------------------------
    def _on_job_progress(self, pct: int, msg: str) -> None:
        job = self._current
        overall = int(100 * (self._n_done + pct / 100.0)
                      / max(1, self._total))
        self.progress.setValue(overall)
        if job is not None:
            job.status = f"{pct}%" if pct < 100 else JOB_DONE
            job.detail = msg
            self._paint(job)
            self.status_label.setText(
                f"[{self._n_done + 1}/{self._total}] {job.label} — {msg}")

    def _on_job_ok(self, path: str) -> None:
        job = self._current
        if job is not None:
            detail = os.path.basename(path)
            srt = os.path.splitext(path)[0] + ".srt"
            if os.path.isfile(srt):
                detail += "  (+ .srt)"
            job.out_path = path
            self._set_job_done(job, detail)

    def _on_job_failed_sig(self, msg: str) -> None:
        job = self._current
        if job is not None:
            self._set_job_failed(job, msg)

    def _on_job_cancelled(self) -> None:
        job = self._current
        if job is not None:
            job.status = JOB_CANCELLED
            job.detail = "Cancelled"
            self._paint(job)
            self._skip_count += 1
            self._n_done += 1

    def _on_worker_finished(self) -> None:
        w = self.sender()
        if w is not None:
            w.deleteLater()
        if self.worker is w:
            self.worker = None
        self._current = None
        self._advance()

    # ---- job completion helpers (load failures use these too) ----------
    def _job_ok(self, job: BatchJob, path: str) -> None:
        detail = os.path.basename(path)
        srt = os.path.splitext(path)[0] + ".srt"
        if os.path.isfile(srt):
            detail += "  (+ .srt)"
        job.out_path = path
        self._set_job_done(job, detail)
        self._current = None
        self._advance()

    def _job_failed(self, job: BatchJob, msg: str) -> None:
        self._set_job_failed(job, msg)
        self._current = None
        self._advance()

    def _set_job_done(self, job: BatchJob, detail: str) -> None:
        job.status = JOB_DONE
        job.detail = detail
        self._paint(job)
        self._ok_count += 1
        self._n_done += 1
        self.progress.setValue(int(100 * self._n_done
                                   / max(1, self._total)))

    def _set_job_failed(self, job: BatchJob, msg: str) -> None:
        job.status = JOB_FAILED
        job.detail = msg
        self._paint(job)
        self._fail_count += 1
        self._n_done += 1
        self.progress.setValue(int(100 * self._n_done
                                   / max(1, self._total)))

    def _paint(self, job: BatchJob) -> None:
        if job.item is None:
            return
        job.item.setText(2, job.status)
        job.item.setText(3, job.detail)
        color = _STATUS_COLORS.get(job.status)
        if color:
            job.item.setForeground(2, QBrush(QColor(color)))

    def _finish_all(self) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        parts = [f"Batch finished — {self._ok_count} exported"]
        if self._fail_count:
            parts.append(f"{self._fail_count} failed")
        if self._skip_count:
            parts.append(f"{self._skip_count} skipped/cancelled")
        summary = ". ".join(parts) + "."
        if self._fail_count:
            summary += "  See the Details column for the errors."
        self.status_label.setText(summary)
        if self._ok_count and self.open_check.isChecked():
            self._open_folder()

    # ------------------------------------------------------------------ #
    def _cancel_or_close(self) -> None:
        if self._running:
            self._cancel_requested = True
            self.status_label.setText("Cancelling — stopping after the "
                                      "current job …")
            if self.worker is not None:
                self.worker.cancel()
            return
        self.reject()

    def reject(self) -> None:  # noqa: N802 — Esc must not kill a running batch
        if self._running:
            self._cancel_or_close()
            return
        super().reject()

    def _open_folder(self) -> None:
        d = self._out_dir or self.out_edit.text().strip() \
            or paths.output_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(d)))
