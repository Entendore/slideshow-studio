"""Text-script mode: the whole deck as one editable plain-text document.

The script format is deliberately simple and markdown-ish::

    # Slide title
    Body text. A blank line starts a new paragraph.

    ~ Narration spoken by the TTS engine.
    ~ More narration lines follow.

    ---

    # Next slide

Rules
  * ``#`` (1-6 of them) at line start starts a new slide; the rest of the
    line is the slide title.
  * ``---`` / ``***`` / ``===`` alone on a line also starts a new (untitled)
    slide.
  * ``~`` at line start is narration text; consecutive narration lines are
    joined with newlines. ``Narration:`` / ``Notes:`` at line start works
    too.
  * Anything else is slide body text.
  * A leading backslash escapes a special first character, so bodies can
    literally start with ``#``, ``~``, ``---`` or ``Notes:``; a literal
    backslash is written as two (``\\\\``).
  * HTML bodies are exported in their readable plain-text form. Applying
    the script back turns an *edited* block into a plain-text body —
    formatting, voices, motion and images of untouched slides are kept.

The module has no Qt dependencies so it can be unit-tested headlessly and
reused by importers.
"""
from __future__ import annotations

import re

from .models import Deck, Slide

_BREAKS = {"---", "***", "==="}
_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
_TILDE = re.compile(r"^~\s?(.*)$")
_LABEL = re.compile(r"^(?:narration|notes)\s*:\s*(.*)$", re.IGNORECASE)


# --------------------------------------------------------------------- #
# line classification / escaping
# --------------------------------------------------------------------- #
def starts_special_line(stripped: str) -> bool:
    """Would this (already stripped) line be misread as structure?"""
    if not stripped:
        return False
    if stripped in _BREAKS:
        return True
    if _HEADING.match(stripped):
        return True
    if _TILDE.match(stripped):
        return True
    if _LABEL.match(stripped):
        return True
    return False


def _escape_body_line(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("\\"):
        return "\\" + line            # literal backslash -> double it
    if starts_special_line(stripped):
        return "\\" + line
    return line


def _unescape_body_line(line: str) -> str:
    if not line.startswith("\\"):
        return line
    rest = line[1:]
    if rest.startswith("\\") or starts_special_line(rest.strip()):
        return rest
    return line


# --------------------------------------------------------------------- #
# deck -> script
# --------------------------------------------------------------------- #
def deck_to_script(deck: Deck) -> str:
    """Serialize a whole deck into the plain-text script format."""
    out: list[str] = []
    for i, s in enumerate(deck.slides):
        if i:
            out.append("")
            if not (s.title or "").strip():
                # no heading will flush this slide -> force a break
                out.append("---")
                out.append("")
        if (s.title or "").strip():
            out.append("# " + s.title.strip())
        body = s.body_plain()
        if body:
            for line in body.replace("\r\n", "\n").split("\n"):
                out.append(_escape_body_line(line.rstrip()))
        narr = (s.narration or "").strip()
        if narr:
            if out and out[-1].strip():
                out.append("")
            for line in narr.replace("\r\n", "\n").split("\n"):
                line = line.strip()
                if line:
                    out.append("~ " + line)
    if not out:
        return ""
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------- #
# script -> slides
# --------------------------------------------------------------------- #
def parse_script(text: str) -> list[Slide]:
    """Parse script text into slides (plain-format bodies).

    Never raises: unknown lines simply become body text. Returns ``[]``
    for empty/blank input.
    """
    slides: list[Slide] = []
    title: str | None = None
    body: list[str] = []
    narr: list[str] = []

    def flush() -> None:
        nonlocal title, body, narr
        b = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip("\n")
        n = "\n".join(narr).strip()
        if title is None and not b and not n:
            body, narr = [], []
            return
        slides.append(Slide(title=(title or "").strip(), body=b, narration=n))
        title, body, narr = None, [], []

    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            if body and body[-1] != "":
                body.append("")
            continue
        if stripped.startswith("\\"):
            rest = stripped[1:]
            if rest.startswith("\\") or starts_special_line(rest):
                # escaped structural character (or literal backslash)
                body.append(_unescape_body_line(raw.rstrip()))
                continue
        m = _HEADING.match(stripped)
        if m:
            flush()
            title = m.group(1).strip()
            continue
        if stripped in _BREAKS:
            flush()
            continue
        m = _TILDE.match(stripped)
        if m:
            line = m.group(1).strip()
            if line:
                narr.append(line)
            continue
        m = _LABEL.match(stripped)
        if m:
            rest = m.group(1).strip()
            if rest:
                narr.append(rest)
            continue
        body.append(raw.rstrip())
    flush()
    return slides


# --------------------------------------------------------------------- #
# stats helpers (no Qt)
# --------------------------------------------------------------------- #
def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def estimate_speak_seconds(text: str, rate: int = 0) -> float:
    """Rough spoken duration of *text* at edge-tts *rate* percent."""
    words = count_words(text)
    if not words:
        return 0.0
    wpm = 155.0 * (1.0 + (rate or 0) / 100.0)
    return words * 60.0 / max(60.0, wpm)


def script_stats(text: str) -> dict:
    """Slide/word/char counts of a script document (for status labels)."""
    slides = parse_script(text)
    return {
        "slides": len(slides),
        "words": count_words(text),
        "chars": len(text or ""),
    }
