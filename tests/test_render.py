"""Shared renderer, video overlays, icon set, QSS themes, widgets kit."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from app import icons, styles
from app.models import Deck, Slide, Theme
from app.render import overlay_info, render_slide, render_slide_png_bytes
from app.widgets import HRule, PanelButton, SectionCard, panel_title


# ------------------------------------------------------------------ render
def test_render_basic_sizes():
    d = Deck()
    s = d.new_slide(title="Render", body="Line one\nLine two")
    for w, h in ((1280, 720), (854, 480), (1600, 900)):
        img = render_slide(s, d.theme, w, h)
        assert not img.isNull() and img.width() == w and img.height() == h


def test_render_solid_background_exact_color():
    theme = Theme(background_mode="solid", bg_color="#112233",
                  show_accent_bar=False)
    s = Slide(title="", body="")
    img = render_slide(s, theme, 320, 180)
    assert img.pixelColor(2, 2) == QColor("#112233")


def test_render_html_body_slide():
    d = Deck()
    s = d.new_slide(title="Rich", body="<p>Rich <b>body</b></p>",
                    body_format="html")
    img = render_slide(s, d.theme, 640, 360)
    assert not img.isNull()


def test_render_image_background_slide(png_image):
    d = Deck()
    s = d.new_slide(title="Pictured")
    s.image = png_image
    img = render_slide(s, d.theme, 640, 360)
    assert not img.isNull()


def test_render_placeholder_when_no_slide():
    img = render_slide(None, Theme(), 640, 360, placeholder="Nothing here")
    assert not img.isNull()


def test_render_slide_png_bytes_are_png():
    d = Deck()
    s = d.new_slide(title="Png")
    data = render_slide_png_bytes(s, d.theme, 320, 180)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_align_center_theme():
    theme = Theme(align="center", background_mode="solid",
                  bg_color="#ffffff", title_color="#000000",
                  body_color="#000000", accent_color="#000000")
    d = Deck()
    d.theme = theme
    s = d.new_slide(title="Centred", body="text")
    assert not render_slide(s, theme, 640, 360).isNull()


# ---------------------------------------------------------------- overlays
def test_overlay_info_none_when_nothing_enabled():
    d = Deck()
    d.new_slide(title="a")
    assert overlay_info(d, 0) is None
    assert overlay_info(None, 0) is None


def test_overlay_info_describes_enabled_overlays():
    d = Deck()
    d.overlay_slide_numbers = True
    d.overlay_progress = True
    d.watermark_text = "  ACME  "
    d.new_slide(title="a")
    d.new_slide(title="b")
    ov = overlay_info(d, 5)
    assert ov["index"] == 1 and ov["total"] == 2      # clamped
    assert ov["numbers"] and ov["progress"]
    assert ov["watermark"] == "ACME"


def test_overlays_change_the_rendered_pixels():
    d = Deck()
    d.new_slide(title="Overlay", body="x")
    plain = render_slide(d.slides[0], d.theme, 640, 360)
    marked = render_slide(d.slides[0], d.theme, 640, 360,
                          overlay={"index": 0, "total": 1, "numbers": True,
                                   "progress": True, "watermark": "WM"})
    assert plain != marked


# ------------------------------------------------------------------- icons
def test_icon_catalog_draws_every_icon():
    names = icons.available()
    assert len(names) >= 10
    for name in names:
        pm = icons.pixmap(name)
        assert not pm.isNull() and pm.width() >= 16, name


def test_icons_can_be_recolored():
    pm = icons.pixmap(icons.available()[0], "#ff0000")
    assert not pm.isNull()


def test_icon_returns_qicon():
    ic = icons.icon("play")
    assert not ic.isNull()


# ------------------------------------------------------------------ styles
def test_both_themes_build_nonempty_qss():
    dark = styles.themed_qss("dark")
    light = styles.themed_qss("light")
    assert dark and light and dark != light
    assert "QMainWindow" in dark and "QMainWindow" in light


def test_apply_theme_switches_and_persists():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    saved = styles.theme_name()
    try:
        other = "light" if saved == "dark" else "dark"
        styles.apply_theme(app, other)
        assert styles.theme_name() == other
        styles.apply_theme(app, saved)
        assert styles.theme_name() == saved
    finally:
        styles.apply_theme(app, saved)


def test_design_tokens_present():
    t = styles.tokens()
    assert t and all(k in t for k in ("window", "panel", "text", "accent"))


# ----------------------------------------------------------------- widgets
def test_section_card_collapses_and_emits_signal(qtbot=None):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    card = SectionCard("Content", collapsed=False)
    assert not card.is_collapsed() and not card.body.isHidden()
    got = []
    card.toggled.connect(lambda collapsed: got.append(collapsed))
    card.header.click()
    app.processEvents()
    assert card.is_collapsed() and card.body.isHidden()
    assert got == [True]
    card.set_collapsed(False)
    assert not card.is_collapsed()


def test_section_card_fluent_builders():
    card = SectionCard("X")
    out = (card.add_widget(HRule())
           .add_rule()
           .add_stretch(0))
    assert out is card
    assert card.body.layout().count() >= 3


def test_panel_button_and_title():
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance()
    btn = PanelButton(icons.available()[0], "tooltip text")
    assert not btn.icon().isNull() and btn.toolTip() == "tooltip text"
    title = panel_title("Deck")
    assert title.property("cardTitle") is True
