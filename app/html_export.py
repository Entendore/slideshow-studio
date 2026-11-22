"""Standalone HTML slideshow export.

Writes a single self-contained .html file that mirrors the deck: theme
backgrounds (gradient / solid / embedded slide images), theme typography,
the same sanitised rich-text bodies as the editor, speaker notes, keyboard
and touch navigation, a progress bar and fullscreen mode.

No external resources, no JavaScript libraries — one portable file.
"""
from __future__ import annotations

import base64
import os

from .htmlfmt import esc, esc_attr, html_to_plain, sanitize_html

STAGE_W, STAGE_H = 1600, 900

_EMBED_MAX_BYTES = 12 * 1024 * 1024   # refuse to inline huge images

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --accent: __ACCENT__; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { height: 100%; background: #07090c; overflow: hidden;
               font-family: __UIFONT__; }
  #deck { position: fixed; inset: 0; }
  .stage {
    width: __W__px; height: __H__px; position: absolute;
    left: 50%; top: 50%; transform-origin: center center;
    overflow: hidden; display: none; border-radius: 6px;
    box-shadow: 0 18px 60px rgba(0,0,0,.55);
  }
  .stage.current { display: block; }
  .stage.leaving { display: block; animation: stageout .45s ease forwards; }
  .stage.entering { display: block; animation: stagein .45s ease; }
  @keyframes stagein  { from { opacity: 0; } to { opacity: 1; } }
  @keyframes stageout { from { opacity: 1; } to { opacity: 0; } }
  .bg { position: absolute; inset: 0; z-index: 0; }
  .content {
    position: absolute; inset: 0; z-index: 2; padding: 118px 110px 84px;
  }
  .content h1 {
    font-family: __TITLEFONT__; font-weight: __TITLEBOLD__;
    color: __TITLECOLOR__; font-size: __TITLESIZE__px;
    line-height: 1.16; margin-bottom: 26px;
  }
  .content.bar h1 { margin-bottom: 0; }
  .accentbar {
    width: 150px; height: 7px; border-radius: 4px;
    background: var(--accent); margin: 26px 0 20px;
  }
  .body { font-family: __BODYFONT__; color: __BODYCOLOR__;
          font-size: __BODYSIZE__px; line-height: 1.3; }
  .body p { margin: 0 0 .55em; }
  .body ul, .body ol { margin: 0 0 .55em 1.4em; }
  .body li { margin: .18em 0; }
  .body blockquote { margin: .4em 0 .5em 26px; padding-left: 14px;
                     border-left: 4px solid var(--accent); opacity: .85; }
  .body h1 { font-size: 1.3em; margin: .5em 0 .3em; }
  .body h2 { font-size: 1.18em; margin: .5em 0 .3em; }
  .body h3 { font-size: 1.08em; margin: .5em 0 .3em; }
  .body a { color: var(--accent); }
  .body code, .body pre { font-family: ui-monospace, Consolas, monospace;
                          font-size: .92em; background: rgba(127,127,127,.18);
                          border-radius: 4px; padding: 0 5px; }
  .center .content { text-align: center; }
  .center .accentbar { margin-left: auto; margin-right: auto; }
  .center .body ul, .center .body ol { display: inline-block;
                                       text-align: left; }
  .notes {
    position: absolute; left: 0; right: 0; bottom: 0; z-index: 3;
    max-height: 38%; overflow: auto; display: none;
    background: rgba(10, 13, 18, .92); color: #cfe0ef;
    padding: 18px 110px 26px; font-size: 22px; line-height: 1.45;
    border-top: 2px solid var(--accent);
    font-family: __UIFONT__;
  }
  body.show-notes .notes { display: block; }
  #hud {
    position: fixed; right: 16px; bottom: 12px; z-index: 10;
    color: #93a5b5; font-size: 14px; display: flex; gap: 12px;
    align-items: center; user-select: none;
  }
  #hud button {
    background: rgba(36,44,54,.9); color: #cfe0ef; border: 1px solid #3a4552;
    border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 13px;
  }
  #hud button:hover { background: #2f5d8a; }
  #progress {
    position: fixed; left: 0; bottom: 0; height: 3px; width: 0;
    background: var(--accent); z-index: 10; transition: width .2s;
  }
  .hint {
    position: fixed; left: 16px; bottom: 12px; color: #5d6b78;
    font-size: 13px; z-index: 10;
  }
  @media print {
    html, body { overflow: visible; background: #fff; }
    .stage { position: relative; display: block !important; left: 0; top: 0;
             transform: none !important; margin: 0 auto 12px;
             box-shadow: none; page-break-after: always; }
    #hud, #progress, .hint { display: none; }
  }
</style>
</head>
<body>
<div id="deck">__SECTIONS__</div>
<div id="progress"></div>
<div class="hint">← → / click to navigate · F fullscreen · N notes · P print</div>
<div id="hud">
  <button id="bNotes" title="Speaker notes (N)">Notes</button>
  <button id="bFull" title="Fullscreen (F)">⛶</button>
  <span id="counter">1 / 1</span>
</div>
<script>
(function () {
  var stages = Array.prototype.slice.call(document.querySelectorAll(".stage"));
  var cur = 0, W = __W__, H = __H__;
  var progress = document.getElementById("progress");
  var counter = document.getElementById("counter");
  function fit() {
    var s = Math.min(window.innerWidth / W, window.innerHeight / H) * 0.985;
    stages.forEach(function (el) {
      el.style.transform = "translate(-50%, -50%) scale(" + s + ")";
    });
  }
  function show(i, dir) {
    i = Math.max(0, Math.min(stages.length - 1, i));
    if (i === cur && stages[i].classList.contains("current")) { return; }
    var prev = stages[cur];
    prev.classList.remove("current", "entering");
    prev.classList.add("leaving");
    setTimeout(function (el) { return function () {
      el.classList.remove("leaving"); }; }(prev), 460);
    cur = i;
    var st = stages[cur];
    st.classList.remove("leaving");
    st.classList.add("current", "entering");
    setTimeout(function (el) { return function () {
      el.classList.remove("entering"); }; }(st), 470);
    counter.textContent = (cur + 1) + " / " + stages.length;
    progress.style.width = (100 * (cur + 1) / stages.length) + "%";
    if (history.replaceState) { history.replaceState(null, "", "#" + (cur + 1)); }
  }
  function next() { show(cur + 1); }
  function prev() { show(cur - 1); }
  document.addEventListener("keydown", function (ev) {
    switch (ev.key) {
      case "ArrowRight": case "PageDown": case " ": case "Enter":
        ev.preventDefault(); next(); break;
      case "ArrowLeft": case "PageUp": case "Backspace":
        ev.preventDefault(); prev(); break;
      case "Home": ev.preventDefault(); show(0); break;
      case "End": ev.preventDefault(); show(stages.length - 1); break;
      case "f": case "F":
        if (document.fullscreenElement) { document.exitFullscreen(); }
        else { document.documentElement.requestFullscreen(); }
        break;
      case "n": case "N":
        document.body.classList.toggle("show-notes"); break;
      case "p": case "P": window.print(); break;
    }
  });
  document.getElementById("deck").addEventListener("click", function (ev) {
    var x = ev.clientX / window.innerWidth;
    if (x > 0.66) { next(); } else if (x < 0.33) { prev(); }
  });
  var tx = null;
  document.addEventListener("touchstart", function (ev) {
    tx = ev.changedTouches[0].clientX;
  }, { passive: true });
  document.addEventListener("touchend", function (ev) {
    if (tx === null) { return; }
    var dx = ev.changedTouches[0].clientX - tx;
    if (dx < -40) { next(); } else if (dx > 40) { prev(); }
    tx = null;
  }, { passive: true });
  document.getElementById("bFull").addEventListener("click", function () {
    if (document.fullscreenElement) { document.exitFullscreen(); }
    else { document.documentElement.requestFullscreen(); }
  });
  document.getElementById("bNotes").addEventListener("click", function () {
    document.body.classList.toggle("show-notes");
  });
  window.addEventListener("resize", fit);
  fit();
  var h = parseInt((location.hash || "").replace("#", ""), 10);
  show(isNaN(h) ? 0 : h - 1);
  setTimeout(fit, 60);
})();
</script>
</body>
</html>
"""


def _data_url(path: str) -> str | None:
    try:
        if not path or not os.path.isfile(path):
            return None
        if os.path.getsize(path) > _EMBED_MAX_BYTES:
            return None
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        ext = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "bmp": "bmp",
               "webp": "webp"}.get(ext, "png")
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        return f"data:image/{ext};base64,{b64}"
    except OSError:
        return None


def _section_css(slide, theme) -> str:
    """Inline background CSS for one slide's .bg div."""
    url = _data_url(getattr(slide, "image", None))
    if url:
        alpha = max(0.0, min(0.92, float(getattr(theme, "image_overlay",
                                                   0.55))))
        return (f"background-image: linear-gradient(rgba(0,0,0,{alpha:.3f}),"
                f"rgba(0,0,0,{alpha:.3f})), url('{url}');"
                "background-size: cover; background-position: center;")
    if getattr(theme, "background_mode", "gradient") == "gradient":
        # Qt angle a  ->  CSS angle a + 90 (both go colour1 -> colour2)
        return (f"background: linear-gradient("
                f"{int(getattr(theme, 'gradient_angle', 90)) + 90}deg, "
                f"{esc_attr(theme.bg_color)}, {esc_attr(theme.bg_color2)});")
    return f"background: {esc_attr(theme.bg_color)};"


def build_html(deck, embed_notes: bool = True) -> str:
    """Return the complete standalone HTML document for *deck*."""
    t = deck.theme
    sections: list[str] = []
    for i, slide in enumerate(deck.slides):
        body_html = (slide.body if slide.body_is_html()
                     else "<p>" +
                     esc(slide.body).replace("\n", "<br>") + "</p>"
                     if slide.body.strip() else "")
        body_html = sanitize_html(body_html)
        center = " center" if getattr(t, "align", "left") == "center" else ""
        notes = ""
        if embed_notes:
            note_text = esc(html_to_plain(slide.effective_narration()) or
                            "(no narration)")
            notes = f'<aside class="notes">{note_text}</aside>'
        title_html = esc(slide.title) if slide.title.strip() else ""
        accent = ""
        if getattr(t, "show_accent_bar", True) and title_html:
            accent = '<div class="accentbar"></div>'
        sections.append(
            f'<section class="stage{center}" data-slide="{i + 1}">\n'
            f'  <div class="bg" style="{_section_css(slide, t)}"></div>\n'
            f'  <div class="content">\n'
            f'    <h1>{title_html}</h1>\n{accent}\n'
            f'    <div class="body">{body_html}</div>\n'
            f'  </div>\n{notes}\n</section>')

    doc = _TEMPLATE
    title_font = (f"'{t.title_font}', 'Segoe UI', system-ui, "
                  "-apple-system, Roboto, Arial, sans-serif")
    body_font = (f"'{t.body_font}', 'Segoe UI', system-ui, "
                 "-apple-system, Roboto, Arial, sans-serif")
    ui_font = "'Segoe UI', system-ui, -apple-system, Roboto, sans-serif"
    replacements = {
        "__TITLE__": esc(deck.name or "Slideshow"),
        "__SECTIONS__": "\n".join(sections),
        "__W__": str(STAGE_W),
        "__H__": str(STAGE_H),
        "__ACCENT__": esc_attr(t.accent_color),
        "__TITLEFONT__": title_font,
        "__BODYFONT__": body_font,
        "__UIFONT__": ui_font,
        "__TITLECOLOR__": esc_attr(t.title_color),
        "__BODYSIZE__": str(int(getattr(t, "body_size", 34))),
        "__BODYSIZE__ ": str(int(getattr(t, "body_size", 34))),
        "__TITLESIZE__": str(int(getattr(t, "title_size", 62))),
        "__TITLEBOLD__": "700" if getattr(t, "title_bold", True) else "400",
        "__BODYCOLOR__": esc_attr(t.body_color),
    }
    for key, val in replacements.items():
        doc = doc.replace(key, val)
    return doc


def export_html(deck, path: str, embed_notes: bool = True) -> str:
    """Write the standalone slideshow and return the path."""
    doc = build_html(deck, embed_notes=embed_notes)
    if not path.lower().endswith(".html"):
        path += ".html"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
