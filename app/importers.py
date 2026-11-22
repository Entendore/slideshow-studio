"""Importers that turn external documents into Deck slides.

Supported inputs:
  * .pptx  -- python-pptx (text frames, pictures, speaker notes)
  * .ppt   -- legacy PowerPoint, converted via LibreOffice if installed
  * .pdf   -- PyMuPDF (page rendered to PNG + extracted text)
  * .html / .htm -- BeautifulSoup (split at h1/h2/h3 headings)
  * .txt   -- Markdown-ish: '# Heading' starts a slide, '---' separates slides
  * .png/.jpg/.jpeg/.bmp/.webp/.gif -- one photo per slide (background
             image, filename-derived title) — the photo-slideshow route
"""
from __future__ import annotations

import html as html_mod
import os
import re
import shutil
import subprocess

from . import folders
from .models import Slide
from .workspace import stage_media
from .htmlfmt import esc, esc_attr, filter_style, html_to_plain

MAX_BODY_CHARS = 1800
MAX_NARRATION_CHARS = 4500

# raster images that become one slide each (kept in sync with canvas.IMAGE_EXTS)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}


class ImportError_(RuntimeError):
    """User-friendly import failure."""


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #
def _clean(text: str) -> str:
    text = html_mod.unescape(text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clip(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    return (cut[:sp if sp > limit * 0.6 else limit]).rstrip() + " …"


# --------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------- #
def import_file(path: str, on_progress=None) -> list[Slide]:
    """Import *path* and return a list of slides. Raises ImportError_."""
    if not os.path.isfile(path):
        raise ImportError_(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pptx":
            return import_pptx(path, on_progress)
        if ext == ".ppt":
            return import_legacy_ppt(path, on_progress)
        if ext == ".pdf":
            return import_pdf(path, on_progress)
        if ext in (".html", ".htm"):
            return import_html(path)
        if ext in (".txt", ".md", ".markdown"):
            return import_txt(path)
        if ext in IMAGE_EXTS:
            return import_image(path)
    except ImportError_:
        raise
    except Exception as exc:  # surface a readable message in the UI
        raise ImportError_(f"Could not read {os.path.basename(path)}: {exc}")
    raise ImportError_(f"Unsupported file type: {ext}")


# --------------------------------------------------------------------- #
# images (photo slideshows)
# --------------------------------------------------------------------- #
def image_title(path: str) -> str:
    """Human slide title from an image filename: 'sunset_beach-2.jpg' →
    'Sunset beach 2'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.capitalize() or "Photo"


def import_image(path: str, on_progress=None) -> list[Slide]:
    """One photo → one slide: the image becomes the slide background
    (staged into the workspace so it survives), the filename becomes the
    title, and narration stays empty so the deck default voice speaks
    the title (or whatever the user adds)."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMAGE_EXTS:
        raise ImportError_(f"Not a supported image: {os.path.basename(path)}")
    try:
        staged = stage_media(path)
    except OSError as exc:
        raise ImportError_(f"Could not copy {os.path.basename(path)}: {exc}")
    return [Slide(title=image_title(path), image=staged)]


# --------------------------------------------------------------------- #
# PPTX
# --------------------------------------------------------------------- #
def _pptx_run_html(run) -> str:
    """Serialise a python-pptx run with its character formatting."""
    text = esc(run.text)
    if not text:
        return ""
    f = run.font
    if f.bold:
        text = f"<b>{text}</b>"
    if f.italic:
        text = f"<i>{text}</i>"
    if f.underline:
        text = f"<u>{text}</u>"
    try:
        addr = run.hyperlink.address
    except Exception:
        addr = None
    if addr and re.match(r"^https?://", addr or ""):
        text = f'<a href="{esc_attr(addr)}">{text}</a>'
    return text


def _build_ul(items: list[tuple[int, str]], pos: int, level: int):
    """Build a nested <ul> from (level, inner_html) items.

    Returns (html, next_pos). Sub-lists are nested inside their parent
    <li> so the fragment stays valid HTML.
    """
    parts = ["<ul>"]
    i = pos
    while i < len(items):
        lv, inner = items[i]
        if lv < level:
            break
        if lv > level:
            sub, i = _build_ul(items, i, lv)
            if parts[-1].startswith("<li") and not parts[-1].endswith("</li>"):
                parts[-1] = parts[-1] + sub + "</li>"
            else:
                parts.append(sub)
        else:
            if i + 1 < len(items) and items[i + 1][0] > level:
                parts.append(f"<li>{inner}")     # left open; sub-list attaches
            else:
                parts.append(f"<li>{inner}</li>")
            i += 1
    parts.append("</ul>")
    return "".join(parts), i


def import_pptx(path: str, on_progress=None) -> list[Slide]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    try:
        prs = Presentation(path)
    except Exception as exc:
        raise ImportError_(f"Not a readable .pptx file: {exc}")

    slides: list[Slide] = []
    prs_slides = list(prs.slides)
    for idx, sl in enumerate(prs_slides):
        if on_progress:
            on_progress(idx, len(prs_slides))

        title, body_lines, image_path = "", [], None

        def walk(shapes):
            nonlocal title, image_path
            for shp in shapes:
                if shp.shape_type == MSO_SHAPE_TYPE.GROUP:
                    walk(shp.shapes)
                    continue
                if shp.shape_type == MSO_SHAPE_TYPE.PICTURE and image_path is None:
                    try:
                        blob = shp.image.blob
                        ext = shp.image.ext or "png"
                        tmp = folders.new_temp_path("pptx", f".{ext}")
                        with open(tmp, "wb") as fh:
                            fh.write(blob)
                        image_path = stage_media(tmp)
                        os.remove(tmp)
                    except Exception:
                        pass
                    continue
                if getattr(shp, "has_text_frame", False):
                    for para in shp.text_frame.paragraphs:
                        runs = [r for r in para.runs if r.text]
                        t = "".join(r.text for r in runs).strip() \
                            or (para.text or "").strip()
                        if not t:
                            continue
                        if not title and shp is getattr(sl.shapes, "title", None):
                            title = t
                        else:
                            body_lines.append((para, runs))

        walk(sl.shapes)
        if not title and body_lines:
            first_para, first_runs = body_lines.pop(0)
            title = "".join(r.text for r in first_runs).strip() \
                or (first_para.text or "").strip()
            # keep only the first sentence-ish chunk as the title
            if len(title) > 90:
                body_lines.insert(0, (first_para, first_runs))
                title = title[:87].rstrip() + "…"

        # ---- body: keep bold/italic/bullets as rich HTML when present ---
        has_formatting = any(
            (r.font.bold or r.font.italic or r.font.underline or
             getattr(p, "level", 0))
            for p, runs in body_lines for r in runs)
        if has_formatting:
            items = []
            for para, runs in body_lines:
                level = max(0, min(3, int(getattr(para, "level", 0) or 0)))
                inner = "".join(_pptx_run_html(r) for r in runs) \
                    or esc((para.text or "").strip())
                items.append((level, inner))
            # renumber levels so there are no gaps (0,1,1,2 -> 0,1,1,2)
            renumbered, mapping, next_lv = [], {}, 0
            for level, inner in items:
                if level not in mapping:
                    mapping[level] = next_lv
                    next_lv += 1
                renumbered.append((mapping[level], inner))
            body, _ = _build_ul(renumbered, 0, 0)
            body_fmt = "html"
            plain_for_clip = html_to_plain(body)
        else:
            body = "\n".join(
                ("• " if getattr(p, "level", 0) else "") +
                ("".join(r.text for r in runs).strip() or
                 (p.text or "").strip())
                for p, runs in body_lines)
            body_fmt = "plain"
            plain_for_clip = body

        narration = ""
        try:
            if sl.has_notes_slide:
                narration = sl.notes_slide.notes_text_frame.text or ""
        except Exception:
            narration = ""
        narration = _clip(narration, MAX_NARRATION_CHARS)

        if len(plain_for_clip) > MAX_BODY_CHARS:
            slides.append(Slide(
                title=_clip(title, 200),
                body=_clip(plain_for_clip, MAX_BODY_CHARS),
                body_format="plain",
                narration=narration,
                image=image_path,
            ))
        else:
            slides.append(Slide(
                title=_clip(title, 200),
                body=body,
                body_format=body_fmt,
                narration=narration,
                image=image_path,
            ))
    if not slides:
        raise ImportError_("The presentation contains no slides.")
    return slides


def import_legacy_ppt(path: str, on_progress=None) -> list[Slide]:
    """Convert legacy .ppt via LibreOffice (soffice) to .pptx, then import."""
    soffice = shutil.which("soffice") or shutil.which("soffice.bin")
    if not soffice and os.name == "nt":
        for cand in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                     r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
            if os.path.isfile(cand):
                soffice = cand
                break
    if not soffice and sys_platform() == "darwin":
        cand = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if os.path.isfile(cand):
            soffice = cand
    if not soffice:
        raise ImportError_(
            "Legacy .ppt files need LibreOffice installed for automatic "
            "conversion. Install LibreOffice, or re-save the file as .pptx "
            "and try again.")

    outdir = folders.new_temp_dir("ppt_convert")
    try:
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pptx",
             "--outdir", outdir, path],
            capture_output=True, timeout=120)
        produced = [f for f in os.listdir(outdir) if f.lower().endswith(".pptx")]
        if proc.returncode != 0 or not produced:
            raise ImportError_("LibreOffice could not convert this .ppt file. "
                               "Try re-saving it as .pptx in PowerPoint.")
        return import_pptx(os.path.join(outdir, produced[0]), on_progress)
    except subprocess.TimeoutExpired:
        raise ImportError_("LibreOffice conversion timed out.")
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


def sys_platform() -> str:
    import sys
    return sys.platform


# --------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------- #
def import_pdf(path: str, on_progress=None) -> list[Slide]:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ImportError_(f"Could not open PDF: {exc}")

    slides: list[Slide] = []
    for i, page in enumerate(doc):
        if on_progress:
            on_progress(i, doc.page_count)

        raw = page.get_text("text") or ""
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        # Render a *clean* background plate: redact the page's own text so the
        # styled overlay text doesn't double up with the ghosted original.
        png_path = None
        try:
            for b in page.get_text("blocks"):
                r = fitz.Rect(b[0], b[1], b[2], b[3])
                if not r.is_empty:
                    page.add_redact_annot(r)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            pix = page.get_pixmap(dpi=144)
        except Exception:
            pix = page.get_pixmap(dpi=144)
        png_path = folders.new_temp_path("pdf", ".png")
        pix.save(png_path)
        image_path = stage_media(png_path)
        os.remove(png_path)

        title = lines[0] if lines else f"Page {i + 1}"
        if len(title) > 90:
            body_first = title
            title = title[:87].rstrip() + "…"
            lines = [body_first] + lines[1:]
        body = "\n".join(lines[1:])
        narration = _clip(raw, MAX_NARRATION_CHARS)

        slides.append(Slide(
            title=_clip(title, 200),
            body=_clip(body, MAX_BODY_CHARS),
            narration=narration,
            image=image_path,
        ))
    doc.close()
    if not slides:
        raise ImportError_("The PDF has no pages.")
    return slides


# --------------------------------------------------------------------- #
# HTML  (bodies are imported as sanitised rich HTML so the formatting
#        survives into the editor and the video export)
# --------------------------------------------------------------------- #
_HEADING_TAGS = ("h1", "h2", "h3")

_INLINE_MAP = {
    "b": "b", "strong": "b", "i": "i", "em": "i", "u": "u",
    "s": "s", "strike": "s", "del": "s", "ins": "u",
    "sub": "sub", "sup": "sup", "code": "code", "small": "small",
}


def _safe_href(url: str) -> str | None:
    url = (url or "").strip()
    if re.match(r"^(https?:|mailto:|/|#)", url, re.IGNORECASE):
        return esc_attr(url)
    return None


def _inline_html(node) -> str:
    """Serialise inline content, keeping a safe subset of the formatting."""
    from bs4 import NavigableString, Tag
    if isinstance(node, NavigableString):
        if node.parent and node.parent.name in ("script", "style"):
            return ""
        return esc(str(node))
    if not isinstance(node, Tag):
        return ""
    name = (node.name or "").lower()
    if name in ("script", "style", "noscript", "template", "iframe", "svg",
                "form", "input", "button", "select", "textarea"):
        return ""
    if name == "br":
        return "<br>"
    if name == "img":
        return esc(node.get("alt") or "")
    if name in _INLINE_MAP:
        inner = "".join(_inline_html(c) for c in node.children)
        tag = _INLINE_MAP[name]
        return f"<{tag}>{inner}</{tag}>" if inner else ""
    if name == "a":
        inner = "".join(_inline_html(c) for c in node.children)
        href = _safe_href(node.get("href") or "")
        if href and inner:
            return f'<a href="{href}">{inner}</a>'
        return inner
    if name in ("span", "font", "mark"):
        inner = "".join(_inline_html(c) for c in node.children)
        if not inner:
            return ""
        style = ""
        if name == "span":
            style = filter_style(node.get("style") or "")
        elif name == "mark":
            style = "background-color: #ffd54a"
        else:  # <font color="...">
            color = (node.get("color") or "").strip()
            if re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]+", color or ""):
                style = f"color: {color}"
        return (f'<span style="{style}">{inner}</span>' if style
                else inner)
    # unknown wrapper: recurse transparently
    return "".join(_inline_html(c) for c in node.children)


def import_html(path: str, on_progress=None) -> list[Slide]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw_html = fh.read()
    except OSError as exc:
        raise ImportError_(f"Could not read file: {exc}")

    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # pragma: no cover
        raise ImportError_(f"BeautifulSoup missing: {exc}")

    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    slides: list[Slide] = []
    cur_title: str | None = None
    cur_frags: list[str] = []
    consumed: set[int] = set()

    def flush():
        nonlocal cur_title, cur_frags
        frag = "".join(cur_frags).strip()
        if (cur_title or "").strip() or frag:
            _html_slide(slides, cur_title or "", frag)
        cur_title, cur_frags = None, []

    interesting = list(_HEADING_TAGS) + ["p", "ul", "ol", "blockquote",
                                         "table"]
    for el in soup.find_all(interesting):
        name = el.name
        if name in _HEADING_TAGS:
            if id(el) in consumed:
                continue
            flush()
            cur_title = _clean(el.get_text(" ", strip=True))
            consumed.add(id(el))
            for d in el.find_all(True):
                consumed.add(id(d))
            cur_frags = []
            continue
        # skip anything consumed as part of a previously handled element
        if id(el) in consumed:
            continue
        ancestor_done = False
        for anc in el.parents:
            if id(anc) in consumed:
                ancestor_done = True
                break
        if ancestor_done:
            continue

        if name in ("ul", "ol"):
            items = []
            for li in el.find_all("li", recursive=False):
                items.append(f"<li>{_inline_html_children(li)}</li>")
                consumed.add(id(li))
                for d in li.find_all(True):
                    consumed.add(d)
            if items:
                tag = "ol" if name == "ol" else "ul"
                cur_frags.append(f"<{tag}>{''.join(items)}</{tag}>")
            consumed.add(id(el))
            for d in el.find_all(True):
                consumed.add(d)
        elif name == "p":
            inner = _inline_html_children(el)
            if inner.strip():
                pstyle = filter_style(el.get("style") or "")
                cur_frags.append(
                    f"<p style=\"{pstyle}\">{inner}</p>" if pstyle
                    else f"<p>{inner}</p>")
            consumed.add(id(el))
            for d in el.find_all(True):
                consumed.add(d)
        elif name == "blockquote":
            inner = _inline_html_children(el)
            if inner.strip():
                cur_frags.append(f"<blockquote>{inner}</blockquote>")
            consumed.add(id(el))
            for d in el.find_all(True):
                consumed.add(d)
        elif name == "table":
            rows: list[str] = []
            for tr in el.find_all("tr"):
                cells = [_clean(td.get_text(" ", strip=True))
                         for td in tr.find_all(["td", "th"])]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(" | ".join(esc(c) for c in cells))
                consumed.add(id(tr))
                for d in tr.find_all(True):
                    consumed.add(d)
            if rows:
                cur_frags.append("<p>" + "<br>".join(rows) + "</p>")
            consumed.add(id(el))
            for d in el.find_all(True):
                consumed.add(d)
    flush()

    # fallback: no headings at all -> chunk paragraphs into slides
    if not slides:
        paras = [f"<p>{_inline_html_children(el)}</p>"
                 for el in soup.find_all("p")
                 if _inline_html_children(el).strip()]
        page_title = soup.title.get_text(strip=True) if soup.title else ""
        chunk: list[str] = []
        for para in paras:
            chunk.append(para)
            if len(chunk) >= 4:
                _html_chunk_slide(slides, chunk)
                chunk = []
        if chunk:
            _html_chunk_slide(slides, chunk)
        if not slides and page_title:
            slides.append(Slide(title=_clip(page_title, 200)))

    if not slides:
        raise ImportError_("No readable content found in the HTML file.")
    return slides


def _inline_html_children(el) -> str:
    return "".join(_inline_html(c) for c in el.children).strip()


def _html_slide(out: list, title: str, frag: str) -> None:
    """Append a slide; falls back to clipped plain text when very long."""
    plain = html_to_plain(frag)
    narration = _clip(((title + ". ") if title.strip() else "") + plain,
                      MAX_NARRATION_CHARS)
    if len(plain) > MAX_BODY_CHARS:
        out.append(Slide(
            title=_clip(title, 200),
            body=_clip(plain, MAX_BODY_CHARS),
            body_format="plain",
            narration=narration,
        ))
    else:
        out.append(Slide(
            title=_clip(title, 200),
            body=frag,
            body_format="html",
            narration=narration,
        ))


def _html_chunk_slide(out: list, chunk: list[str]) -> None:
    body = "".join(chunk)
    plain = html_to_plain(body)
    out.append(Slide(
        title=_clip(_first_words(plain), 200),
        body=body,
        body_format="html",
        narration=_clip(plain, MAX_NARRATION_CHARS),
    ))


def _first_words(text: str, n: int = 8) -> str:
    words = text.split()
    t = " ".join(words[:n])
    return t + "\u2026" if len(words) > n else t


# --------------------------------------------------------------------- #
# TXT
# --------------------------------------------------------------------- #
def import_txt(path: str, on_progress=None) -> list[Slide]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ImportError_(f"Could not read file: {exc}")

    from .script_mode import starts_special_line

    slides: list[Slide] = []
    title: str | None = None
    buf: list[str] = []
    narr: list[str] = []
    saw_heading = False
    _TILDE = re.compile(r"^~\s?(.*)$")
    _LABEL = re.compile(r"^(?:narration|notes)\s*:\s*(.*)$", re.IGNORECASE)

    def flush():
        nonlocal title, buf, narr
        body = _clean("\n".join(buf).strip("\n"))
        if title is None and not body and not narr:
            buf, narr = [], []
            return
        if narr:
            narration = _clip("\n".join(narr), MAX_NARRATION_CHARS)
        else:                       # legacy: speak title + body
            narration = _clip(((title + ". ") if title else "") + body,
                              MAX_NARRATION_CHARS)
        slides.append(Slide(
            title=_clip(title or "", 200),
            body=_clip(body, MAX_BODY_CHARS),
            narration=narration,
        ))
        title, buf, narr = None, [], []

    for line in raw.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if (stripped.startswith("\\")
                and starts_special_line(stripped[1:].strip())):
            buf.append(line[1:].rstrip())          # escaped structural char
        elif re.match(r"^#{1,6}\s+\S", stripped):  # markdown heading
            flush()
            saw_heading = True
            title = re.sub(r"^#{1,6}\s+", "", stripped)
        elif stripped in ("---", "***", "==="):    # explicit separator
            flush()
        else:
            m = _TILDE.match(stripped)
            if m:
                t = m.group(1).strip()
                if t:
                    narr.append(t)
                continue
            m = _LABEL.match(stripped)
            if m:
                t = m.group(1).strip()
                if t:
                    narr.append(t)
                continue
            if not stripped and buf and not buf[-1]:
                continue                           # collapse blanks
            buf.append(line)
    flush()

    # no headings at all -> chunk paragraphs into slides
    # (saw_heading, NOT the post-flush `title`, because flush() resets it)
    if not saw_heading and not narr and len(slides) <= 1:
        paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
        if paras and len(paras) > 1:
            slides.clear()
            for i in range(0, len(paras), 3):
                group = paras[i:i + 3]
                slides.append(Slide(
                    title=_first_words(group[0]),
                    body=_clip("\n\n".join(group), MAX_BODY_CHARS),
                    narration=_clip(" ".join(group), MAX_NARRATION_CHARS),
                ))

    if not slides:
        raise ImportError_("The text file appears to be empty.")
    return slides
