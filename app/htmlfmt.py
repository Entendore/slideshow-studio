"""HTML helpers for rich-text slide bodies.

Slide bodies may be plain text (``body_format == "plain"``) or a small,
sanitised HTML subset (``body_format == "html"``). The subset is exactly what
Qt's rich-text engine can render, so what the editor shows is what the canvas,
the thumbnails and the video exporter draw.

Supported tags
    b strong i em u s strike del ins  sub sup code  br  hr
    p div span  h1..h6  ul ol li  blockquote pre  a(href)  font(color)
Supported style keys (inline styles)
    color background-color text-align font-weight font-style text-decoration

Everything else is removed: scripts, event handlers, external resources,
ids/classes, font-family/font-size (the theme + auto-shrink own typography so
slides can never overflow the layout).
"""
from __future__ import annotations

import html as html_mod
import re
from typing import Iterable

# --------------------------------------------------------------------------- #
# whitelists
# --------------------------------------------------------------------------- #
DROP_TAGS = {          # removed together with their content
    "script", "style", "noscript", "template", "iframe", "object", "embed",
    "applet", "form", "input", "button", "select", "textarea", "svg", "math",
    "link", "meta", "title", "head", "base", "audio", "video", "canvas",
}
BLOCK_TAGS = {"p", "div", "ul", "ol", "li", "blockquote", "pre",
              "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "td", "th"}
ALLOWED_TAGS = BLOCK_TAGS | {
    "b", "strong", "i", "em", "u", "s", "strike", "del", "ins", "sub", "sup",
    "code", "span", "a", "font", "small", "mark", "br", "hr",
}

ALLOWED_STYLE_KEYS = {
    "color", "background-color", "text-align", "font-weight", "font-style",
    "text-decoration",
}
SAFE_HREF = re.compile(r"^(https?:|mailto:|/|#)", re.IGNORECASE)

_ALIGN_CSS = {"left", "center", "right", "justify"}


# --------------------------------------------------------------------------- #
# style attribute filtering
# --------------------------------------------------------------------------- #
def filter_style(style: str) -> str:
    """Keep only whitelisted, harmless declarations of a style attribute."""
    out: list[str] = []
    for decl in (style or "").split(";"):
        if ":" not in decl:
            continue
        key, val = decl.split(":", 1)
        key = key.strip().lower()
        val = val.strip().rstrip(";")
        if key not in ALLOWED_STYLE_KEYS or not val:
            continue
        # very defensive value check: no url(), no expression(), no braces
        if re.search(r"(url\s*\(|expression|javascript|@)", val, re.I):
            continue
        if key == "text-align" and val.lower() not in _ALIGN_CSS:
            continue
        if key in ("font-weight",) and val.lower() not in (
                "bold", "normal", "bolder", "lighter", "600", "700", "800",
                "900"):
            continue
        if key in ("font-style",) and val.lower() not in ("italic", "normal"):
            continue
        if key == "text-decoration" and not re.fullmatch(
                r"[a-z\- ]*(underline|line-through)[a-z\- ]*", val.lower()):
            continue
        out.append(f"{key}: {val}")
    return "; ".join(out)


# --------------------------------------------------------------------------- #
# sanitiser
# --------------------------------------------------------------------------- #
def sanitize_html(html: str) -> str:
    """Filter an HTML fragment down to the supported, safe subset."""
    if not html or not html.strip():
        return ""
    if "<" not in html:                       # plain text convenience
        return plain_to_html(html_mod.unescape(html))

    from bs4 import BeautifulSoup, Comment, Doctype

    soup = BeautifulSoup(html, "html.parser")

    for comment in soup.find_all(string=lambda t:
                                 isinstance(t, (Comment, Doctype))):
        comment.extract()
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    # <html>/<body>/<head> wrappers (e.g. from Qt's toHtml) just unwrap
    for name in ("html", "body", "head"):
        for tag in soup.find_all(name):
            tag.unwrap()

    for tag in soup.find_all(True):
        name = (tag.name or "").lower()
        if name == "img":
            # no external resources: keep alt text, drop the tag
            alt = tag.get("alt") or ""
            tag.replace_with(alt)
            continue
        if name == "hr":
            tag.attrs = {}
            continue
        if name not in ALLOWED_TAGS:
            tag.unwrap()                       # keep children, drop wrapper
            continue
        # --- attributes -------------------------------------------------
        attrs: dict = {}
        if name == "a":
            href = (tag.get("href") or "").strip()
            if href and SAFE_HREF.match(href):
                attrs["href"] = html_mod.escape(href, quote=True)
        style = filter_style(tag.get("style") or "")
        # Qt emits paragraph alignment as align="center" — keep it as CSS
        align = (tag.get("align") or "").strip().lower()
        if align in _ALIGN_CSS and "text-align" not in style:
            style = (style + "; " if style else "") + f"text-align: {align}"
        if style:
            attrs["style"] = style
        if name == "font":
            color_attr = (tag.get("color") or "").strip()
            if re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]+", color_attr):
                style = (style + "; " if style else "") + \
                    f"color: {color_attr}"
                if style:
                    attrs["style"] = style
        tag.attrs = attrs

    _normalize_formatting_spans(soup)
    out = soup.decode()
    return out.strip()


def _normalize_formatting_spans(soup) -> None:
    """Turn single-format spans into clean <b>/<i>/<u>/<s> tags.

    Qt's toHtml() emits <span style="font-weight:600">…</span> etc.; the
    equivalent tags keep stored bodies small and human-editable.
    """
    changed = True
    while changed:
        changed = False
        for span in soup.find_all("span"):
            style = span.get("style") or ""
            decls = [d.strip().lower() for d in style.split(";") if d.strip()]
            tag = None
            if len(decls) == 1:
                key, _, val = decls[0].partition(":")
                val = val.strip()
                if key == "font-weight" and val in ("bold", "600", "700",
                                                    "800", "900", "bolder"):
                    tag = "b"
                elif key == "font-style" and val == "italic":
                    tag = "i"
                elif key == "text-decoration" and val == "underline":
                    tag = "u"
                elif key == "text-decoration" and val == "line-through":
                    tag = "s"
            if tag is None:
                continue
            span.name = tag
            span.attrs = {}
            changed = True


# --------------------------------------------------------------------------- #
# html -> plain text
# --------------------------------------------------------------------------- #
def html_to_plain(html: str) -> str:
    """Readable plain text of an HTML fragment (for narration / stats)."""
    if not html or not html.strip():
        return ""
    if "<" not in html:
        return re.sub(r"\n{3,}", "\n\n", html).strip()
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    def walk(node, out: list[str]) -> None:
        from bs4 import NavigableString, Tag
        for child in node.children:
            if isinstance(child, NavigableString):
                out.append(str(child))
            elif isinstance(child, Tag):
                name = child.name.lower()
                if name in DROP_TAGS:
                    continue
                if name == "li":
                    out.append("\n• ")
                    walk(child, out)
                elif name in ("p", "div", "blockquote", "pre", "tr",
                              *("h1", "h2", "h3", "h4", "h5", "h6")):
                    out.append("\n")
                    walk(child, out)
                    out.append("\n")
                elif name in ("td", "th"):
                    walk(child, out)
                    out.append(" | ")
                elif name in ("ul", "ol", "table", "thead", "tbody", "hr"):
                    out.append("\n")
                    walk(child, out)
                else:
                    walk(child, out)

    out: list[str] = []
    walk(soup, out)
    text = "".join(out)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"(\n• )+", "\n• ", text)
    text = re.sub(r"( \| )+", " | ", text).strip()
    text = text.replace(" | \n", "\n").replace("\n |", "")
    return html_mod.unescape(text).strip()


# --------------------------------------------------------------------------- #
# plain text -> html
# --------------------------------------------------------------------------- #
def esc(text: str) -> str:
    return html_mod.escape(text or "", quote=False)


def esc_attr(text: str) -> str:
    return html_mod.escape(text or "", quote=True)


def plain_to_html(text: str) -> str:
    """Plain text -> html paragraphs (blank line = new paragraph)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    paras = re.split(r"\n\s*\n", text)
    out = []
    for para in paras:
        out.append("<p>" + esc(para).replace("\n", "<br>") + "</p>")
    return "".join(out)


def looks_like_html(text: str) -> bool:
    """Heuristic: does this body text already contain markup?"""
    return bool(re.search(
        r"</?(p|div|br|b|strong|i|em|u|s|ul|ol|li|h[1-6]|span|blockquote|"
        r"a|code|pre|font|sub|sup)\b", (text or ""), re.IGNORECASE))


# --------------------------------------------------------------------------- #
# Qt document builder (used by render.py)
# --------------------------------------------------------------------------- #
_DEFAULT_CSS = (
    "h1 { font-size: 1.30em; font-weight: bold; } "
    "h2 { font-size: 1.18em; font-weight: bold; } "
    "h3 { font-size: 1.08em; font-weight: bold; } "
    "h4, h5, h6 { font-size: 1.0em; font-weight: bold; font-style: italic; } "
    "blockquote { margin-left: 26px; } "
    "li { margin-left: 8px; } "
    "a { text-decoration: underline; } "
    "pre { font-family: monospace; } "
    "code { font-family: monospace; } "
)


def build_body_document(html: str, family: str, px: int, color: str,
                        theme_align: str = "left"):
    """Build a QTextDocument for an HTML slide body.

    * family/px  -- theme body font (scaled by the caller for export size)
    * color      -- theme body colour (applied where the HTML has none)
    * theme_align-- default paragraph alignment for blocks without explicit
                    alignment ("left" or "center")
    """
    from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCursor, \
        QTextDocument
    from PySide6.QtCore import Qt

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultStyleSheet(_DEFAULT_CSS)
    f = QFont(family)
    f.setPixelSize(max(6, int(px)))
    doc.setDefaultFont(f)

    safe = sanitize_html(html) or "<p></p>"
    wrapped = (f'<span style="color:{color};">{safe}</span>')
    doc.setHtml(wrapped)

    align_map = {
        "left": Qt.AlignmentFlag.AlignLeft,
        "center": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignRight,
    }
    theme_align_f = align_map.get(theme_align,
                                  Qt.AlignmentFlag.AlignLeft)
    gap = max(4, int(px * 0.30))

    cursor = QTextCursor(doc)
    block = doc.firstBlock()
    first = True
    while block.isValid():
        cur = QTextCursor(block)
        bf = QTextBlockFormat(block.blockFormat())
        # line spacing consistent with the plain-text renderer
        bf.setLineHeight(130,
                         QTextBlockFormat.LineHeightTypes.ProportionalHeight
                         .value)
        # blocks without their own alignment follow the theme
        cur_align = bf.alignment()
        if cur_align in (Qt.AlignmentFlag.AlignLeft,):
            bf.setAlignment(theme_align_f)
        if not first:
            bf.setTopMargin(gap)
        cur.setBlockFormat(bf)
        first = False
        block = block.next()
    _ = cursor
    return doc


def fit_body_document(html: str, family: str, start_px: int, min_px: int,
                      color: str, theme_align: str, width: int, max_h: int):
    """build_body_document + shrink loop, mirroring render._fit_doc."""
    px = start_px
    doc = None
    while True:
        doc = build_body_document(html, family, px, color, theme_align)
        doc.setTextWidth(width)
        if doc.size().height() <= max_h or px <= min_px:
            return doc, px
        px = max(min_px, px - max(2, int(px * 0.05)))
