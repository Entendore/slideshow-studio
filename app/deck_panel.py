"""Right panel — deck-wide settings: theme designer + narration engine/voice
+ TTS text cleaning + music.

Laid out with collapsible SectionCards; every control keeps its historical
attribute name.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from . import icons, tts
from .models import PRESET_THEMES
from .widgets import SectionCard


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#4da3ff", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(64, 24)
        self.clicked.connect(self._pick)
        self._sync()

    def _sync(self) -> None:
        self.setText(self._color)
        from . import styles
        border = styles.tokens()["border_strong"]
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color}; color: #fff; "
            f"border: 1px solid {border}; border-radius: 6px; "
            f"font-size: 11px; }}")

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self._sync()

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Pick color")
        if c.isValid():
            self.set_color(c.name())
            self.colorChanged.emit(c.name())


def _row(label: str, widget) -> QHBoxLayout:
    row = QHBoxLayout()
    lab = QLabel(label)
    lab.setMinimumWidth(84)
    row.addWidget(lab)
    row.addWidget(widget, 1)
    return row


class DeckPanel(QWidget):
    deckChanged = Signal()      # theme / defaults changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck = None
        self._loading = False
        self._edge_voices: list[dict] = list(tts.FALLBACK_VOICES)
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # ---------- presentation --------------------------------------- #
        sec_pres = SectionCard("Presentation", "film")
        lay.addWidget(sec_pres)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Deck name")
        self.name_edit.textEdited.connect(self._changed)
        sec_pres.add_widget(self.name_edit)
        row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESET_THEMES.keys()))
        self.btn_apply_preset = QPushButton(icons.icon("check"), "Apply")
        self.btn_apply_preset.clicked.connect(self._apply_preset)
        row.addWidget(self.preset_combo, 1)
        row.addWidget(self.btn_apply_preset)
        sec_pres.add_layout(row)

        # ---------- background ---------------------------------------- #
        sec_bg = SectionCard("Background", "image")
        lay.addWidget(sec_bg)
        self.bg_mode = QComboBox()
        self.bg_mode.addItems(["solid", "gradient"])
        self.bg_mode.currentTextChanged.connect(self._changed)
        sec_bg.add_layout(_row("Mode", self.bg_mode))

        self.bg1 = ColorButton()
        self.bg1.colorChanged.connect(self._changed)
        self.bg2 = ColorButton()
        self.bg2.colorChanged.connect(self._changed)
        row = QHBoxLayout()
        row.addWidget(QLabel("Colors"))
        row.addWidget(self.bg1, 1)
        row.addWidget(self.bg2, 1)
        sec_bg.add_layout(row)

        self.angle_spin = QSpinBox()
        self.angle_spin.setRange(0, 360)
        self.angle_spin.setSuffix("\u00b0")
        self.angle_spin.valueChanged.connect(self._changed)
        sec_bg.add_layout(_row("Angle", self.angle_spin))

        self.overlay_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_slider.setRange(0, 90)
        self.overlay_slider.setValue(55)
        self.overlay_slider.setToolTip(
            "Dark overlay on PDF/image slides, for text readability")
        self.overlay_slider.valueChanged.connect(self._changed)
        sec_bg.add_layout(_row("Image dim", self.overlay_slider))

        # ---------- typography ----------------------------------------- #
        sec_typo = SectionCard("Typography", "script")
        lay.addWidget(sec_typo)
        fams = list(QFontDatabase.families()) or []

        self.title_font = QComboBox()
        self.title_font.setEditable(True)
        self.title_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.title_font.addItems(fams)
        self.title_font.setCurrentText("Segoe UI")
        self.title_font.currentTextChanged.connect(self._changed)
        sec_typo.add_layout(_row("Title font", self.title_font))

        self.title_size = QSpinBox()
        self.title_size.setRange(20, 130)
        self.title_size.valueChanged.connect(self._changed)
        sec_typo.add_layout(_row("Title size", self.title_size))

        self.title_color = ColorButton("#ffffff")
        self.title_color.colorChanged.connect(self._changed)
        sec_typo.add_layout(_row("Title color", self.title_color))

        self.title_bold = QCheckBox("Title bold")
        self.title_bold.toggled.connect(self._changed)
        sec_typo.add_widget(self.title_bold)

        self.body_font = QComboBox()
        self.body_font.setEditable(True)
        self.body_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.body_font.addItems(fams)
        self.body_font.setCurrentText("Segoe UI")
        self.body_font.currentTextChanged.connect(self._changed)
        sec_typo.add_layout(_row("Body font", self.body_font))

        self.body_size = QSpinBox()
        self.body_size.setRange(12, 90)
        self.body_size.valueChanged.connect(self._changed)
        sec_typo.add_layout(_row("Body size", self.body_size))

        self.body_color = ColorButton("#e6edf3")
        self.body_color.colorChanged.connect(self._changed)
        sec_typo.add_layout(_row("Body color", self.body_color))

        # ---------- accents ------------------------------------------- #
        sec_acc = SectionCard("Accents & alignment", "wand")
        lay.addWidget(sec_acc)
        self.accent_color = ColorButton("#4da3ff")
        self.accent_color.colorChanged.connect(self._changed)
        sec_acc.add_layout(_row("Accent", self.accent_color))

        self.accent_bar = QCheckBox("Show accent bar")
        self.accent_bar.setChecked(True)
        self.accent_bar.toggled.connect(self._changed)
        sec_acc.add_widget(self.accent_bar)

        self.align_combo = QComboBox()
        self.align_combo.addItems(["left", "center"])
        self.align_combo.currentTextChanged.connect(self._changed)
        sec_acc.add_layout(_row("Align", self.align_combo))

        # ---------- video overlays ------------------------------------- #
        sec_ovl = SectionCard("Video overlays", "film")
        lay.addWidget(sec_ovl)
        self.chk_numbers = QCheckBox("Slide numbers (bottom right)")
        self.chk_numbers.toggled.connect(self._changed)
        sec_ovl.add_widget(self.chk_numbers)
        self.chk_progress = QCheckBox("Progress bar (bottom edge)")
        self.chk_progress.toggled.connect(self._changed)
        sec_ovl.add_widget(self.chk_progress)
        self.watermark_edit = QLineEdit()
        self.watermark_edit.setPlaceholderText("Watermark text (bottom-left)")
        self.watermark_edit.setToolTip(
            "Small semi-transparent text on every slide — "
            "your name, brand or project title")
        self.watermark_edit.textChanged.connect(self._changed)
        sec_ovl.add_widget(self.watermark_edit)
        sec_ovl.add_widget(self._hint_overlay())

        # ---------- narration engine & voice -------------------------- #
        sec_voice = SectionCard("Narration engine & voice", "mic")
        lay.addWidget(sec_voice)
        self.engine_combo = QComboBox()
        for eng in tts.ENGINES:
            self.engine_combo.addItem(tts.ENGINE_LABELS[eng], eng)
        self.engine_combo.setToolTip(
            "edge: Microsoft neural voices (needs internet)\n"
            "Piper: free offline voices, model files download on first use\n"
            "Qwen: Alibaba Qwen3-TTS via your DashScope API key")
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        sec_voice.add_widget(self.engine_combo)

        self.voice_combo = QComboBox()
        self.voice_combo.currentTextChanged.connect(self._changed)
        sec_voice.add_widget(self.voice_combo)

        self.btn_refresh_voices = QPushButton(
            icons.icon("refresh"), "Refresh edge voice list")
        self.btn_refresh_voices.setToolTip(
            "Fetch the full online voice list from Microsoft (edge engine)")
        self.btn_refresh_voices.clicked.connect(self._refresh_voices)
        sec_voice.add_widget(self.btn_refresh_voices)

        self.piper_status = QLabel("")
        self.piper_status.setProperty("hint", True)
        self.piper_status.setWordWrap(True)
        sec_voice.add_widget(self.piper_status)

        self.qwen_key_edit = QLineEdit()
        self.qwen_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.qwen_key_edit.setPlaceholderText("DashScope API key (sk-\u2026)")
        self.qwen_key_edit.setToolTip(
            "Only the Qwen engine uses this key. It is stored in this "
            "app's settings on your computer.")
        self.qwen_key_edit.editingFinished.connect(self._qwen_key_changed)
        self.qwen_region = QComboBox()
        self.qwen_region.addItems(["International", "China"])
        self.qwen_region.setToolTip(
            "DashScope endpoint region \u2014 must match where your API "
            "key was created")
        self.qwen_region.currentIndexChanged.connect(
            self._qwen_region_changed)
        row = QHBoxLayout()
        row.addWidget(self.qwen_key_edit, 1)
        row.addWidget(self.qwen_region)
        self.qwen_row = QWidget()
        self.qwen_row.setLayout(row)
        sec_voice.add_widget(self.qwen_row)

        self.engine_hint = QLabel("")
        self.engine_hint.setProperty("hint", True)
        self.engine_hint.setWordWrap(True)
        sec_voice.add_widget(self.engine_hint)

        # ---------- TTS text cleaning --------------------------------- #
        sec_clean = SectionCard("TTS text cleaning", "check")
        lay.addWidget(sec_clean)
        self.clean_hint = QLabel(
            "Cleans the text that is *spoken* \u2014 slide text is untouched.")
        self.clean_hint.setProperty("hint", True)
        self.clean_hint.setWordWrap(True)
        sec_clean.add_widget(self.clean_hint)
        self.clean_boxes = {}
        for key, label in (
                ("emoji", "Strip emoji & pictographs"),
                ("markdown", "Strip markdown marks (**, #, ` \u2026)"),
                ("urls", "Replace URLs with \u201clink\u201d"),
                ("symbols", "Normalize symbols & punctuation"),
                ("abbrev",
                 "Expand abbreviations (e.g. \u2192 for example)")):
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._changed)
            sec_clean.add_widget(box)
            self.clean_boxes[key] = box

        # ---------- narration tools ----------------------------------- #
        sec_tools = SectionCard("Narration tools", "wand")
        lay.addWidget(sec_tools)
        row = QHBoxLayout()
        self.btn_fill_narrations = QPushButton(icons.icon("mic"),
                                               "Fill empty from text")
        self.btn_fill_narrations.setToolTip(
            "Copy each slide's title + body into its empty narration box, "
            "so you can tweak the spoken wording slide by slide")
        self.btn_fill_narrations.clicked.connect(self._fill_narrations)
        self.btn_clear_narrations = QPushButton(icons.icon("close"),
                                                "Clear all")
        self.btn_clear_narrations.setToolTip(
            "Empty every slide's narration (slides fall back to speaking "
            "title + body). One undo step restores them.")
        self.btn_clear_narrations.clicked.connect(self._clear_narrations)
        row.addWidget(self.btn_fill_narrations, 1)
        row.addWidget(self.btn_clear_narrations)
        sec_tools.add_layout(row)
        sec_tools.add_widget(self._hint_tools())

        # ---------- background music ---------------------------------- #
        sec_music = SectionCard("Background music", "music")
        lay.addWidget(sec_music)
        self.music_edit = QLineEdit()
        self.music_edit.setPlaceholderText("No music selected")
        self.music_edit.setReadOnly(True)
        sec_music.add_widget(self.music_edit)
        row = QHBoxLayout()
        self.btn_music = QPushButton(icons.icon("music"), "Choose track \u2026")
        self.btn_music.clicked.connect(self._pick_music)
        self.btn_music_clear = QPushButton(icons.icon("close"), "Remove")
        self.btn_music_clear.clicked.connect(self._clear_music)
        row.addWidget(self.btn_music)
        row.addWidget(self.btn_music_clear)
        sec_music.add_layout(row)

        self.music_vol = QSlider(Qt.Orientation.Horizontal)
        self.music_vol.setRange(0, 50)
        self.music_vol.setValue(15)
        self.music_vol.valueChanged.connect(self._changed)
        sec_music.add_layout(_row("Music vol", self.music_vol))

        lay.addStretch(1)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setProperty("heading", True)
        return lab

    @staticmethod
    def _hint_overlay() -> QLabel:
        lab = QLabel("Rendered in the editor preview, thumbnails and the "
                     "exported MP4 — WYSIWYG.")
        lab.setProperty("hint", True)
        lab.setWordWrap(True)
        return lab

    @staticmethod
    def _hint_tools() -> QLabel:
        lab = QLabel("Bulk helpers for the per-slide narration boxes.")
        lab.setProperty("hint", True)
        lab.setWordWrap(True)
        return lab

    # ------------------------------------------------------------------ #
    def set_deck(self, deck) -> None:
        self._loading = True
        self._deck = deck
        try:
            t = deck.theme
            self.name_edit.setText(deck.name)
            self.bg_mode.setCurrentText(t.background_mode)
            self.bg1.set_color(t.bg_color)
            self.bg2.set_color(t.bg_color2)
            self.angle_spin.setValue(t.gradient_angle)
            self.overlay_slider.setValue(int(t.image_overlay * 100))
            self.title_font.setCurrentText(t.title_font)
            self.title_size.setValue(t.title_size)
            self.title_color.set_color(t.title_color)
            self.title_bold.setChecked(t.title_bold)
            self.body_font.setCurrentText(t.body_font)
            self.body_size.setValue(t.body_size)
            self.body_color.set_color(t.body_color)
            self.accent_color.set_color(t.accent_color)
            self.accent_bar.setChecked(t.show_accent_bar)
            self.align_combo.setCurrentText(t.align)
            self.chk_numbers.setChecked(bool(deck.overlay_slide_numbers))
            self.chk_progress.setChecked(bool(deck.overlay_progress))
            self.watermark_edit.setText(deck.watermark_text or "")
            eng = tts.engine_of(deck.default_voice.voice)
            i = self.engine_combo.findData(eng)
            self.engine_combo.setCurrentIndex(max(0, i))
            self._populate_voices(eng)
            j = self.voice_combo.findText(deck.default_voice.voice)
            if j < 0:      # stored voice missing from catalog -> show as-is
                self.voice_combo.addItem(deck.default_voice.voice)
                j = self.voice_combo.count() - 1
            self.voice_combo.setCurrentIndex(j)
            self._sync_engine_extras(eng)
            self._load_qwen_settings()
            opts = deck.sanitize_options()
            for key, box in self.clean_boxes.items():
                box.setChecked(bool(opts.get(key, True)))
            self.music_edit.setText(deck.music_path or "")
            self.music_vol.setValue(int(deck.music_volume * 100))
        finally:
            self._loading = False

    def set_voices(self, voices: list[dict], online: bool) -> None:
        """Update the cached edge voice list (from the online refresh)."""
        self._edge_voices = list(voices)
        if tts.engine_of(self.voice_combo.currentText()) == "edge" \
                or not self.voice_combo.currentText():
            cur = self.voice_combo.currentText()
            self._populate_voices("edge")
            i = self.voice_combo.findText(cur)
            self.voice_combo.setCurrentIndex(i if i >= 0 else 0)
        self.btn_refresh_voices.setText(
            "↻  Voice list refreshed ✓" if online
            else "↻  Refresh failed — using cached voices")

    # ------------------------------------------------------------------ #
    def _apply_preset(self) -> None:
        if not self._deck:
            return
        preset = PRESET_THEMES[self.preset_combo.currentText()]
        import dataclasses
        self._deck.theme = dataclasses.replace(preset)
        self.set_deck(self._deck)
        self.deckChanged.emit()

    def _pick_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose background music", "",
            "Audio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)")
        if not path:
            return
        self._deck.music_path = path
        self.music_edit.setText(path)
        self._changed()

    def _clear_music(self) -> None:
        self._deck.music_path = None
        self.music_edit.setText("")
        self._changed()

    def _fill_narrations(self) -> None:
        """Deck-wide: copy title+body into every empty narration box."""
        if not self._deck:
            return
        win = self.window()
        filled = 0
        if hasattr(win, "apply_fill_narrations"):
            filled = win.apply_fill_narrations()
        else:                       # standalone (tests) — do it directly
            for s in self._deck.slides:
                if not (s.narration or "").strip():
                    text = s.effective_narration().strip()
                    if text:
                        s.narration = text
                        filled += 1
        self.window().statusBar().showMessage(
            f"Filled {filled} empty narration(s) from slide text.", 5000)

    def _clear_narrations(self) -> None:
        """Deck-wide: empty every narration (one undo step)."""
        if not self._deck:
            return
        win = self.window()
        if hasattr(win, "apply_clear_narrations"):
            n = win.apply_clear_narrations()
        else:
            n = 0
            for s in self._deck.slides:
                if (s.narration or "").strip():
                    s.narration = ""
                    n += 1
        self.window().statusBar().showMessage(
            f"Cleared {n} narration(s) — slides speak their text again.",
            5000)

    def _refresh_voices(self) -> None:
        self.btn_refresh_voices.setText("… fetching voice list")
        self.btn_refresh_voices.setEnabled(False)
        self._voices_thread = _VoicesThread(self)
        self._voices_thread.ready.connect(self._voices_ready)
        self._voices_thread.start()

    def _voices_ready(self, voices: list, online: bool) -> None:
        self.btn_refresh_voices.setEnabled(True)
        self.set_voices(voices, online)
        self.window().voices_loaded(voices, online)

    # ---------------- engine plumbing --------------------------------- #
    def _populate_voices(self, engine: str) -> None:
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        names = sorted({v["ShortName"]
                        for v in tts.voices_for_engine(engine,
                                                       self._edge_voices)})
        if engine == "piper":            # keep catalog order (by locale)
            names = [v["ShortName"] for v in tts.PIPER_VOICES]
        self.voice_combo.addItems(names)
        self.voice_combo.blockSignals(False)

    def _sync_engine_extras(self, engine: str) -> None:
        self.btn_refresh_voices.setVisible(engine == "edge")
        self.qwen_row.setVisible(engine == "qwen")
        if engine == "piper":
            n = tts.piper_installed_count()
            self.piper_status.setVisible(True)
            self.piper_status.setText(
                f"{n} of {len(tts.PIPER_VOICES)} voice models downloaded "
                "— missing ones fetch automatically on first use "
                "(≈60 MB each). Manage them in Tools ▸ Voice models "
                "& caches.")
            self.engine_hint.setText(
                "Piper runs fully offline. Rate and volume are applied; "
                "pitch is not available with Piper.")
        else:
            self.piper_status.setVisible(False)
        if engine == "qwen":
            self.engine_hint.setText(
                "Uses your DashScope API key (billed per character). "
                "Rate / volume / pitch are not applied by Qwen.")
        elif engine == "edge":
            self.engine_hint.setText(
                "Free Microsoft neural voices — needs internet access. "
                "Rate, volume and pitch all work.")

    def refresh_piper_status(self) -> None:
        """Public hook: re-read model counts after downloads/deletes."""
        eng = self.engine_combo.currentData()
        if eng:
            self._sync_engine_extras(eng)

    def _engine_changed(self, *args) -> None:
        eng = self.engine_combo.currentData()
        if not eng:
            return
        self._populate_voices(eng)
        self._sync_engine_extras(eng)
        self._changed()

    def _load_qwen_settings(self) -> None:
        s = QSettings("ZaiStudio", "SlideshowStudio")
        key = s.value("qwen_api_key", "") or ""
        self.qwen_key_edit.setText(str(key))
        tts.set_qwen_api_key(str(key))
        region = str(s.value("qwen_region", "International"))
        i = self.qwen_region.findText(region)
        self.qwen_region.setCurrentIndex(max(0, i))
        tts.set_qwen_region(region)

    def _qwen_key_changed(self) -> None:
        s = QSettings("ZaiStudio", "SlideshowStudio")
        s.setValue("qwen_api_key", self.qwen_key_edit.text().strip())
        tts.set_qwen_api_key(self.qwen_key_edit.text().strip())

    def _qwen_region_changed(self, *args) -> None:
        s = QSettings("ZaiStudio", "SlideshowStudio")
        s.setValue("qwen_region", self.qwen_region.currentText())
        tts.set_qwen_region(self.qwen_region.currentText())

    def _changed(self, *args) -> None:
        if self._loading or self._deck is None:
            return
        t = self._deck.theme
        t.background_mode = self.bg_mode.currentText()
        t.bg_color = self.bg1.color()
        t.bg_color2 = self.bg2.color()
        t.gradient_angle = self.angle_spin.value()
        t.image_overlay = self.overlay_slider.value() / 100.0
        t.title_font = self.title_font.currentText()
        t.title_size = self.title_size.value()
        t.title_color = self.title_color.color()
        t.title_bold = self.title_bold.isChecked()
        t.body_font = self.body_font.currentText()
        t.body_size = self.body_size.value()
        t.body_color = self.body_color.color()
        t.accent_color = self.accent_color.color()
        t.show_accent_bar = self.accent_bar.isChecked()
        t.align = self.align_combo.currentText()
        self._deck.overlay_slide_numbers = self.chk_numbers.isChecked()
        self._deck.overlay_progress = self.chk_progress.isChecked()
        self._deck.watermark_text = self.watermark_edit.text()
        if self.voice_combo.currentText():
            self._deck.default_voice.voice = self.voice_combo.currentText()
        self._deck.tts_clean_emoji = self.clean_boxes["emoji"].isChecked()
        self._deck.tts_clean_markdown = self.clean_boxes["markdown"].isChecked()
        self._deck.tts_clean_urls = self.clean_boxes["urls"].isChecked()
        self._deck.tts_clean_symbols = self.clean_boxes["symbols"].isChecked()
        self._deck.tts_clean_abbrev = self.clean_boxes["abbrev"].isChecked()
        self._deck.music_volume = self.music_vol.value() / 100.0
        self.deckChanged.emit()


class _VoicesThread(QThread):
    ready = Signal(list, bool)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self) -> None:
        from . import tts
        voices, online = tts.list_voices_sync()
        self.ready.emit(voices, online)
