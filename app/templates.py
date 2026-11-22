"""Slide layout templates for quick deck building.

Every template returns a pre-filled Slide the user can then edit; the
placeholders explain themselves and are overwritten by real content.
"""
from __future__ import annotations

from .models import Slide


def _t() -> Slide:
    """Title slide — big title + subtitle, nothing else."""
    return Slide(
        title="Presentation title",
        body="A one-line subtitle or speaker name",
    )


def _c() -> Slide:
    """Classic title + paragraph content."""
    return Slide(
        title="Slide title",
        body="Write the main point here.\n\n"
             "Supporting detail — every blank line starts a new paragraph.",
    )


def _b() -> Slide:
    """Bulleted list (rich HTML)."""
    return Slide(
        title="Key points",
        body="<ul>"
             "<li>First key point — keep each bullet to one line</li>"
             "<li>Second key point</li>"
             "<li>Third key point</li>"
             "</ul>",
        body_format="html",
    )


def _q() -> Slide:
    """Centred pull-quote."""
    return Slide(
        title="",
        body="<blockquote><p>“A memorable quote goes here.”</p>"
             "<p><i>— Attribution</i></p></blockquote>",
        body_format="html",
    )


def _s() -> Slide:
    """Section divider — heading only, vertically centred."""
    return Slide(title="Section heading")


TEMPLATES: list[tuple[str, str]] = [
    ("Title slide", "Big centred title + subtitle"),
    ("Title + content", "Classic heading with paragraph body"),
    ("Bullet list", "Heading with an HTML bullet list"),
    ("Quote", "Centred pull-quote with attribution"),
    ("Section header", "Heading only, vertically centred"),
]

_FACTORIES = {"Title slide": _t, "Title + content": _c, "Bullet list": _b,
              "Quote": _q, "Section header": _s}

DEFAULT_TEMPLATE = "Title + content"


def make_slide(name: str) -> Slide:
    """Build a new Slide from a template name (falls back to default)."""
    factory = _FACTORIES.get(name, _c)
    return factory()


def template_names() -> list[str]:
    return [name for name, _ in TEMPLATES]
