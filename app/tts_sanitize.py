"""TTS text sanitation — clean narration before it reaches a speech engine.

Speech engines read punctuation, emoji and markup literally, which produces
artefacts: "star-star" for markdown bold, long pauses at emoji, spelled-out
URLs, odd intonation at fancy unicode punctuation. This module rewrites the
*SPOKEN* text only — the deck always keeps the original wording.

Cleaning steps (each individually switchable via the options dict):

html      strip tags & decode entities (narration pasted from rich text)
emoji     remove emoji, pictographs, variation selectors, ZWJ, skin tones
markdown  unmark **bold**, _italic_, `code`, # headings, [text](url), quotes
urls      replace http(s) URLs and www. hosts with the word "link"
symbols   map unicode punctuation/symbols to speakable ASCII (dashes,
          smart quotes, arrows, math signs, currency kept), drop
          copyright/trademark marks
abbrev    expand common abbreviations (e.g., i.e., etc., Dr., Mr., …)

`options_for(None)` yields every step enabled.
"""
from __future__ import annotations

import html as html_mod
import re

DEFAULT_OPTIONS: dict = {
    "html": True,
    "emoji": True,
    "markdown": True,
    "urls": True,
    "symbols": True,
    "abbrev": True,
}


def options_for(options: dict | None) -> dict:
    opts = dict(DEFAULT_OPTIONS)
    opts.update(options or {})
    return opts


# --------------------------------------------------------------------- #
# patterns
# --------------------------------------------------------------------- #
_HTML_TAG = re.compile(r"<[^>]{1,400}>")

# emoji & pictographs (supplementary planes + misc symbols + dingbats),
# variation selectors, ZWJ, skin-tone modifiers, keycaps
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"     # emoji, pictographs, transport, supplemental
    "\U00002600-\U000027BF"     # misc symbols + dingbats
    "\U00002B00-\U00002BFF"     # arrows/star/misc (⭐ etc.)
    "\U0001F1E6-\U0001F1FF"     # regional indicators (flags)
    "\U0001F3FB-\U0001F3FF"     # skin tones
    "\U0000FE00-\U0000FE0F"     # variation selectors
    "\U0000200D"                # zero-width joiner
    "\U000020E3"                # combining enclosing keycap
    "]+"
)

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]{0,400}\)")
_MD_LINK = re.compile(r"\[([^\]]{0,200})\]\([^)]{0,400}\)")
_MD_BOLD = re.compile(r"(\*\*\*|___)(\S(?:.*?\S)?)\1", re.S)
_MD_BOLD2 = re.compile(r"(\*\*|__)(\S(?:.*?\S)?)\1", re.S)
_MD_ITALIC = re.compile(r"(?<![\w\\])(\*|_)(\S(?:.*?\S)?)\1(?![\w])", re.S)
_MD_CODE = re.compile(r"```+ *(.*?)```+", re.S | re.DOTALL)
_MD_CODE2 = re.compile(r"`([^`\n]{1,200})`")
_MD_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MD_BULLET = re.compile(r"(?m)^\s{0,8}[-*+]\s+")
_MD_QUOTE = re.compile(r"(?m)^\s{0,3}>\s?")
_MD_HRULE = re.compile(r"(?m)^\s{0,3}([-*_])\1{2,}\s*$")
_MD_TABLE = re.compile(r"(?m)^\s{0,3}\|.+\|\s*$")
_URL = re.compile(r"\bhttps?://\S{1,300}", re.IGNORECASE)
_URL_WWW = re.compile(r"(?<![\w.])www\.\S{1,300}", re.IGNORECASE)

_ZERO_WIDTH = re.compile("[\u200b\u200c\u200e\u200f\u202a-\u202e\u2060\ufeff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# unicode -> speakable ASCII
_SYMBOL_MAP = {
    "\u2013": ", ",      # en dash
    "\u2014": ", ",      # em dash
    "\u2212": "-",       # minus sign
    "\u2018": "'", "\u2019": "'", "\u201a": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2026": "...",
    "\u2032": "'", "\u2033": '"',
    "\u00a0": " ",
    "\u00b7": ", ", "\u2022": ", ", "\u2023": ", ", "\u25aa": ", ",
    "\u2192": " to ", "\u2190": " back to ", "\u2191": " up ",
    "\u2193": " down ", "\u21d2": " so ",
    "\u00d7": " times ", "\u00f7": " divided by ", "\u00b1": " plus or minus ",
    "\u2248": " about ", "\u2260": " not equal ", "\u2264": " at most ",
    "\u2265": " at least ", "\u221e": " infinity ",
    "\u00b0": " degrees ",
    "\u2196": "", "\u2197": "", "\u2198": "", "\u2199": "",
    "\u25b6": "", "\u25c0": "", "\u23f8": "", "\u2705": "", "\u2714": "",
    "\u274c": "", "\u2716": "", "\u2028": " ", "\u2029": " ",
    "\u203e": "", "\u00ad": "", "\u2500": "", "\u2502": " ",
}
_SYMBOL_RE = re.compile("|".join(re.escape(k) for k in _SYMBOL_MAP))

_DROP_SYMBOLS = re.compile("[\u00a9\u00ae\u2122\u2139\u203c\u2049\u3030\u303d]")

# common abbreviations -> spoken form (applied with word boundaries)
_ABBREVIATIONS = [
    (re.compile(r"\be\.g\.", re.I), "for example"),
    (re.compile(r"\bi\.e\.", re.I), "that is"),
    (re.compile(r"\betc\.(?=\s|$)", re.I), "and so on"),
    (re.compile(r"\bvs\.?(?=\s|$)", re.I), "versus"),
    (re.compile(r"\bapprox\.(?=\s|$)", re.I), "approximately"),
    (re.compile(r"\bFig\.(?=\s*\d)", re.I), "Figure"),
    (re.compile(r"\bDr\.", re.I), "Doctor"),
    (re.compile(r"\bMr\.", re.I), "Mister"),
    (re.compile(r"\bMrs\.", re.I), "Missus"),
    (re.compile(r"\bMs\.", re.I), "Miss"),
    (re.compile(r"\bProf\.", re.I), "Professor"),
    (re.compile(r"\bviz\.", re.I), "namely"),
]
_REPEATED_PUNCT = re.compile(r"([!?])\1{1,}")
_SPACE_BEFORE_PUNCT = re.compile(r" +([,.;:!?])")
_DANGLING = re.compile(r"^[,.;:!? ]+")
_MULTI_BLANK = re.compile(r"\n\s*\n\s*")


# --------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------- #
def sanitize_for_tts(text: str, options: dict | None = None) -> str:
    """Return the text a speech engine should read, cleaned per *options*."""
    opts = options_for(options)
    t = text or ""
    if not t.strip():
        return t or ""

    if opts.get("html", True):
        t = _strip_html(t)

    t = _ZERO_WIDTH.sub("", t)
    t = _CONTROL.sub(" ", t)

    if opts.get("emoji", True):
        t = _EMOJI.sub(" ", t)

    if opts.get("markdown", True):
        t = _clean_markdown(t)

    if opts.get("urls", True):
        t = _URL.sub("link", t)
        t = _URL_WWW.sub("link", t)

    if opts.get("abbrev", True):
        for pat, spoken in _ABBREVIATIONS:
            t = pat.sub(spoken, t)

    if opts.get("symbols", True):
        t = _DROP_SYMBOLS.sub("", t)
        t = _SYMBOL_RE.sub(lambda m: _SYMBOL_MAP[m.group(0)], t)

    t = _REPEATED_PUNCT.sub(r"\1", t)
    t = _MULTI_BLANK.sub("\n", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = _SPACE_BEFORE_PUNCT.sub(r"\1", t)
    lines = [_DANGLING.sub("", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines).strip()


# --------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------- #
def _strip_html(t: str) -> str:
    if "<" not in t and "&" not in t:
        return t
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|li|h[1-6]|blockquote|tr)>", "\n", t)
    t = _HTML_TAG.sub(" ", t)
    return html_mod.unescape(t)


def _clean_markdown(t: str) -> str:
    t = _MD_IMAGE.sub(lambda m: m.group(1) or "", t)
    t = _MD_LINK.sub(lambda m: m.group(1), t)
    t = _MD_CODE.sub(lambda m: m.group(1), t)
    t = _MD_CODE2.sub(lambda m: m.group(1), t)
    t = _MD_BOLD.sub(lambda m: m.group(2), t)
    t = _MD_BOLD2.sub(lambda m: m.group(2), t)
    t = _MD_ITALIC.sub(lambda m: m.group(2), t)
    t = _MD_HEADING.sub("", t)
    t = _MD_BULLET.sub("", t)
    t = _MD_QUOTE.sub("", t)
    t = _MD_HRULE.sub("", t)
    t = _MD_TABLE.sub(lambda m: m.group(0).replace("|", " "), t)
    # escaped markdown characters -> literal
    t = re.sub(r"\\([\\`*_{}\[\]()#+.!~-])", r"\1", t)
    return t


# --------------------------------------------------------------------- #
# helper for UI: describe what cleaning will do
# --------------------------------------------------------------------- #
def preview_pair(text: str, options: dict | None = None,
                 limit: int = 120) -> tuple[str, str]:
    """(original, cleaned) pair, each elided to *limit* chars."""
    orig = " ".join((text or "").split())
    clean = " ".join(sanitize_for_tts(text, options).split())
    if len(orig) > limit:
        orig = orig[:limit].rstrip() + "…"
    if len(clean) > limit:
        clean = clean[:limit].rstrip() + "…"
    return orig, clean
