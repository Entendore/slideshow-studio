"""Text processing: SRT subtitles, TTS sanitation, script mode, find & replace."""
# ---------------------------------------------------------------- subtitles
from app import subtitles, tts_sanitize
from app.find_replace import replace_in_html, replace_in_slide
from app.models import Deck, Slide
from app.script_mode import (count_words, deck_to_script, estimate_speak_seconds,
                             parse_script, script_stats, starts_special_line)


def _slide(text):
    return Slide(title="T", narration=text)


# ---------------------------------------------------------------- subtitles
def test_slide_starts_account_for_transitions():
    starts = subtitles.slide_starts([6.0, 4.0, 3.0], 0.8)
    assert abs(starts[0]) < 1e-6
    assert abs(starts[1] - 5.2) < 1e-6          # 6.0 - 0.8
    assert abs(starts[2] - 8.4) < 1e-6          # 5.2 + 4.0 - 0.8


def test_slide_starts_without_transitions():
    starts = subtitles.slide_starts([2.0, 3.0])
    assert starts == [0.0, 2.0]


def test_build_srt_cues_timecode_and_content():
    slides = [_slide("First sentence here. Second one follows!"),
              Slide(title="Two", body="Body only text.")]
    doc = subtitles.build_srt(slides, [6.0, 4.0], subtitles.slide_starts(
        [6.0, 4.0]), pad=0.0)
    assert doc.count(" --> ") >= 2
    assert "First sentence here." in doc
    assert "Body only text." in doc
    import re
    assert re.search(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{3}",
                     doc) or re.search(r"\d{2}:\d{2}:\d{2},\d{3} -->", doc)


def test_build_srt_splits_very_long_narration():
    doc = subtitles.build_srt([_slide("word " * 120)], [10.0], [0.0], pad=0.0)
    assert doc.count(" --> ") >= 2, "long text must split into several cues"


def test_build_srt_skips_silent_slides():
    doc = subtitles.build_srt([Slide(), _slide("spoken")], [3.0, 3.0],
                              [0.0, 3.0], pad=0.0)
    assert " --> " in doc and doc.strip().splitlines()[0] == "1"


def test_build_srt_empty_narration_only_returns_nothing():
    doc = subtitles.build_srt([Slide()], [3.0], [0.0], pad=0.0)
    assert doc == ""


def test_sentence_split_merges_tiny_fragments():
    cues = subtitles._split_cues("Hi. Ok. This is a perfectly normal "
                                 "sentence of decent length.")
    assert any("Hi." in c for c in cues)
    assert all(len(c) <= subtitles.MAX_CUE_CHARS for c in cues)


# ------------------------------------------------------------- tts_sanitize
def test_emoji_removed_but_words_kept():
    out = tts_sanitize.sanitize_for_tts("Hello 🎉 world 👍‍👍")
    assert "Hello" in out and "world" in out
    assert "🎉" not in out and "\U0001F44D" not in out


def test_markdown_marks_removed():
    out = tts_sanitize.sanitize_for_tts("**bold** and _ital_ and `code` and # Head")
    assert "**" not in out and "`" not in out
    assert "bold" in out and "ital" in out and "Head" in out


def test_markdown_links_and_images():
    out = tts_sanitize.sanitize_for_tts("![logo](pic.png) see [docs](https://x.y)")
    assert "docs" in out and "](" not in out and "pic.png" not in out


def test_urls_replaced_with_link():
    out = tts_sanitize.sanitize_for_tts("visit https://example.com/x now")
    assert "https://" not in out and "link" in out
    out2 = tts_sanitize.sanitize_for_tts("see www.example.com ok")
    assert "www." not in out2 and "link" in out2


def test_symbols_become_speakable_words():
    out = tts_sanitize.sanitize_for_tts("3 × 4, 100°C, A → B, wait…")
    assert "times" in out and "×" not in out
    assert "degrees" in out and "°" not in out
    assert " to " in out
    assert "..." in out and "…" not in out


def test_abbreviations_expanded():
    out = tts_sanitize.sanitize_for_tts("e.g. Dr. Smith vs. Mr. Lee")
    assert "for example" in out and "Doctor" in out
    assert "versus" in out and "Mister" in out


def test_each_step_individually_disableable():
    keep_url = tts_sanitize.sanitize_for_tts("go https://x.y",
                                             {"urls": False})
    assert "https://x.y" in keep_url
    keep_md = tts_sanitize.sanitize_for_tts("**b**", {"markdown": False})
    assert "**b**" in keep_md
    keep_emoji = tts_sanitize.sanitize_for_tts("a 🎉 b", {"emoji": False})
    assert "🎉" in keep_emoji


def test_options_for_merges_onto_defaults():
    o = tts_sanitize.options_for(None)
    assert all(v is True for v in o.values())
    o2 = tts_sanitize.options_for({"urls": False})
    assert o2["urls"] is False and o2["emoji"] is True


def test_empty_and_whitespace_passthrough():
    assert tts_sanitize.sanitize_for_tts("") == ""
    assert tts_sanitize.sanitize_for_tts("   ") == "   "


def test_repeated_punctuation_collapsed():
    assert "!!" not in tts_sanitize.sanitize_for_tts("wow!!!")


def test_preview_pair_elides_long_text():
    orig, clean = tts_sanitize.preview_pair("word " * 200)
    assert 0 < len(orig) <= 121 and 0 < len(clean) <= 121


# -------------------------------------------------------------- script mode
def test_deck_script_roundtrip():
    d = Deck()
    d.new_slide(title="One", body="Body one.\nSecond line.",
                narration="narr one")
    d.new_slide(title="Two", body="Body two.")
    text = deck_to_script(d)
    slides = parse_script(text)
    assert len(slides) == 2
    assert slides[0].title == "One" and slides[0].narration == "narr one"
    assert "Body one." in slides[0].body and "Second line" in slides[0].body
    assert slides[1].title == "Two" and "Body two." in slides[1].body


def test_script_escapes_structural_lines():
    d = Deck()
    d.new_slide(title="Esc", body="# not a heading\n~ not narration\n"
                                  "\\ literal backslash")
    text = deck_to_script(d)
    assert "\\# not a heading" in text
    assert "\\~ not narration" in text
    slides = parse_script(text)
    assert "# not a heading" in slides[0].body
    assert "~ not narration" in slides[0].body
    assert "\\ literal backslash" in slides[0].body


def test_parse_breaks_labels_and_untitled_slides():
    text = ("# A\nbody a\n\nNotes: spoken a\n\n---\n\nNarration: spoken b\n\n"
            "***\n\nplain block")
    slides = parse_script(text)
    assert slides[0].title == "A" and slides[0].narration == "spoken a"
    assert slides[1].title == "" and slides[1].narration == "spoken b"
    assert "plain block" in slides[2].body


def test_parse_empty_input():
    assert parse_script("") == []
    assert parse_script("  \n \n ") == []


def test_starts_special_line_detection():
    for line in ("# x", "## x", "~ x", "---", "***", "===", "Notes: x",
                 "Narration: x"):
        assert starts_special_line(line), line
    for line in ("just text", "", "hash inside # mid", "3 - 4"):
        assert not starts_special_line(line), line


def test_stats_helpers():
    text = "# A\nhello world\n\n~ narration here"
    st = script_stats(text)
    assert st["slides"] == 1
    assert st["words"] == count_words(text)
    assert st["chars"] == len(text)
    assert count_words("") == 0


def test_estimate_speak_seconds_scales_with_rate():
    assert estimate_speak_seconds("") == 0.0
    base = estimate_speak_seconds("word " * 100)
    assert base > 0
    assert estimate_speak_seconds("word " * 100, rate=50) < base
    assert estimate_speak_seconds("word " * 100, rate=-50) > base


# ------------------------------------------------------------ find/replace
def test_replace_in_html_touches_text_only():
    html = '<p>red apple</p><a href="apple.com">apple link</a>'
    out, n = replace_in_html(html, "apple", "pear")
    assert n == 2                       # two text nodes, href untouched
    assert 'href="apple.com"' in out
    assert out.count("pear") == 2


def test_replace_in_html_case_insensitive():
    out, n = replace_in_html("<p>Apple apple</p>", "apple", "X",
                             case_sensitive=False)
    assert n == 2 and "<p>X X</p>" in out


def test_replace_in_html_no_match_returns_original():
    out, n = replace_in_html("<p>hello</p>", "zzz", "x")
    assert n == 0 and out == "<p>hello</p>"


def test_replace_in_html_plain_text_passthrough():
    out, n = replace_in_html("no tags here", "tags", "TAGS")
    assert n == 0 and out == "no tags here"


def test_replace_in_slide_plain_fields():
    s = Slide(title="Alpha alpha", body="the alpha body",
              narration="alpha narr")
    n = replace_in_slide(s, "alpha", "beta", case_sensitive=False)
    assert n == 4
    assert s.title == "beta beta" and s.narration == "beta narr"
    assert s.body == "the beta body"


def test_replace_in_slide_html_body_preserves_markup():
    s = Slide(title="t", body="<p>value is <b>42</b> units</p>",
              body_format="html")
    n = replace_in_slide(s, "42", "X")
    assert n == 1
    assert "<b>X</b>" in s.body and "<p>" in s.body


def test_replace_in_slide_empty_needle_is_noop():
    s = Slide(title="x", body="y", narration="z")
    assert replace_in_slide(s, "", "y") == 0
    assert (s.title, s.body, s.narration) == ("x", "y", "z")
