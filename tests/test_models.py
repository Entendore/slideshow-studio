"""Deck / Slide / Theme / VoiceSettings models + layout templates."""
from app.models import (BODY_FORMATS, MOTIONS, PRESET_THEMES, Deck, Slide,
                        Theme, VoiceSettings)


# ------------------------------------------------------------------ voice
def test_voice_settings_edge_args_formatting():
    vs = VoiceSettings("en-US-AriaNeural", rate=10, volume=-5, pitch=20)
    assert vs.edge_args() == {"rate": "+10%", "volume": "-5%",
                              "pitch": "+20Hz"}
    assert VoiceSettings().edge_args() == {"rate": "+0%", "volume": "+0%",
                                           "pitch": "+0Hz"}


def test_voice_engine_prefix_dispatch():
    assert VoiceSettings(voice="piper:en_US-lessac-medium").engine == "piper"
    assert VoiceSettings(voice="qwen:Cherry").engine == "qwen"
    assert VoiceSettings(voice="en-US-AriaNeural").engine == "edge"
    assert VoiceSettings(voice="").engine == "edge"


def test_voice_clone_is_independent():
    a = VoiceSettings("v", 1, 2, 3)
    b = a.clone()
    b.rate = 99
    assert a.rate == 1 and b.rate == 99


def test_voice_from_dict_empty_uses_defaults():
    vs = VoiceSettings.from_dict(None)
    assert vs.voice == "en-US-AriaNeural" and vs.rate == 0


# ------------------------------------------------------------------ slide
def test_slide_narration_fallback_plain():
    s = Slide(title="T", body="B")
    assert s.effective_narration() == "T. B"
    s2 = Slide(narration="  spoken  ")
    assert s2.effective_narration() == "spoken"
    s3 = Slide()
    assert s3.effective_narration() == ""


def test_slide_narration_fallback_strips_html():
    s = Slide(title="H", body="<p>Hello <b>world</b></p>",
              body_format="html")
    spoken = s.effective_narration()
    assert "Hello" in spoken and "world" in spoken
    assert "<" not in spoken


def test_slide_body_plain_of_html():
    s = Slide(body="<p>alpha<br>beta</p>", body_format="html")
    assert "alpha" in s.body_plain() and "beta" in s.body_plain()


def test_slide_from_dict_bad_motion_degrades_safely():
    assert Slide.from_dict({"title": "x", "motion": "bogus"}).motion == "none"


def test_slide_from_dict_recovers_body_format():
    s = Slide.from_dict({"body": "<p>rich</p>", "body_format": "wat"})
    assert s.body_format == "html"
    s2 = Slide.from_dict({"body": "just text", "body_format": "wat"})
    assert s2.body_format == "plain"


def test_slide_roundtrip_keeps_every_field():
    s = Slide(title="T", body="B", narration="N",
              voice=VoiceSettings("en-US-GuyNeural", 5, -10, 2),
              duration_override=4.2, motion="Zoom in + pan right",
              motion_intensity=0.8, body_format="html")
    s2 = Slide.from_dict(s.to_dict())
    assert s2.title == "T" and s2.narration == "N"
    assert s2.body_format in BODY_FORMATS
    assert s2.voice.voice == "en-US-GuyNeural" and s2.voice.rate == 5
    assert abs(s2.duration_override - 4.2) < 1e-6
    assert s2.motion == "Zoom in + pan right"
    assert abs(s2.motion_intensity - 0.8) < 1e-6
    assert s2.id == s.id


# ------------------------------------------------------------------ deck
def test_deck_insert_and_remove_clamp_indices():
    d = Deck()
    d.new_slide(title="a")
    d.new_slide(title="b")
    d.insert_slide(99, Slide(title="end"))
    assert d.slides[-1].title == "end"
    d.insert_slide(-5, Slide(title="top"))
    assert d.slides[0].title == "top"
    assert d.remove_slide(999) is None
    assert d.remove_slide(0).title == "top"
    assert len(d.slides) == 3


def test_deck_duplicate_gets_fresh_id():
    d = Deck()
    s = d.new_slide(title="orig", body="b", narration="n")
    dup = d.duplicate_slide(0)
    assert dup is not None and dup is not s and dup.id != s.id
    assert dup.title == "orig"
    assert d.slides[1] is dup
    assert d.duplicate_slide(42) is None


def test_deck_move_slide_reorders_and_clamps():
    d = Deck()
    for t in "abc":
        d.new_slide(title=t)
    assert d.move_slide(0, 2) is True
    assert [s.title for s in d.slides] == ["b", "c", "a"]
    assert d.move_slide(0, 0) is False                 # same spot
    assert d.move_slide(9, 0) is False                 # bad source
    assert d.move_slide(0, 99) is True                 # clamped target
    assert [s.title for s in d.slides] == ["c", "a", "b"]


def test_deck_roundtrip_overlays_cleaning_music():
    d = Deck()
    d.name = "Full"
    d.overlay_slide_numbers = True
    d.overlay_progress = True
    d.watermark_text = "wm"
    d.tts_clean_emoji = False
    d.music_volume = 0.3
    d.new_slide(title="s")
    d2 = Deck.from_dict(d.to_dict())
    assert d2.overlay_slide_numbers and d2.overlay_progress
    assert d2.watermark_text == "wm"
    assert d2.tts_clean_emoji is False and d2.tts_clean_urls is True
    assert abs(d2.music_volume - 0.3) < 1e-6
    assert d2.sanitize_options()["emoji"] is False
    assert d2.sanitize_options()["urls"] is True


def test_deck_from_dict_tolerates_missing_keys():
    d = Deck.from_dict({})
    assert d.name == "Untitled Deck" and d.slides == []
    assert d.default_voice.voice == "en-US-AriaNeural"


def test_effective_voice_prefers_slide_override():
    d = Deck()
    d.default_voice = VoiceSettings("en-US-JennyNeural", 12)
    s = d.new_slide(title="x")
    assert s.effective_voice(d).voice == "en-US-JennyNeural"
    assert s.effective_voice(d).rate == 12
    s.voice = VoiceSettings("piper:en_US-amy-medium")
    assert s.effective_voice(d).voice == "piper:en_US-amy-medium"
    assert s.has_voice_settings()


# ------------------------------------------------------------------ theme
def test_six_preset_themes_ship_with_the_app():
    assert len(PRESET_THEMES) == 6
    for t in PRESET_THEMES.values():
        assert t.name and t.title_color and t.bg_color


def test_theme_from_dict_ignores_unknown_keys():
    t = Theme.from_dict({"bg_color": "#010203", "nonsense": 1})
    assert t.bg_color == "#010203"
    assert not hasattr(t, "nonsense")


def test_theme_roundtrip_all_fields():
    t = Theme(name="X", background_mode="solid", align="center",
              image_overlay=0.7, title_bold=False)
    t2 = Theme.from_dict(t.to_dict())
    assert t2 == t


def test_motion_catalog():
    assert len(MOTIONS) >= 8 and MOTIONS[0] == "none"
    for name in ("Zoom in", "Zoom out", "Pan left", "Pan up",
                 "Zoom in + pan right", "Zoom out + pan left"):
        assert name in MOTIONS


# -------------------------------------------------------------- templates
def test_five_layout_templates_build_content_slides():
    from app.templates import (DEFAULT_TEMPLATE, TEMPLATES, make_slide,
                               template_names)
    names = template_names()
    assert len(names) == 5 and DEFAULT_TEMPLATE in names
    assert len(TEMPLATES) == len(names)
    for n in names:
        s = make_slide(n)
        assert isinstance(s, Slide)
        assert s.title or s.body, f"template {n!r} produced empty slide"
    # bullet + quote templates are rich text
    assert make_slide("Bullet list").body_format == "html"
    assert make_slide("Quote").body_format == "html"


def test_make_slide_unknown_name_falls_back_to_default():
    from app.templates import DEFAULT_TEMPLATE, make_slide
    s = make_slide("does-not-exist")
    assert s.title == make_slide(DEFAULT_TEMPLATE).title
