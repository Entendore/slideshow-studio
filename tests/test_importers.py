"""Importers: TXT / MD / HTML / PDF / PPTX dispatch, edge cases, examples."""
import os

import pytest

from app.importers import ImportError_, import_file
from app.models import Slide


# ----------------------------------------------------------------- helpers
def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    import fitz
    path = tmp_path_factory.mktemp("pdf") / "gen.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=800, height=600)
        page.insert_textbox(fitz.Rect(60, 60, 740, 540),
                            f"PDF Page {i + 1}\n\n"
                            f"Content paragraph {i + 1} with enough text "
                            "to be extracted by the importer.")
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="module")
def sample_pptx(tmp_path_factory, png_image):
    from pptx import Presentation
    from pptx.util import Inches
    path = tmp_path_factory.mktemp("pptx") / "gen.pptx"
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Deck Title"
    s1.placeholders[1].text = "Subtitle line"
    s1.notes_slide.notes_text_frame.text = "Speaker notes here"
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Bullets"
    tf = s2.placeholders[1].text_frame
    tf.text = "first bullet"
    p = tf.add_paragraph()
    run = p.add_run()
    run.text = "bold bullet"
    run.font.bold = True
    s2.shapes.add_picture(png_image, Inches(1), Inches(2))
    prs.save(str(path))
    return str(path)


# --------------------------------------------------------------------- txt
def test_txt_headings_narration_and_escapes(tmp_path):
    p = _write(tmp_path, "t.txt",
               "# First\nBody one.\n\n~ narr one\n\n"
               "# Second\nBody two.\n\nNotes: narr two\n")
    slides = import_file(p)
    assert [s.title for s in slides] == ["First", "Second"]
    assert slides[0].narration == "narr one"
    assert slides[1].narration == "narr two"
    assert "Body two." in slides[1].body


def test_txt_separators_start_new_slides(tmp_path):
    p = _write(tmp_path, "t.txt", "para one\n\n---\n\npara two\n\n***\n\np3")
    slides = import_file(p)
    assert len(slides) == 3


def test_txt_without_headings_chunked_three_per_slide(tmp_path):
    paras = "\n\n".join(f"Paragraph number {i} with words."
                        for i in range(4))
    slides = import_file(_write(tmp_path, "t.txt", paras + "\n"))
    assert len(slides) == 2                     # 3 + 1 paragraphs
    assert "Paragraph number 0" in slides[0].body
    assert "Paragraph number 2" in slides[0].body
    assert "Paragraph number 3" in slides[1].body


def test_txt_empty_file_raises(tmp_path):
    with pytest.raises(ImportError_):
        import_file(_write(tmp_path, "t.txt", "   \n \n"))


def test_txt_missing_file_raises():
    with pytest.raises(ImportError_):
        import_file("/nonexistent/nope.txt")


def test_md_import(tmp_path):
    p = _write(tmp_path, "t.md",
               "# Alpha slide\n\nBody one.\n\n~ narr alpha\n\n"
               "## Beta slide\n\nBody two.\n")
    slides = import_file(p)
    assert len(slides) == 2
    assert slides[0].title == "Alpha slide"
    assert slides[0].narration == "narr alpha"
    assert "Body two." in slides[1].body


# -------------------------------------------------------------------- html
def test_html_splits_at_headings_and_keeps_formatting(tmp_path):
    p = _write(
        tmp_path, "t.html",
        "<html><head><style>body{}</style></head><body>"
        "<h1>One</h1><p>plain <b>bold</b> words</p>"
        "<h2>Two</h2><ul><li>item A</li><li>item B</li></ul>"
        "<h3>Three</h3><p>tail</p>"
        "</body></html>")
    slides = import_file(p)
    assert [s.title for s in slides] == ["One", "Two", "Three"]
    assert "<b>bold</b>" in slides[0].body
    assert slides[0].body_format == "html"
    assert "<li>" in slides[1].body


def test_html_scripts_and_handlers_stripped(tmp_path):
    p = _write(tmp_path, "t.html",
               "<h1>Safe</h1><p onclick='x()'>text</p><script>evil()</script>"
               "<img src='http://e/x.png' alt='pic'>")
    slides = import_file(p)
    body = slides[0].body
    assert "script" not in body.lower() and "evil" not in body
    assert "onclick" not in body
    assert "<img" not in body.lower() and "http://e" not in body


# --------------------------------------------------------------------- pdf
def test_pdf_pages_become_image_slides(sample_pdf):
    slides = import_file(sample_pdf)
    assert len(slides) == 2
    for s in slides:
        assert s.image and os.path.isfile(s.image), "page render kept"
    assert "PDF Page 1" in slides[0].body or "PDF Page 1" in slides[0].title
    assert slides[0].narration, "extracted text becomes the narration"


# -------------------------------------------------------------------- pptx
def test_pptx_notes_become_narration(sample_pptx):
    slides = import_file(sample_pptx)
    assert slides[0].narration == "Speaker notes here"
    assert slides[0].title == "Deck Title"
    assert "Subtitle line" in slides[0].body


def test_pptx_bullets_and_bold_runs(sample_pptx):
    slides = import_file(sample_pptx)
    body = slides[1].body
    assert "<li>" in body
    assert "<b>" in body


def test_pptx_picture_kept_as_background(sample_pptx):
    slides = import_file(sample_pptx)
    pict = [s for s in slides if s.image]
    assert pict, "the added picture must become a slide background"
    assert os.path.isfile(pict[0].image)


# ---------------------------------------------------------------- dispatch
def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "x.docx"
    p.write_bytes(b"whatever")
    with pytest.raises(ImportError_) as ei:
        import_file(str(p))
    assert "Unsupported" in str(ei.value)


def test_corrupt_zip_raises_import_error(tmp_path):
    p = tmp_path / "broken.pptx"
    p.write_bytes(b"PK\x03\x04 definitely not a real zip")
    with pytest.raises(ImportError_):
        import_file(str(p))


# --------------------------------------------------------------- examples
def test_every_bundled_example_loads():
    from app import paths, workspace
    found = 0
    for p in paths.list_examples():
        if p.lower().endswith(".slideshow"):
            deck = workspace.load_project(p)
            assert deck.slides, f"{p}: project without slides"
        else:
            slides = import_file(p)
            assert slides, f"{p}: importer returned no slides"
            for s in slides:
                assert s.title or s.body or s.image
        found += 1
    assert found >= 6, "examples folder must ship its sample decks"


def test_demo_project_example_is_fully_configured():
    from app import paths, workspace
    demo = os.path.join(paths.examples_dir(), "demo-tour.slideshow")
    deck = workspace.load_project(demo)
    assert len(deck.slides) >= 4
    assert any(s.narration for s in deck.slides), "demo has narration"
    assert any(s.motion != "none" for s in deck.slides), "demo has motion"
    assert any(s.body_format == "html" for s in deck.slides)
    assert deck.overlay_slide_numbers or deck.overlay_progress \
        or deck.watermark_text
