"""The sanitised rich-text HTML subset (app/htmlfmt.py)."""
from app.htmlfmt import (filter_style, html_to_plain, looks_like_html,
                         plain_to_html, sanitize_html)


# ------------------------------------------------------------------ safety
def test_script_and_event_handlers_removed():
    dirty = ('<p onclick="evil()">hi</p><script>alert(1)</script>'
             '<img src="http://evil/x.png" alt="logo">')
    out = sanitize_html(dirty)
    assert "script" not in out.lower()
    assert "onclick" not in out.lower()
    assert "evil()" not in out
    assert "<img" not in out.lower()          # external resources dropped
    assert "logo" in out                      # alt text survives


def test_iframe_style_objects_removed():
    out = sanitize_html('<iframe src="http://x"></iframe>'
                        '<style>p{}</style><p>kept</p>')
    assert "iframe" not in out.lower()
    assert "<style" not in out.lower()
    assert "kept" in out


def test_unknown_tags_unwrapped_children_kept():
    out = sanitize_html("<article><p>text</p></article>")
    assert "article" not in out and "text" in out


def test_comments_and_doctype_removed():
    out = sanitize_html("<!-- secret --><p>visible</p>")
    assert "secret" not in out and "visible" in out


def test_plain_text_wrapped_into_paragraphs():
    assert sanitize_html("just text") == "<p>just text</p>"


def test_empty_input_returns_empty():
    assert sanitize_html("") == ""
    assert sanitize_html("   ") == ""


# ------------------------------------------------------------- attributes
def test_safe_links_kept_unsafe_removed():
    ok = sanitize_html('<a href="https://ok.example">l</a>')
    assert 'href="https://ok.example"' in ok
    mail = sanitize_html('<a href="mailto:a@b.c">m</a>')
    assert 'href="mailto:a@b.c"' in mail
    bad = sanitize_html('<a href="javascript:alert(1)">x</a>')
    assert "javascript:" not in bad


def test_style_filter_whitelists_keys():
    keep = filter_style("color: red; font-size: 99px; background: url(x)")
    assert "color: red" in keep
    assert "font-size" not in keep and "url(" not in keep


def test_style_filter_blocks_dangerous_values():
    assert "expression" not in filter_style("color: expression(evil)")
    assert "javascript" not in filter_style("color: javascript:red")
    assert filter_style("text-align: sideways") == ""
    assert "font-weight: 700" in filter_style("font-weight: 700")


def test_align_attribute_becomes_css():
    out = sanitize_html('<p align="center">c</p>')
    assert "text-align: center" in out


def test_formatting_spans_normalized_to_tags():
    out = sanitize_html('<span style="font-weight: bold;">B</span>'
                        '<span style="font-style: italic;">I</span>')
    assert "<b>B</b>" in out and "<i>I</i>" in out


# ------------------------------------------------------------ plain tools
def test_html_to_plain_lists_and_breaks():
    plain = html_to_plain("<ul><li>one</li><li>two</li></ul><p>para</p>")
    assert "• one" in plain and "• two" in plain and "para" in plain


def test_html_to_plain_drops_script_content():
    plain = html_to_plain("<p>keep</p><script>evil()</script>")
    assert "keep" in plain and "evil" not in plain


def test_plain_to_html_paragraphs_and_escapes():
    h = plain_to_html("first para\nline two\n\nsecond")
    assert h.count("<p>") == 2 and "<br>" in h
    h2 = plain_to_html("a < b & c")
    assert "&lt;" in h2 and "&amp;" in h2


def test_plain_to_html_empty():
    assert plain_to_html("") == ""
    assert plain_to_html("  \n ") == ""


def test_looks_like_html_heuristic():
    assert looks_like_html("<p>x</p>")
    assert looks_like_html("line one<br>two")
    assert not looks_like_html("plain words only")
    assert not looks_like_html("2 < 3 and 4 > 1")
