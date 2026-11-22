"""Slide renderer.

One painting routine is shared by the editor canvas, list thumbnails and the
high-resolution video exporter, so what you see while editing is exactly what
ends up in the MP4.

Everything is laid out in a virtual 1600x900 design space and scaled by
``out_width / 1600``. Fonts use setPixelSize so the result is resolution
independent (no DPI surprises between preview and export).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QImage, QPainter,
                           QPainterPath, QPen, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextDocument,
                           QTextOption)
from PySide6.QtWidgets import QWidget

BASE_W, BASE_H = 1600, 900

_MARGIN_X = 110        # horizontal margin in design px
_TOP = 118             # first baseline start
_BOTTOM = 84           # bottom margin
_TITLE_BODY_GAP = 46   # gap between title block and body


def render_slide(slide, theme, out_w: int, out_h: int,
                 placeholder: str = "", overlay: dict | None = None) -> QImage:
    """Render a slide to a QImage of the requested size.

    ``overlay`` is an optional dict from :func:`overlay_info` describing
    deck-level video overlays (slide numbers, progress bar, watermark).
    """
    img = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    try:
        s = out_w / BASE_W
        if placeholder:
            _paint_placeholder(p, out_w, out_h, placeholder, theme)
        else:
            _paint_slide(p, slide, theme, out_w, out_h, s)
            if overlay:
                accent = _lighten(getattr(theme, "accent_color", "#4da3ff"))
                _paint_overlays(p, out_w, out_h, s, overlay, accent)
    finally:
        p.end()
    return img


def overlay_info(deck, index: int) -> dict | None:
    """Deck-level overlay description for slide *index*, or None.

    Returns None when no overlay option is enabled so the common path
    stays untouched.
    """
    if deck is None:
        return None
    n = len(getattr(deck, "slides", []) or [])
    if not n:
        return None
    wm = (getattr(deck, "watermark_text", "") or "").strip()
    numbers = bool(getattr(deck, "overlay_slide_numbers", False))
    progress = bool(getattr(deck, "overlay_progress", False))
    if not (numbers or progress or wm):
        return None
    return {"index": max(0, min(index, n - 1)), "total": n,
            "numbers": numbers, "progress": progress,
            "watermark": wm}


def _paint_overlays(p: QPainter, w: int, h: int, s: float,
                    ov: dict, accent: str) -> None:
    """Draw deck-level overlays: watermark, slide numbers, progress bar."""
    pad = int(36 * s)
    shadow = QColor(0, 0, 0, 150)

    def draw_text(text: str, right: bool = False) -> None:
        f = QFont()
        f.setPixelSize(max(10, int(30 * s)))
        f.setBold(False)
        p.setFont(f)
        flags = int(Qt.AlignmentFlag.AlignBottom |
                    (Qt.AlignmentFlag.AlignRight if right
                     else Qt.AlignmentFlag.AlignLeft))
        base = QRectF(0, 0, w, h).adjusted(pad, 0, -pad, -int(pad * 0.55))
        p.setPen(QPen(shadow, 2.0))
        p.drawText(base.translated(1, 1), flags, text)
        p.setPen(QPen(QColor(255, 255, 255, 225)))
        p.drawText(base, flags, text)

    wm = ov.get("watermark") or ""
    if wm:
        draw_text(wm, right=False)
    if ov.get("numbers"):
        draw_text(f"{ov['index'] + 1} / {ov['total']}", right=True)
    if ov.get("progress"):
        frac = (ov["index"] + 1) / max(1, ov["total"])
        bar_h = max(2, int(6 * s))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRect(QRectF(0, h - bar_h, w, bar_h))
        p.setBrush(QColor(accent))
        p.drawRect(QRectF(0, h - bar_h, w * frac, bar_h))


def render_slide_png_bytes(slide, theme, out_w: int, out_h: int) -> bytes:
    img = render_slide(slide, theme, out_w, out_h)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba.data())


# ---------------------------------------------------------------------- #
# internals
# ---------------------------------------------------------------------- #
def _paint_placeholder(p: QPainter, w: int, h: int, text: str, theme) -> None:
    p.fillRect(0, 0, w, h, QColor("#14181d"))
    f = QFont()
    f.setPixelSize(int(h * 0.05))
    p.setFont(f)
    p.setPen(QPen(QColor("#8a97a5")))
    p.drawText(QRectF(0, 0, w, h),
               int(Qt.AlignmentFlag.AlignCenter), text)


def _gradient(w: int, h: int, angle_deg: float, c1: QColor, c2: QColor):
    a = math.radians(angle_deg)
    cx, cy = w / 2.0, h / 2.0
    half_len = (abs(w * math.cos(a)) + abs(h * math.sin(a))) / 2.0
    dx, dy = math.cos(a) * half_len, math.sin(a) * half_len
    g = QLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy)
    g.setColorAt(0.0, c1)
    g.setColorAt(1.0, c2)
    return g


def _cover_image(p: QPainter, path: str, w: int, h: int,
                 overlay_alpha: float) -> bool:
    img = QImage(path)
    if img.isNull():
        return False
    iw, ih = img.width(), img.height()
    scale = max(w / iw, h / ih)
    tw, th = iw * scale, ih * scale
    p.drawImage(QRectF((w - tw) / 2.0, (h - th) / 2.0, tw, th), img)
    if overlay_alpha > 0.001:
        p.fillRect(0, 0, w, h, QColor(0, 0, 0, int(255 * min(overlay_alpha, 1.0))))
    return True


def _text_doc(text: str, family: str, px: int, color: str, bold: bool,
              align: Qt.AlignmentFlag, line_h: int = 128,
              para_gap: float = 0.32) -> QTextDocument:
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    f = QFont(family)
    f.setPixelSize(max(6, int(px)))
    f.setBold(bold)
    doc.setDefaultFont(f)

    cur = QTextCursor(doc)
    cf = QTextCharFormat()
    cf.setForeground(QColor(color))
    gap = int(px * para_gap)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        bf = QTextBlockFormat()
        bf.setAlignment(align)
        bf.setLineHeight(line_h, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        if i > 0:
            bf.setTopMargin(gap)
        cur.setBlockFormat(bf)
        cur.insertText(line, cf)
        if i < len(lines) - 1:
            cur.insertBlock()
    return doc


_ALIGN = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
}


def _paint_slide(p: QPainter, slide, theme, w: int, h: int, s: float) -> None:
    # ---- background --------------------------------------------------
    used_image = False
    if slide.image:
        used_image = _cover_image(p, slide.image, w, h, theme.image_overlay)
    if not used_image:
        if theme.background_mode == "gradient":
            g = _gradient(w, h, theme.gradient_angle,
                          QColor(theme.bg_color), QColor(theme.bg_color2))
            p.fillRect(0, 0, w, h, g)
        else:
            p.fillRect(0, 0, w, h, QColor(theme.bg_color))

    align = _ALIGN.get(theme.align, Qt.AlignmentFlag.AlignLeft)
    mx = int(_MARGIN_X * s)
    avail_w = w - 2 * mx
    top = int(_TOP * s)
    bottom = int(_BOTTOM * s)

    body_color = theme.body_color if not used_image else _lighten(theme.body_color)
    title_color = theme.title_color if not used_image else _lighten(theme.title_color)
    accent = theme.accent_color if not used_image else _lighten(theme.accent_color)

    # ---- title -------------------------------------------------------
    title_doc = None
    title_px = max(10, int(theme.title_size * s))
    if slide.title.strip():
        title_doc, title_px = _fit_doc(
            lambda px: _text_doc(slide.title, theme.title_font, px,
                                 title_color, theme.title_bold, align,
                                 line_h=116),
            avail_w, int(h * 0.30), title_px, int(title_px * 0.55))
        p.save()
        p.translate(mx, top)
        title_doc.drawContents(p)
        p.restore()

    y = top + (title_doc.size().height() if title_doc else 0)

    # ---- accent bar ---------------------------------------------------
    if theme.show_accent_bar and slide.title.strip():
        bar_h = max(2, int(7 * s))
        bar_w = int(150 * s)
        by = y + int(26 * s)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent))
        if theme.align == "center":
            bx = (w - bar_w) / 2.0
        else:
            bx = mx
        p.drawRoundedRect(QRectF(bx, by, bar_w, bar_h), bar_h / 2, bar_h / 2)
        y = by + bar_h + int(20 * s)
    if title_doc:
        y += int(_TITLE_BODY_GAP * s)

    # ---- body ---------------------------------------------------------
    body_top = min(y + int(14 * s), h - bottom - int(30 * s))
    max_body_h = h - body_top - bottom
    body_html = getattr(slide, "body_format", "plain") == "html"
    body_text = slide.body or ""
    if body_text.strip() and max_body_h > int(20 * s):
        body_px = max(9, int(theme.body_size * s))
        if body_html:
            from .htmlfmt import fit_body_document
            body_doc, _ = fit_body_document(
                body_text, theme.body_font, body_px, int(body_px * 0.6),
                body_color, theme.align, avail_w, max_body_h)
        else:
            body_doc, _ = _fit_doc(
                lambda px: _text_doc(body_text, theme.body_font, px,
                                     body_color, False, align, line_h=132),
                avail_w, max_body_h, body_px, int(body_px * 0.6))
        bh = body_doc.size().height()
        by = body_top
        if not slide.title.strip():
            # vertically centre body on title-less slides
            by = top + max(0, (h - top - bottom - bh) / 2.0)
        p.save()
        p.translate(mx, by)
        body_doc.drawContents(p)
        p.restore()


def _fit_doc(make_doc, width: int, max_h: int, start_px: int, min_px: int):
    """Build a QTextDocument, shrinking the font until it fits max_h."""
    px = start_px
    while True:
        doc = make_doc(px)
        doc.setTextWidth(width)
        if doc.size().height() <= max_h or px <= min_px:
            return doc, px
        px = max(min_px, px - max(2, int(px * 0.05)))


def _lighten(color: str) -> str:
    c = QColor(color)
    if c.lightness() < 190:
        c = c.lighter(135)
    return c.name()


def image_to_data_url(img: QImage) -> str:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    import base64
    return "data:image/png;base64," + base64.b64encode(
        bytes(ba.data())).decode("ascii")


# Keep flake8 happy about the optional import used only by callers.
_ = QWidget
