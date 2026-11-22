"""Document exports: PDF handouts and PowerPoint decks.

Both formats are built from the same slide renderer used by the canvas,
thumbnails and the MP4 pipeline, so what you see in the editor is exactly
what lands on the page/slide.

  PDF handout   one 16:9 page per slide, optionally interleaved with
                notes pages (slide thumbnail on top, the text that would
                be spoken below). No ffmpeg needed — great for sharing,
                printing and handouts.
  PowerPoint    a real .pptx (16:9) with the rendered slide as a
                full-bleed picture and the narration pre-filled into the
                speaker-notes pane, so the deck stays presentable and
                editable in PowerPoint, Google Slides or LibreOffice.

Rendering needs a QApplication (fonts), but no event loop and no ffmpeg.
Every helper takes an optional ``check`` callable so a running export can
be cancelled between slides, and an ``on_progress(done, total)`` callback
for live status.
"""
from __future__ import annotations

import os

from . import folders
from .models import Deck
from .render import overlay_info, render_slide

# page geometry (PDF points and PPTX EMU are derived from the 16:9 frame)
PAGE_W = 960.0            # 13.33 in × 72 — standard 16:9 slide page
PAGE_H = 540.0

# render width for embedded page images (px) — crisp on print and zoom
RENDER_W = 2000

PDF_NOTE_FONT = "helv"
NOTES_BG = "#f7f8fa"
NOTES_TEXT = "#2c3a47"


def _rgb(hex_color: str) -> tuple[float, float, float]:
    """'#rrggbb' -> (r, g, b) floats in 0..1 (PyMuPDF colour format)."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


# ------------------------------------------------------------------ #
# shared rendering
# ------------------------------------------------------------------ #
def _render_pages(deck: Deck, on_progress=None, check=None
                  ) -> tuple[str, list[str]]:
    """Render every slide to a PNG inside the managed working folder.

    Returns ``(scratch_dir, png_paths)``; the caller removes the scratch
    folder when done."""
    tmp = folders.new_temp_dir("docs")
    paths: list[str] = []
    try:
        n = len(deck.slides)
        for i, slide in enumerate(deck.slides):
            if check:
                check()
            if on_progress:
                on_progress(i, n)
            img = render_slide(slide, deck.theme, RENDER_W,
                               int(RENDER_W * PAGE_H / PAGE_W),
                               overlay=overlay_info(deck, i))
            p = os.path.join(tmp, f"page_{i:04d}.png")
            if not img.save(p, "PNG"):
                raise RuntimeError(f"Failed to render slide {i + 1}")
            paths.append(p)
        if on_progress:
            on_progress(n, n)
    except Exception:
        _rm(tmp)
        raise
    return tmp, paths


def _rm(path: str) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _narration_of(slide) -> str:
    text = (slide.narration or "").strip() or slide.effective_narration()
    return (text or "").strip()


# ------------------------------------------------------------------ #
# PDF handout
# ------------------------------------------------------------------ #
def export_pdf(deck: Deck, path: str, notes: bool = False,
               on_progress=None, check=None) -> str:
    """Write the deck as a PDF handout and return the output path.

    ``notes`` interleaves a notes page after every slide page: the slide
    thumbnail on top and the text that would be spoken underneath."""
    import fitz

    if not deck.slides:
        raise RuntimeError("The deck has no slides to export.")

    tmp, pages = _render_pages(deck, on_progress, check)
    try:
        doc = fitz.open()
        for i, png in enumerate(pages):
            if check:
                check()
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            page.insert_image(fitz.Rect(0, 0, PAGE_W, PAGE_H),
                              filename=png)
            if notes:
                _pdf_notes_page(doc, deck, i, png)
        doc.set_metadata({
            "title": deck.name or "Slideshow",
            "author": "Slideshow Studio",
            "creator": "Slideshow Studio (PyMuPDF)",
        })
        if check:
            check()
        doc.save(path, deflate=True)
        doc.close()
    finally:
        _rm(tmp)
    return path


def _pdf_notes_page(doc, deck: Deck, index: int, slide_png: str) -> None:
    """A white notes page: slide thumbnail, then the spoken text."""
    import fitz

    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.draw_rect(fitz.Rect(0, 0, PAGE_W, PAGE_H),
                   color=None, fill=_rgb(NOTES_BG))

    # thumbnail
    thumb_h = PAGE_H * 0.52
    page.insert_image(fitz.Rect(24, 24, PAGE_W - 24, 24 + thumb_h),
                      filename=slide_png)

    # caption + narration
    slide = deck.slides[index]
    title = (slide.title or f"Slide {index + 1}").strip()
    page.insert_textbox(
        fitz.Rect(24, 24 + thumb_h + 10, PAGE_W - 24, 24 + thumb_h + 32),
        f"{index + 1}. {title}", fontname=PDF_NOTE_FONT, fontsize=12,
        color=_rgb(NOTES_TEXT))
    body = _narration_of(slide)
    if body:
        # insert_textbox writes NOTHING when the text does not fit —
        # shrink the font until it does so long narrations still land
        rect = fitz.Rect(24, 24 + thumb_h + 40, PAGE_W - 24, PAGE_H - 24)
        for size in (10.5, 9.5, 8.5, 7.5, 6.5):
            if page.insert_textbox(rect, body, fontname=PDF_NOTE_FONT,
                                   fontsize=size, color=_rgb(NOTES_TEXT),
                                   align=fitz.TEXT_ALIGN_LEFT) >= 0:
                break


# ------------------------------------------------------------------ #
# PowerPoint
# ------------------------------------------------------------------ #
def export_pptx(deck: Deck, path: str, on_progress=None, check=None) -> str:
    """Write the deck as a 16:9 .pptx and return the output path.

    Each slide is the studio render as a full-bleed picture; the
    narration is written into the speaker-notes pane."""
    from pptx import Presentation
    from pptx.util import Emu

    if not deck.slides:
        raise RuntimeError("The deck has no slides to export.")

    tmp, pages = _render_pages(deck, on_progress, check)
    try:
        prs = Presentation()
        prs.slide_width = Emu(12192000)      # 13.333 in — 16:9 default
        prs.slide_height = Emu(6858000)      # 7.5 in
        blank = prs.slide_layouts[6]
        for i, png in enumerate(pages):
            if check:
                check()
            slide = prs.slides.add_slide(blank)
            slide.shapes.add_picture(png, 0, 0,
                                     width=prs.slide_width,
                                     height=prs.slide_height)
            text = _narration_of(deck.slides[i])
            if text:
                slide.notes_slide.notes_text_frame.text = text
        props = prs.core_properties
        props.title = deck.name or "Slideshow"
        props.author = "Slideshow Studio"
        props.comments = "Made with Slideshow Studio"
        if check:
            check()
        prs.save(path)
    finally:
        _rm(tmp)
    return path
