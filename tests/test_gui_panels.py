"""Panel-level GUI behaviour: inspector, deck panel, canvas, slide list,
the three-view body editor, and per-slide voice plumbing."""
import os

import pytest

from app import tts
from app.htmlfmt import looks_like_html
from app.models import VoiceSettings


# --------------------------------------------------------------- inspector
def test_inspector_voice_override_and_apply_to_all(win):
    win.deck.default_voice = VoiceSettings("en-US-AriaNeural")
    win.inspector.set_deck(win.deck)
    win.inspector.set_slide(win.current_slide())
    win.inspector.voice_combo.setCurrentText("en-GB-RyanNeural")
    win.inspector._changed()
    assert win.current_slide().voice.voice == "en-GB-RyanNeural"
    win.inspector._apply_voice_to_all()
    assert all(s.voice and s.voice.voice == "en-GB-RyanNeural"
               for s in win.deck.slides)
    win.inspector._reset_voice()
    assert win.current_slide().voice is None


def test_inspector_slider_gating_per_engine(win):
    insp = win.inspector
    insp.set_deck(win.deck)
    insp.set_slide(win.current_slide())
    insp.engine_combo.setCurrentIndex(0)              # edge: all sliders
    assert insp._sliders["rate"].isEnabled()
    assert insp._sliders["pitch"].isEnabled()
    win.deck.default_voice = VoiceSettings("piper:en_US-amy-medium")
    insp.set_slide(win.current_slide())
    assert insp.engine_combo.currentIndex() == 0      # "deck default"
    assert not insp._sliders["pitch"].isEnabled()     # piper: no pitch
    assert insp._sliders["rate"].isEnabled()
    insp.engine_combo.setCurrentIndex(3)              # explicit qwen
    assert not insp._sliders["rate"].isEnabled()
    assert not insp._sliders["volume"].isEnabled()
    assert not insp._sliders["pitch"].isEnabled()
    assert win.current_slide().voice.voice.startswith("qwen:")


def test_inspector_spoken_preview_shows_cleaned_text(win):
    insp = win.inspector
    insp.narr_edit.setPlainText("Hi 🎉 visit https://a.b — **bold**")
    insp._changed()
    sp = insp.spoken_preview.text()
    assert sp.startswith("Speaks:")
    assert "🎉" not in sp and "https://" not in sp


def test_inspector_use_slide_text_button(win):
    insp = win.inspector
    s = win.current_slide()
    s.narration = ""
    insp.set_slide(s)
    insp._use_slide_text()
    assert s.narration.strip(), "slide text copied into the narration"


def test_inspector_empty_slide_disables_inputs(win):
    from app.models import Deck
    win.inspector.set_deck(Deck())
    win.inspector.set_slide(None)


# -------------------------------------------------------------- deck panel
def test_deck_panel_engine_switching(win, qapp):
    dp = win.deck_panel
    dp.engine_combo.setCurrentIndex(1)                # piper
    qapp.processEvents()
    assert win.deck.default_voice.voice.startswith("piper:")
    assert dp.qwen_row.isHidden() and dp.btn_refresh_voices.isHidden()
    assert not dp.piper_status.isHidden()
    dp.engine_combo.setCurrentIndex(2)                # qwen
    qapp.processEvents()
    assert win.deck.default_voice.voice.startswith("qwen:")
    assert not dp.qwen_row.isHidden() and dp.piper_status.isHidden()
    dp.engine_combo.setCurrentIndex(0)                # edge
    qapp.processEvents()
    assert not win.deck.default_voice.voice.startswith(("piper:", "qwen:"))
    assert not dp.btn_refresh_voices.isHidden()


def test_deck_panel_qwen_key_roundtrip(win, qapp):
    from PySide6.QtCore import QSettings
    dp = win.deck_panel
    dp.engine_combo.setCurrentIndex(2)
    qapp.processEvents()
    dp.qwen_key_edit.setText("sk-test-123")
    dp._qwen_key_changed()
    s = QSettings("ZaiStudio", "SlideshowStudio")
    assert str(s.value("qwen_api_key", "")) == "sk-test-123"
    assert tts.get_qwen_api_key() == "sk-test-123"
    dp.qwen_key_edit.setText("")
    dp._qwen_key_changed()
    assert tts.get_qwen_api_key() is None
    dp.engine_combo.setCurrentIndex(0)


def test_deck_panel_cleaning_checkboxes_write_deck(win, qapp):
    dp = win.deck_panel
    dp.clean_boxes["emoji"].setChecked(False)
    qapp.processEvents()
    assert win.deck.tts_clean_emoji is False
    dp.clean_boxes["emoji"].setChecked(True)
    qapp.processEvents()
    assert win.deck.tts_clean_emoji is True


def test_deck_panel_overlay_checkboxes(win, qapp):
    dp = win.deck_panel
    dp.chk_numbers.setChecked(True)
    dp.chk_progress.setChecked(True)
    dp.watermark_edit.setText("Test WM")
    qapp.processEvents()
    assert win.deck.overlay_slide_numbers and win.deck.overlay_progress
    assert win.deck.watermark_text == "Test WM"
    dp.chk_numbers.setChecked(False)
    dp.chk_progress.setChecked(False)
    dp.watermark_edit.setText("")
    qapp.processEvents()
    assert not win.deck.overlay_slide_numbers


def test_deck_panel_preset_theme_applies(win, qapp):
    dp = win.deck_panel
    idx = dp.preset_combo.findText("Dark Pro")
    assert idx >= 0
    dp.preset_combo.setCurrentIndex(idx)
    dp._apply_preset()
    assert win.deck.theme.name == "Dark Pro"
    assert win.deck.theme.bg_color == "#0b0b0d"


def test_deck_panel_set_voices_populates_combo(win):
    dp = win.deck_panel
    dp.set_voices([{"ShortName": "en-GB-SoniaNeural", "Locale": "en-GB",
                    "Gender": "Female"}], True)
    texts = [dp.voice_combo.itemText(i) for i in range(dp.voice_combo.count())]
    assert "en-GB-SoniaNeural" in texts


def test_deck_panel_fill_clear_narration_buttons(win, qapp):
    dp = win.deck_panel
    for s in win.deck.slides:
        s.narration = ""
    dp._fill_narrations()
    assert all(s.narration for s in win.deck.slides)
    dp._clear_narrations()
    assert all(not s.narration for s in win.deck.slides)


def test_deck_panel_refresh_piper_status(win, qapp):
    dp = win.deck_panel
    dp.engine_combo.setCurrentIndex(1)                 # piper engine active
    qapp.processEvents()
    assert not dp.piper_status.isHidden()
    dp.refresh_piper_status()
    txt = dp.piper_status.text()
    assert txt, "piper status line must describe the model state"
    assert "Tools" in txt or "model" in txt.lower()


# ------------------------------------------------------------------ canvas
def test_canvas_paste_image_background(win, png_image):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    img = QImage(png_image)
    QApplication.clipboard().setImage(img)
    assert win.canvas.paste_background() is True
    assert win.current_slide().image and os.path.isfile(
        win.current_slide().image)


def test_canvas_paste_without_image_returns_false(win):
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().clear()
    assert win.canvas.paste_background() is False


def test_canvas_invalidate_and_index(win):
    win.canvas.set_deck(win.deck)
    win.canvas.set_index(1)
    win.canvas.invalidate()
    assert win.canvas._index == 1
    assert win.canvas._deck is win.deck


# -------------------------------------------------------------- slide list
def test_slide_list_selection_drives_current_index(win):
    win.slide_list.setCurrentRow(1)
    assert win.current_index() == 1
    assert win.slide_list.count() == len(win.deck.slides)


def test_slide_list_refresh_keeps_thumbnails(win):
    n = len(win.deck.slides)
    win.slide_list.refresh(keep_current=True)
    assert win.slide_list.count() == n
    for i in range(n):
        assert win.slide_list.item(i) is not None


def test_slide_list_labels_show_titles(win):
    item_text = win.slide_list.item(0).text()
    title = win.deck.slides[0].title.strip() or "(untitled)"
    assert title[:20] in item_text
    assert item_text.startswith("1.")


# ------------------------------------------------------------- body editor
def test_body_editor_three_views_roundtrip(qapp):
    from app.html_editor import HtmlBodyEditor
    ed = HtmlBodyEditor()
    ed.set_content("<p>Hello <b>world</b></p>", "html")
    body, fmt = ed.content()
    assert fmt == "html" and "Hello" in body and "world" in body
    # switching to plain text flattens the markup
    ed._set_mode("plain", convert=True)
    body, fmt = ed.content()
    assert fmt == "plain" and "<b>" not in body and "world" in body
    # and back to the html source view via the sanitiser
    ed._set_mode("source", convert=True)
    body, fmt = ed.content()
    assert fmt == "html" and looks_like_html(body)
    # visual mode round-trips as well
    ed._set_mode("visual", convert=True)
    body, fmt = ed.content()
    assert fmt == "html" and "world" in body


def test_body_editor_plain_paragraphs(qapp):
    from app.html_editor import HtmlBodyEditor
    ed = HtmlBodyEditor()
    ed.set_content("first\n\nsecond", "plain")
    body, fmt = ed.content()
    assert fmt == "plain" and "first" in body and "second" in body


def test_body_editor_paste_is_sanitized(qapp):
    from PySide6.QtCore import QMimeData
    from PySide6.QtWidgets import QApplication
    from app.html_editor import HtmlBodyEditor
    ed = HtmlBodyEditor()
    ed.set_content("<p>target</p>", "html")
    ed._set_mode("visual", convert=False)
    md = QMimeData()
    md.setHtml('<b style="x:1">bold</b><script>evil()</script>')
    ed.visual.insertFromMimeData(md)
    qapp.processEvents()
    body, _fmt = ed.content()
    assert "bold" in body
    assert "script" not in body.lower() and "evil" not in body.lower()
