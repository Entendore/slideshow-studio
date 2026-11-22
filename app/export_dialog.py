"""Export dialog: MP4, audio, HTML, PDF handout or PowerPoint, with
named export presets, live progress + cancel."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from . import folders, presets
from .export_worker import (FFMPEG_MODES, RESOLUTIONS, TRANSITIONS,
                            ExportOptions, ExportWorker)
from .models import Deck
from .presets import LAST_PRESET_KEY, Preset


# export-dialog row index -> ExportOptions.mode
MODE_KEYS = ["mp4", "audio", "html", "pdf", "pptx"]


class ExportDialog(QDialog):
    """MP4 / audio / HTML / PDF / PPTX export with live progress + cancel.

    Emitted once per successful export so the main window can track the
    input -> MP4 workflow."""

    exported = Signal(str)

    def __init__(self, deck: Deck, parent=None, ffmpeg_ok: bool = True):
        super().__init__(parent)
        self.deck = deck
        self.ffmpeg_ok = ffmpeg_ok
        self.worker: ExportWorker | None = None
        self.settings = QSettings("ZaiStudio", "SlideshowStudio")
        self.setWindowTitle("Export slideshow")
        self.setMinimumWidth(470)
        self._last_suggest = ""          # most recent auto-suggested path
        self._presets: list[Preset] = []
        self._preset_applying = False    # guards tweak -> "(custom)" flip
        self._build()
        self._restore_settings()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel("Export")
        head.setProperty("heading", True)
        lay.addWidget(head)

        # named presets (populated + selected in _restore_settings)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("One click recalls a saved export "
                                     "configuration — Save… stores the "
                                     "options currently shown")
        self.btn_preset_save = QPushButton("Save…")
        self.btn_preset_save.setToolTip("Store the current options as a "
                                        "named preset")
        self.btn_preset_del = QPushButton("Delete")
        self.btn_preset_del.setToolTip("Remove the selected preset")
        self.btn_preset_del.setEnabled(False)
        self.btn_preset_save.clicked.connect(self._preset_save)
        self.btn_preset_del.clicked.connect(self._preset_delete)
        self.preset_combo.currentIndexChanged.connect(self._preset_selected)
        prow = QHBoxLayout()
        plab = QLabel("Preset")
        plab.setMinimumWidth(90)
        prow.addWidget(plab)
        prow.addWidget(self.preset_combo, 1)
        prow.addWidget(self.btn_preset_save)
        prow.addWidget(self.btn_preset_del)
        lay.addLayout(prow)

        # mode
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["MP4 video (narrated slideshow)",
                                  "Audio only (MP3 / WAV)",
                                  "HTML slideshow (web page)",
                                  "PDF handout (share / print)",
                                  "PowerPoint presentation (.pptx)"])
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        lay.addLayout(self._row("Format", self.mode_combo))

        # resolution (video only)
        self.res_combo = QComboBox()
        self.res_combo.addItems(list(RESOLUTIONS.keys()))
        self.res_combo.setCurrentText("Full HD 1920×1080")
        self.res_row = self._row("Resolution", self.res_combo)
        lay.addLayout(self.res_row)

        # audio format (audio only)
        self.aud_combo = QComboBox()
        self.aud_combo.addItems(["mp3", "wav"])
        self.aud_row = self._row("Audio codec", self.aud_combo)
        lay.addLayout(self.aud_row)

        # padding
        self.pad_spin = QDoubleSpinBox()
        self.pad_spin.setRange(0.0, 5.0)
        self.pad_spin.setSingleStep(0.1)
        self.pad_spin.setValue(0.7)
        self.pad_spin.setSuffix(" s")
        self.pad_spin.setToolTip("Silent pause appended after each slide's "
                                 "narration")
        self.pad_row = self._row("Pause / slide", self.pad_spin)
        lay.addLayout(self.pad_row)

        # transitions (video only)
        self.trans_combo = QComboBox()
        self.trans_combo.addItems(list(TRANSITIONS.keys()))
        self.trans_combo.setCurrentText("None")
        self.trans_combo.setToolTip("Animated transition between slides "
                                    "(applied when the video is assembled)")
        self.trans_row = self._row("Transition", self.trans_combo)
        lay.addLayout(self.trans_row)

        self.trans_dur = QDoubleSpinBox()
        self.trans_dur.setRange(0.2, 2.0)
        self.trans_dur.setSingleStep(0.1)
        self.trans_dur.setValue(0.8)
        self.trans_dur.setSuffix(" s")
        self.trans_dur_row = self._row("Trans. length", self.trans_dur)
        lay.addLayout(self.trans_dur_row)
        self.trans_combo.currentIndexChanged.connect(
            lambda _: self._trans_enabled())
        self._trans_enabled()

        # subtitles
        self.srt_check = QCheckBox("Save subtitles file (.srt)")
        self.srt_check.setToolTip("Write narration as an .srt file next to "
                                  "the output (great for YouTube uploads)")
        lay.addWidget(self.srt_check)
        self.burn_check = QCheckBox("Burn subtitles into video")
        self.burn_check.setToolTip("Hardcode the narration text into the "
                                   "MP4 picture")
        lay.addWidget(self.burn_check)
        self.sub_size = QSpinBox()
        self.sub_size.setRange(8, 40)
        self.sub_size.setValue(16)
        self.sub_size.setToolTip("Subtitle font size (libass units)")
        self.sub_size_row = self._row("Sub. size", self.sub_size)
        lay.addLayout(self.sub_size_row)
        self.burn_check.toggled.connect(
            lambda on: self._set_row_visible(self.sub_size_row, on))

        # documents (PDF / PPTX)
        self.notes_check = QCheckBox("Interleave notes pages "
                                     "(slide + spoken text)")
        self.notes_check.setToolTip("After every slide page, add a page with "
                                    "the slide thumbnail and the text that "
                                    "would be spoken — ideal as a handout")
        lay.addWidget(self.notes_check)

        # music
        music_available = bool(self.deck.music_path and
                               os.path.isfile(self.deck.music_path))
        self.music_check = QCheckBox(
            "Mix background music" +
            ("" if music_available else "  (no music track set in Deck tab)"))
        self.music_check.setEnabled(music_available)
        self.music_check.setChecked(music_available)
        lay.addWidget(self.music_check)
        self.duck_check = QCheckBox("Auto-duck music under narration")
        self.duck_check.setChecked(True)
        self.duck_check.setEnabled(music_available)
        indent = QHBoxLayout()
        indent.addSpacing(22)
        indent.addWidget(self.duck_check)
        indent.addStretch(1)
        lay.addLayout(indent)

        # output path
        lay.addLayout(self._row("Output file", self._out_row()))

        self.open_check = QCheckBox("Open the output folder when finished")
        self.open_check.setToolTip("Reveal the finished file in the file "
                                   "manager as soon as the export ends")
        lay.addWidget(self.open_check)

        # progress
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        lay.addWidget(self.progress)
        self.status_label = QLabel("Ready.")
        self.status_label.setProperty("hint", True)
        lay.addWidget(self.status_label)

        # buttons
        row = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Play the exported file in your default "
                                 "video/audio player")
        self.btn_play.clicked.connect(self._open_out)
        self.btn_play.setEnabled(False)
        row.addWidget(self.btn_play)
        self.btn_open = QPushButton("Open folder")
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_open.setEnabled(False)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._cancel_or_close)
        row.addWidget(self.btn_cancel)
        self.btn_start = QPushButton("Start export")
        self.btn_start.setObjectName("primary")
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self._start)
        row.addWidget(self.btn_start)
        lay.addLayout(row)

        # any manual edit drops the combo back to "(custom)" so the
        # selector always tells the truth about where the values came from
        self.mode_combo.currentIndexChanged.connect(self._on_user_tweak)
        self.res_combo.currentIndexChanged.connect(self._on_user_tweak)
        self.aud_combo.currentIndexChanged.connect(self._on_user_tweak)
        self.pad_spin.valueChanged.connect(self._on_user_tweak)
        self.trans_combo.currentIndexChanged.connect(self._on_user_tweak)
        self.trans_dur.valueChanged.connect(self._on_user_tweak)
        self.sub_size.valueChanged.connect(self._on_user_tweak)
        self.srt_check.toggled.connect(self._on_user_tweak)
        self.burn_check.toggled.connect(self._on_user_tweak)
        self.notes_check.toggled.connect(self._on_user_tweak)
        self.music_check.toggled.connect(self._on_user_tweak)
        self.duck_check.toggled.connect(self._on_user_tweak)
        self.open_check.toggled.connect(self._on_user_tweak)

        self._mode_changed(0)

    # ------------------------------------------------------------------ #
    # named export presets
    # ------------------------------------------------------------------ #
    def _rebuild_preset_combo(self, select: str | None = None) -> None:
        """Refill the preset combo from self._presets (signals blocked)."""
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("(custom)")
        for p in self._presets:
            self.preset_combo.addItem(p.name)
            self.preset_combo.setItemData(
                self.preset_combo.count() - 1, p.describe(),
                Qt.ItemDataRole.ToolTipRole)
        idx = 0
        if select:
            found = self.preset_combo.findText(select)
            idx = found if found > 0 else 0
        self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)
        self.btn_preset_del.setEnabled(idx > 0)

    def _preset_selected(self, idx: int) -> None:
        """Apply the chosen preset; index 0 is the "(custom)" placeholder."""
        if self._preset_applying:
            return
        self.btn_preset_del.setEnabled(idx > 0)
        if idx <= 0:
            self.settings.remove(LAST_PRESET_KEY)
            return
        name = self.preset_combo.itemText(idx)
        preset = presets.find(self._presets, name)
        if preset is None:
            return
        self._apply_preset(preset)
        self.settings.setValue(LAST_PRESET_KEY, name)
        self.status_label.setText(
            f"Preset “{name}” — {preset.describe()}")

    def _apply_preset(self, p: Preset) -> None:
        """Push a preset's values into every dialog control."""
        self._preset_applying = True
        try:
            if p.mode in MODE_KEYS:
                self.mode_combo.setCurrentIndex(MODE_KEYS.index(p.mode))
            if self.res_combo.findText(p.resolution) >= 0:
                self.res_combo.setCurrentText(p.resolution)
            if self.aud_combo.findText(p.audio_format) >= 0:
                self.aud_combo.setCurrentText(p.audio_format)
            self.pad_spin.setValue(p.pad)
            if self.trans_combo.findText(p.transition) >= 0:
                self.trans_combo.setCurrentText(p.transition)
            self.trans_dur.setValue(p.transition_dur)
            self.srt_check.setChecked(p.save_srt)
            self.burn_check.setChecked(p.burn_subtitles)
            self.sub_size.setValue(p.subtitle_size)
            self.notes_check.setChecked(p.notes)
            self.music_check.setChecked(p.use_music)
            self.duck_check.setChecked(p.duck_music)
            self.open_check.setChecked(p.open_folder)
        finally:
            self._preset_applying = False

    def _preset_collect(self, name: str) -> Preset:
        """Snapshot the dialog's current options into a named preset."""
        return Preset(
            name=name,
            mode=MODE_KEYS[self.mode_combo.currentIndex()],
            resolution=self.res_combo.currentText(),
            audio_format=self.aud_combo.currentText(),
            pad=self.pad_spin.value(),
            transition=self.trans_combo.currentText(),
            transition_dur=self.trans_dur.value(),
            save_srt=self.srt_check.isChecked(),
            burn_subtitles=self.burn_check.isChecked(),
            subtitle_size=self.sub_size.value(),
            notes=self.notes_check.isChecked(),
            use_music=self.music_check.isChecked(),
            duck_music=self.duck_check.isChecked(),
            open_folder=self.open_check.isChecked(),
        )

    def _preset_save(self) -> None:
        default = self.preset_combo.currentText() \
            if self.preset_combo.currentIndex() > 0 else "My preset"
        name, ok = QInputDialog.getText(
            self, "Save export preset",
            "Name this preset (stores every option shown above):",
            text=default)
        if not ok:
            return
        name = name.strip()
        if not name:
            self.status_label.setText("Preset name was empty — nothing "
                                      "saved.")
            return
        preset = self._preset_collect(name)
        self._presets = presets.upsert(self._presets, preset)
        presets.save_presets(self.settings, self._presets)
        self._rebuild_preset_combo(select=name)
        self.settings.setValue(LAST_PRESET_KEY, name)
        self.status_label.setText(
            f"✓ Preset “{name}” saved — {preset.describe()}")

    def _preset_delete(self) -> None:
        idx = self.preset_combo.currentIndex()
        if idx <= 0:
            return
        name = self.preset_combo.itemText(idx)
        self._presets = [p for p in self._presets if p.name != name]
        presets.save_presets(self.settings, self._presets)
        self._rebuild_preset_combo()
        self.settings.remove(LAST_PRESET_KEY)
        self.status_label.setText(f"Preset “{name}” deleted.")

    def _on_user_tweak(self, *_args) -> None:
        """A manual edit while a preset is shown means it's custom now."""
        if self._preset_applying:
            return
        if self.preset_combo.currentIndex() != 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(0)
            self.preset_combo.blockSignals(False)
            self.btn_preset_del.setEnabled(False)
            self.settings.remove(LAST_PRESET_KEY)

    # ------------------------------------------------------------------ #
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

    def _trans_enabled(self) -> None:
        on = self.trans_combo.currentText() != "None"
        self.trans_dur.setEnabled(on)

    def _out_row(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Choose an output file …")
        h.addWidget(self.out_edit, 1)
        btn = QPushButton("…")
        btn.setFixedWidth(34)
        btn.clicked.connect(self._pick_out)
        h.addWidget(btn)
        return w

    def _suggest_out(self) -> None:
        """Prefill the output name from the deck name + folder settings.

        Priority: a configured output folder (honouring the layout
        policy) › the last folder an export was saved to › the app's
        'output' folder, which always exists."""
        if self.out_edit.text().strip():
            return
        name = (self.deck.name or "slideshow").strip() or "slideshow"
        mode = MODE_KEYS[self.mode_combo.currentIndex()]
        if mode == "audio":
            ext = self.aud_combo.currentText()
        else:
            ext = mode
        suggestion = folders.suggest_output_path(name, ext)
        self.out_edit.setText(suggestion)
        self._last_suggest = suggestion

    def _pick_out(self) -> None:
        mode = MODE_KEYS[self.mode_combo.currentIndex()]
        if mode == "mp4":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export MP4", self.out_edit.text() or "slideshow.mp4",
                "MP4 video (*.mp4)")
        elif mode == "audio":
            fmt = self.aud_combo.currentText()
            path, _ = QFileDialog.getSaveFileName(
                self, "Export audio",
                self.out_edit.text() or f"narration.{fmt}",
                f"{fmt.upper()} audio (*.{fmt})")
        elif mode == "pdf":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PDF handout",
                self.out_edit.text() or "handout.pdf",
                "PDF (*.pdf)")
        elif mode == "pptx":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PowerPoint",
                self.out_edit.text() or "slideshow.pptx",
                "PowerPoint (*.pptx)")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export HTML slideshow",
                self.out_edit.text() or "slideshow.html",
                "HTML slideshow (*.html)")
        if path:
            self.out_edit.setText(path)
            folders.remember_folder(
                os.path.dirname(os.path.abspath(path)))

    def _mode_changed(self, idx: int) -> None:
        mode = MODE_KEYS[idx]
        video = mode == "mp4"
        audio = mode == "audio"
        document = mode in ("pdf", "pptx")
        plain_text = mode == "html"
        self._set_row_visible(self.res_row, video)
        self.res_combo.setVisible(video)
        self._set_row_visible(self.aud_row, audio)
        self.aud_combo.setVisible(audio)
        self._set_row_visible(self.trans_row, video)
        self.trans_combo.setVisible(video)
        self._set_row_visible(self.trans_dur_row, video)
        self.trans_dur.setVisible(video)
        self.burn_check.setVisible(video)
        self._set_row_visible(self.sub_size_row, video and
                              self.burn_check.isChecked())
        self.srt_check.setVisible(not document and not plain_text)
        self.notes_check.setVisible(mode == "pdf")
        self.pad_spin.setEnabled(not document and not plain_text)
        self._set_row_visible(self.pad_row, not document and not plain_text)
        self.music_check.setVisible(not document and not plain_text)
        self.duck_check.setVisible(not document and not plain_text)
        self._trans_enabled()
        # refresh auto-suggestions whose extension no longer matches the
        # chosen format; a path the user typed is never overwritten
        cur = self.out_edit.text().strip()
        if cur and self._last_suggest and \
                os.path.abspath(cur) == os.path.abspath(self._last_suggest):
            self.out_edit.clear()
        self._suggest_out()

    # ------------------------------------------------------------------ #
    def _restore_settings(self) -> None:
        s = self.settings
        self.mode_combo.setCurrentIndex(int(s.value("exp/mode_idx", 0)))
        res = s.value("exp/res")
        if res and self.res_combo.findText(res) >= 0:
            self.res_combo.setCurrentText(res)
        self.pad_spin.setValue(float(s.value("exp/pad", 0.7)))
        fmt = s.value("exp/audio_fmt")
        if fmt and self.aud_combo.findText(fmt) >= 0:
            self.aud_combo.setCurrentText(fmt)
        tr = s.value("exp/transition")
        if tr and self.trans_combo.findText(tr) >= 0:
            self.trans_combo.setCurrentText(tr)
        self.trans_dur.setValue(float(s.value("exp/trans_dur", 0.8)))
        self.srt_check.setChecked(s.value("exp/srt", "false") in (True, "true",
                                                                  "1"))
        self.burn_check.setChecked(s.value("exp/burn", "false") in
                                   (True, "true", "1"))
        self.sub_size.setValue(int(s.value("exp/sub_size", 16)))
        self.music_check.setChecked(
            bool(self.deck.music_path and
                 os.path.isfile(self.deck.music_path)) and
            s.value("exp/music", "true") in (True, "true", "1"))
        self.duck_check.setChecked(s.value("exp/duck", "true") in
                                   (True, "true", "1"))
        self.open_check.setChecked(s.value("exp/open_folder", "false") in
                                   (True, "true", "1"))
        self.notes_check.setChecked(s.value("exp/notes", "false") in
                                    (True, "true", "1"))
        self._mode_changed(self.mode_combo.currentIndex())
        # presets last: they are applied on top of the remembered widgets
        # (a fresh install is seeded with the factory preset set)
        self._presets = presets.load_presets(s)
        self._rebuild_preset_combo()
        last = str(s.value(LAST_PRESET_KEY, "") or "")
        found = self.preset_combo.findText(last) if last else -1
        self.preset_combo.setCurrentIndex(found if found > 0 else 0)

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("exp/mode_idx", self.mode_combo.currentIndex())
        s.setValue("exp/res", self.res_combo.currentText())
        s.setValue("exp/pad", self.pad_spin.value())
        s.setValue("exp/audio_fmt", self.aud_combo.currentText())
        s.setValue("exp/transition", self.trans_combo.currentText())
        s.setValue("exp/trans_dur", self.trans_dur.value())
        s.setValue("exp/srt", self.srt_check.isChecked())
        s.setValue("exp/burn", self.burn_check.isChecked())
        s.setValue("exp/sub_size", self.sub_size.value())
        s.setValue("exp/music", self.music_check.isChecked())
        s.setValue("exp/duck", self.duck_check.isChecked())
        s.setValue("exp/open_folder", self.open_check.isChecked())
        s.setValue("exp/notes", self.notes_check.isChecked())

    def _start(self) -> None:
        mode = MODE_KEYS[self.mode_combo.currentIndex()]
        out = self.out_edit.text().strip()
        if not out:
            self.status_label.setText("Choose an output file first.")
            return
        if mode in FFMPEG_MODES and not self.ffmpeg_ok:
            self.status_label.setText(
                "✗ ffmpeg is required for video/audio export — install it "
                "or choose the HTML, PDF or PPTX format.")
            return
        self._save_settings()
        self.settings.setValue("last_export_dir",
                               os.path.dirname(os.path.abspath(out)))
        folders.remember_folder(os.path.dirname(os.path.abspath(out)))
        if mode == "html":
            self._run_html_export(out)
            return
        opts = ExportOptions(
            mode=mode,
            resolution=self.res_combo.currentText(),
            pad=self.pad_spin.value(),
            use_music=self.music_check.isChecked(),
            duck_music=self.duck_check.isChecked(),
            audio_format=self.aud_combo.currentText(),
            out_path=out,
            transition=(self.trans_combo.currentText()
                        if mode == "mp4" else "None"),
            transition_dur=self.trans_dur.value(),
            save_srt=(self.srt_check.isChecked() if mode == "mp4"
                      else False),
            burn_subtitles=(self.burn_check.isChecked()
                            if mode == "mp4" else False),
            subtitle_size=self.sub_size.value(),
            notes=(self.notes_check.isChecked() if mode == "pdf"
                   else False),
        )
        self._set_running(True)
        self.progress.setValue(0)
        self.worker = ExportWorker(self.deck, opts, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _run_html_export(self, out: str) -> None:
        """HTML export needs no ffmpeg — run it inline (fast)."""
        from . import html_export
        self._set_running(True)
        self.progress.setValue(30)
        self.status_label.setText("Building standalone HTML slideshow …")
        try:
            QApplication.processEvents()
            path = html_export.export_html(self.deck, out)
        except Exception as exc:
            self._set_running(False)
            self.progress.setValue(0)
            self.status_label.setText(f"✗ HTML export failed: {exc}")
            return
        self._on_done(path)

    def _open_out(self) -> None:
        path = getattr(self, "_out_path", "")
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.status_label.setText(msg)

    def _on_done(self, path: str) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        extra = ""
        srt = os.path.splitext(path)[0] + ".srt"
        if os.path.isfile(srt):
            extra = f"  (+ {os.path.basename(srt)})"
        self.status_label.setText(f"✓ Saved to {path}{extra}")
        self.btn_open.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.btn_start.setText("Export again")
        self.btn_start.setEnabled(True)
        self._out_path = path
        self.exported.emit(path)
        if self.open_check.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(
                os.path.dirname(os.path.abspath(path))))

    def _on_failed(self, msg: str) -> None:
        self._set_running(False)
        self.status_label.setText(f"✗ {msg}")

    def _on_cancelled(self) -> None:
        self._set_running(False)
        self.status_label.setText("Export cancelled.")

    def _cancel_or_close(self) -> None:
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Cancelling …")
            self.worker.cancel()
            return
        self.reject()

    def _open_folder(self) -> None:
        path = getattr(self, "_out_path", "")
        if path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(os.path.abspath(path))))

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_start.setText("Exporting …" if running else "Start export")
        self.btn_cancel.setText("Cancel export" if running else "Close")
        music_available = bool(self.deck.music_path and
                               os.path.isfile(self.deck.music_path))
        for w in (self.mode_combo, self.res_combo, self.aud_combo,
                  self.pad_spin, self.trans_combo, self.trans_dur,
                  self.srt_check, self.burn_check, self.sub_size,
                  self.open_check, self.preset_combo,
                  self.btn_preset_save, self.btn_preset_del):
            w.setEnabled(not running)
        # the post-export actions only come alive after a real export
        has_out = bool(getattr(self, "_out_path", ""))
        self.btn_play.setEnabled(not running and has_out)
        self.btn_open.setEnabled(not running and has_out)
        self._trans_enabled()
        self.music_check.setEnabled(not running and music_available)
        self.duck_check.setEnabled(not running and music_available and
                                   self.music_check.isChecked())
