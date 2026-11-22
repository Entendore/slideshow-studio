"""Right panel — per-slide properties (text, narration, voice, image).

Laid out as collapsible SectionCards for a professional inspector feel;
every control keeps its historical attribute name, so behaviour (and
automation) is unchanged.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSlider, QSpinBox, QDoubleSpinBox, QTextEdit,
                               QVBoxLayout, QWidget)

from . import icons, tts
from .html_editor import HtmlBodyEditor
from .models import MOTIONS, TRANSITION_NAMES, Slide, VoiceSettings
from .script_mode import count_words, estimate_speak_seconds
from .tts_sanitize import preview_pair
from .widgets import SectionCard

DECK_DEFAULT_ITEM = "— Deck default —"


class _VoicePreviewThread(QThread):
    done = Signal(str)      # path or error message
    ok = Signal(str)

    def __init__(self, slide: Slide, deck, parent=None):
        super().__init__(parent)
        self.slide = slide
        self.deck = deck

    def run(self) -> None:
        try:
            path = tts.synthesize_cached(self.slide, self.deck)
            self.ok.emit(path)
        except RuntimeError as exc:
            self.done.emit(str(exc))


class VoicePreviewButton(QPushButton):
    """Play-the-narration button; reusable in inspector and deck panel."""

    def __init__(self, parent=None):
        super().__init__("▶  Preview voice", parent)
        self._thread: _VoicePreviewThread | None = None
        self._player: QMediaPlayer | None = None
        self._audio: QAudioOutput | None = None
        self.slide: Slide | None = None
        self.deck = None
        self.clicked.connect(self._start)

    def _start(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        if self.slide is None or self.deck is None:
            return
        self.setText("… synthesizing")
        self.setEnabled(False)
        self._thread = _VoicePreviewThread(self.slide, self.deck, self)
        self._thread.ok.connect(self._play)
        self._thread.done.connect(self._error)
        self._thread.start()

    def _style(self) -> None:
        self.setIcon(icons.icon("play"))
        self.setProperty("primary", True)

    def _play(self, path: str) -> None:
        self._reset()
        try:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.setSource(QUrl_from_local(path))
            self._player.mediaStatusChanged.connect(
                lambda st: self._maybe_reset(st))
            self._audio.setVolume(1.0)
            self._player.play()
        except Exception:
            self.setText("▶  Preview voice")
            self.setEnabled(True)

    def _maybe_reset(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer as _QMP
        if status == _QMP.MediaStatus.EndOfMedia:
            self._reset()

    def _error(self, msg: str) -> None:
        self._reset()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Voice preview failed", msg)

    def _reset(self) -> None:
        self.setText("▶  Preview voice")
        self.setEnabled(True)

    def stop(self) -> None:
        if self._player:
            self._player.stop()


def QUrl_from_local(path: str):
    from PySide6.QtCore import QUrl
    return QUrl.fromLocalFile(path)


class SlideInspector(QWidget):
    """Editor bound to the currently selected slide."""
    slideChanged = Signal()          # any field edited

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slide: Slide | None = None
        self._deck = None
        self._loading = False
        self._edge_voices: list[dict] = list(tts.FALLBACK_VOICES)
        self._cur_engine = "edge"
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # ---------------- content ------------------------------------- #
        sec_content = SectionCard("Content", "script")
        lay.addWidget(sec_content)
        self.title_edit = QLineEdit()
        sec_content.add_widget(self.title_edit)
        self.title_edit.setPlaceholderText("Slide title")
        self.title_edit.textEdited.connect(self._changed)
        sec_content.add_widget(self._hint(
            "Body — rich text (HTML). Formatting, lists and colours; "
            "auto-shrinks to fit."))
        self.body_editor = HtmlBodyEditor()
        self.body_editor.changed.connect(self._changed)
        sec_content.add_widget(self.body_editor)

        # ---------------- narration ----------------------------------- #
        sec_narr = SectionCard("Narration", "mic")
        lay.addWidget(sec_narr)
        self.narr_edit = QTextEdit()
        self.narr_edit.setAcceptRichText(False)
        self.narr_edit.setPlaceholderText(
            "Leave empty to speak the title + body instead …")
        self.narr_edit.setFixedHeight(90)
        self.narr_edit.textChanged.connect(self._changed)
        sec_narr.add_widget(self.narr_edit)
        self.spoken_preview = QLabel("")
        self.spoken_preview.setProperty("hint", True)
        self.spoken_preview.setWordWrap(True)
        self.spoken_preview.setToolTip(
            "The text after TTS cleaning (Deck & Theme ▸ TTS text cleaning) "
            "— this is what the voice will read")
        sec_narr.add_widget(self.spoken_preview)
        row = QHBoxLayout()
        self.btn_use_slide_text = QPushButton(
            icons.icon("script"), "Use slide text")
        self.btn_use_slide_text.setToolTip(
            "Fill the narration with title + body, then tweak it")
        self.btn_use_slide_text.clicked.connect(self._use_slide_text)
        row.addWidget(self.btn_use_slide_text)
        row.addStretch(1)
        self.narr_count = QLabel("0 chars")
        self.narr_count.setProperty("hint", True)
        row.addWidget(self.narr_count)
        sec_narr.add_layout(row)

        # ---------------- motion ------------------------------------- #
        sec_motion = SectionCard("Motion & transition", "wand")
        lay.addWidget(sec_motion)
        self.motion_combo = QComboBox()
        self.motion_combo.addItems(MOTIONS)
        self.motion_combo.setToolTip("Animated zoom / pan applied when "
                                     "exporting the MP4")
        self.motion_combo.currentTextChanged.connect(self._changed)
        sec_motion.add_widget(self.motion_combo)
        row = QHBoxLayout()
        row.addWidget(QLabel("Intensity"))
        self.motion_slider = QSlider(Qt.Orientation.Horizontal)
        self.motion_slider.setRange(5, 100)
        self.motion_slider.setValue(50)
        self.motion_slider.valueChanged.connect(self._changed)
        row.addWidget(self.motion_slider, 1)
        sec_motion.add_layout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Enter via"))
        self.trans_combo = QComboBox()
        self.trans_combo.addItem(DECK_DEFAULT_ITEM, "")
        for _t in TRANSITION_NAMES:
            self.trans_combo.addItem(_t, _t)
        self.trans_combo.setToolTip(
            "How this slide enters during the MP4 export — animated "
            "transition from the previous slide. \"Deck default\" uses "
            "the transition chosen in the export dialog; \"None\" forces "
            "a hard cut.")
        self.trans_combo.currentIndexChanged.connect(self._changed)
        row.addWidget(self.trans_combo, 1)
        sec_motion.add_layout(row)
        sec_motion.add_widget(self._hint(
            "Applied during MP4 export — the editor preview stays still."))

        # ---------------- voice ------------------------------------- #
        sec_voice = SectionCard("Voice", "music")
        lay.addWidget(sec_voice)
        self.engine_combo = QComboBox()
        self.engine_combo.addItem(DECK_DEFAULT_ITEM, "")
        for eng in tts.ENGINES:
            self.engine_combo.addItem(tts.ENGINE_SHORT[eng], eng)
        self.engine_combo.setToolTip(
            "Override the TTS engine for this slide — leave on “Deck "
            "default” to follow the Deck & Theme setting")
        self.engine_combo.currentIndexChanged.connect(self._engine_changed)
        sec_voice.add_widget(self.engine_combo)

        self.voice_combo = QComboBox()
        self.voice_combo.currentTextChanged.connect(self._changed)
        sec_voice.add_widget(self.voice_combo)

        self._sliders = {}
        self._slider_vals = {}
        for key, label, lo, hi, suffix in (
                ("rate", "Rate", -50, 50, "%"),
                ("volume", "Volume", -100, 50, "%"),
                ("pitch", "Pitch", -50, 50, " Hz")):
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setMinimumWidth(48)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            val = QLabel("0" + suffix)
            val.setMinimumWidth(52)
            val.setAlignment(Qt.AlignmentFlag.AlignRight |
                             Qt.AlignmentFlag.AlignVCenter)
            slider.valueChanged.connect(self._changed)
            slider.valueChanged.connect(
                lambda v, l=val, s=suffix: l.setText(f"{v:+d}{s}"))
            row.addWidget(lab)
            row.addWidget(slider, 1)
            row.addWidget(val)
            sec_voice.add_layout(row)
            self._sliders[key] = slider
            self._slider_vals[key] = val

        self.btn_preview = VoicePreviewButton()
        self.btn_preview._style()
        sec_voice.add_widget(self.btn_preview)
        self.btn_reset_voice = QPushButton(
            icons.icon("refresh"), "Reset voice to deck default")
        self.btn_reset_voice.clicked.connect(self._reset_voice)
        sec_voice.add_widget(self.btn_reset_voice)
        self.btn_voice_all = QPushButton(
            icons.icon("copy"), "Apply voice to all slides")
        self.btn_voice_all.setToolTip("Copy this slide's voice settings to "
                                      "every slide in the deck")
        self.btn_voice_all.clicked.connect(self._apply_voice_to_all)
        sec_voice.add_widget(self.btn_voice_all)

        # ---------------- timing ------------------------------------- #
        sec_time = SectionCard("Timing", "clock")
        lay.addWidget(sec_time)
        row = QHBoxLayout()
        row.addWidget(QLabel("Duration"))
        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setRange(0.0, 600.0)
        self.dur_spin.setSingleStep(0.5)
        self.dur_spin.setSuffix(" s")
        self.dur_spin.setSpecialValueText("Auto (narration)")
        self.dur_spin.valueChanged.connect(self._changed)
        row.addWidget(self.dur_spin, 1)
        sec_time.add_layout(row)

        # ---------------- image -------------------------------------- #
        sec_img = SectionCard("Background image", "image")
        lay.addWidget(sec_img)
        self.img_label = QLabel("None")
        self.img_label.setProperty("hint", True)
        self.img_label.setWordWrap(True)
        sec_img.add_widget(self.img_label)
        row = QHBoxLayout()
        self.btn_img = QPushButton(icons.icon("image"), "Choose …")
        self.btn_img.clicked.connect(self._pick_image)
        self.btn_img_clear = QPushButton(icons.icon("close"), "Remove")
        self.btn_img_clear.clicked.connect(self._clear_image)
        row.addWidget(self.btn_img)
        row.addWidget(self.btn_img_clear)
        sec_img.add_layout(row)

        lay.addStretch(1)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _heading(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setProperty("heading", True)
        return lab

    @staticmethod
    def _hint(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setProperty("hint", True)
        return lab

    # ------------------------------------------------------------------ #
    def set_deck(self, deck) -> None:
        self._deck = deck
        self.btn_preview.deck = deck

    def set_voices(self, voices: list[dict]) -> None:
        self._edge_voices = list(voices)
        if getattr(self, "_cur_engine", "edge") == "edge":
            cur = self.voice_combo.currentText()
            self._populate_voices("edge")
            i = self.voice_combo.findText(cur)
            self.voice_combo.setCurrentIndex(max(0, i))

    def set_slide(self, slide: Slide | None) -> None:
        self._loading = True
        self._slide = slide
        try:
            if slide is None:
                self.setEnabled(False)
                return
            self.setEnabled(True)
            self.title_edit.setText(slide.title)
            self.body_editor.set_content(slide.body, slide.body_format)
            self.narr_edit.setPlainText(slide.narration)
            vs = slide.voice
            deck_voice = (self._deck.default_voice.voice
                          if self._deck else "en-US-AriaNeural")
            eng = vs.engine if vs is not None else tts.engine_of(deck_voice)
            # engine selector + voice list for that engine
            self.engine_combo.blockSignals(True)
            self.engine_combo.setCurrentIndex(
                0 if vs is None else 1 + tts.ENGINES.index(eng))
            self._populate_voices(eng)
            self.engine_combo.blockSignals(False)
            voice_id = vs.voice if vs is not None else deck_voice
            i = self.voice_combo.findText(voice_id)
            if i >= 0:
                self.voice_combo.setCurrentIndex(i)
            else:
                if self.voice_combo.findText(voice_id) < 0:
                    self.voice_combo.addItem(voice_id)
                self.voice_combo.setCurrentText(voice_id)
            if vs is None:
                for key in self._sliders:
                    self._sliders[key].setValue(0)
            else:
                self._sliders["rate"].setValue(vs.rate)
                self._sliders["volume"].setValue(vs.volume)
                self._sliders["pitch"].setValue(vs.pitch)
            self._gate_sliders(eng)
            self.dur_spin.setValue(slide.duration_override)
            self.motion_combo.setCurrentText(
                slide.motion if slide.motion in MOTIONS else "none")
            self.motion_slider.setValue(
                int(max(0.05, min(1.0, slide.motion_intensity)) * 100))
            ti = self.trans_combo.findData(slide.transition or "")
            self.trans_combo.setCurrentIndex(ti if ti >= 0 else 0)
            self.img_label.setText(
                os.path.basename(slide.image) if slide.image else "None")
            self.btn_preview.slide = slide
            self._update_count()
        finally:
            self._loading = False

    # ------------------------------------------------------------------ #
    def _update_count(self) -> None:
        text = self.narr_edit.toPlainText()
        words = count_words(text)
        chars = len(text.strip())
        if chars:
            rate = self._sliders["rate"].value() if "rate" in self._sliders else 0
            secs = estimate_speak_seconds(text, rate)
            self.narr_count.setText(
                f"{words} words · {chars} chars · ~{secs:.0f}s speech")
        else:
            self.narr_count.setText("0 words · 0 chars")
        # spoken-text preview (after TTS cleaning)
        opts = self._deck.sanitize_options() if self._deck else None
        orig, clean = preview_pair(
            text if text.strip() else
            (self._slide.effective_narration() if self._slide else ""),
            opts)
        if clean:
            self.spoken_preview.setText(f"Speaks: {clean}")
        else:
            self.spoken_preview.setText("")

    # ---------------- engine plumbing --------------------------------- #
    def _populate_voices(self, engine: str) -> None:
        self._cur_engine = engine
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        names = sorted({v["ShortName"]
                        for v in tts.voices_for_engine(engine,
                                                       self._edge_voices)})
        self.voice_combo.addItems(names)
        self.voice_combo.blockSignals(False)

    def _engine_changed(self, *args) -> None:
        if self._loading or self._slide is None:
            return
        data = self.engine_combo.currentData()
        if not data:      # "— Deck default —"
            eng = (tts.engine_of(self._deck.default_voice.voice)
                   if self._deck else "edge")
            voice_id = (self._deck.default_voice.voice
                        if self._deck else "en-US-AriaNeural")
        else:
            eng = data
            voice_id = tts.voices_for_engine(eng, self._edge_voices)[0][
                "ShortName"]
        self._populate_voices(eng)
        i = self.voice_combo.findText(voice_id)
        self.voice_combo.setCurrentIndex(max(0, i))
        self._gate_sliders(eng)
        self._changed()

    def _gate_sliders(self, engine: str) -> None:
        caps = {"edge": (True, True, True),
                "piper": (True, True, False),
                "qwen": (False, False, False)}
        for key, allowed in zip(("rate", "volume", "pitch"),
                                caps.get(engine, (True, True, True))):
            self._sliders[key].setEnabled(allowed)
            self._slider_vals[key].setEnabled(allowed)
            if not allowed:
                self._sliders[key].setValue(0)

    def _use_slide_text(self) -> None:
        if not self._slide:
            return
        self.narr_edit.setPlainText(self._slide.effective_narration())
        # textChanged already fired _changed

    def _reset_voice(self) -> None:
        if not self._slide:
            return
        self._slide.voice = None
        self.set_slide(self._slide)
        self.slideChanged.emit()

    def _apply_voice_to_all(self) -> None:
        """Copy this slide's effective voice settings to every slide."""
        if not self._slide or not self._deck:
            return
        vs = self._slide.effective_voice(self._deck)
        for s in self._deck.slides:
            s.voice = vs.clone()
        self.set_slide(self._slide)
        self.slideChanged.emit()

    def _pick_image(self) -> None:
        if not self._slide:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose background image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        from .workspace import stage_media
        self._slide.image = stage_media(path)
        self.img_label.setText(os.path.basename(path))
        self.slideChanged.emit()

    def _clear_image(self) -> None:
        if not self._slide:
            return
        self._slide.image = None
        self.img_label.setText("None")
        self.slideChanged.emit()

    def _changed(self, *args) -> None:
        if self._loading or self._slide is None:
            return
        self._slide.title = self.title_edit.text()
        body, fmt = self.body_editor.content()
        self._slide.body = body
        self._slide.body_format = fmt
        self._slide.narration = self.narr_edit.toPlainText()
        voice_text = self.voice_combo.currentText()
        deck_voice = (self._deck.default_voice.voice
                      if self._deck else "en-US-AriaNeural")
        rate = self._sliders["rate"].value()
        vol = self._sliders["volume"].value()
        pitch = self._sliders["pitch"].value()
        if (voice_text and voice_text != deck_voice) or rate or vol or pitch:
            self._slide.voice = VoiceSettings(
                voice=voice_text or deck_voice,
                rate=rate, volume=vol, pitch=pitch)
        else:
            self._slide.voice = None
        self._slide.duration_override = self.dur_spin.value()
        self._slide.motion = (self.motion_combo.currentText()
                              if self.motion_combo.currentText() in MOTIONS
                              else "none")
        self._slide.motion_intensity = self.motion_slider.value() / 100.0
        self._slide.transition = self.trans_combo.currentData() or ""
        self.btn_preview.slide = self._slide
        self._update_count()
        self.slideChanged.emit()
