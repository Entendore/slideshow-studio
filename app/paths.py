"""App-relative folders: the bundled examples and the default output directory.

Pure Python (no Qt) so tests and tools can use it without a QApplication.

Layout (relative to the folder that contains main.py):
    examples/   ready-made slideshows users can import (File ▸ Import example)
    output/     default destination for exports (MP4 / MP3 / WAV / HTML)
"""
from __future__ import annotations

import os
import re
import sys

EXAMPLES_DIRNAME = "examples"
OUTPUT_DIRNAME = "output"

# extensions the studio can import (keep in sync with main_window.SUPPORTED_EXTS)
IMPORTABLE_EXTS = {".pptx", ".ppt", ".pdf", ".html", ".htm", ".txt",
                   ".md", ".markdown", ".slideshow",
                   # photos become one slide each (photo slideshows)
                   ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}


def app_dir() -> str:
    """Folder that contains main.py (or a frozen executable's folder)."""
    if getattr(sys, "frozen", False):        # PyInstaller-style bundles
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def examples_dir() -> str:
    return os.path.join(app_dir(), EXAMPLES_DIRNAME)


def output_dir(create: bool = True) -> str:
    """Default export folder; created on first use so exports never fail."""
    d = os.path.join(app_dir(), OUTPUT_DIRNAME)
    if create:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass                            # read-only install: user picks
    return d


def sanitize_stem(name: str) -> str:
    """Filename-safe stem derived from a deck name."""
    stem = (name or "slideshow").strip() or "slideshow"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return stem or "slideshow"


def default_output_path(name: str, ext: str) -> str:
    """Suggest '<name>.<ext>' inside output/, adding -2, -3 … on collision."""
    stem = sanitize_stem(name)
    ext = ext.lstrip(".")
    base = os.path.join(output_dir(), f"{stem}.{ext}")
    if not os.path.exists(base):
        return base
    i = 2
    while os.path.exists(os.path.join(output_dir(),
                                      f"{stem}-{i}.{ext}")):
        i += 1
    return os.path.join(output_dir(), f"{stem}-{i}.{ext}")


def list_examples() -> list[str]:
    """Importable files bundled in examples/, sorted; README first."""
    d = examples_dir()
    if not os.path.isdir(d):
        return []
    files = []
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext in IMPORTABLE_EXTS:
            files.append(p)
    return files


def describe_example(path: str) -> str:
    """Human label for an example file ('demo-tour.slideshow' →
    'Demo tour  (project)')."""
    stem = os.path.splitext(os.path.basename(path))[0]
    label = stem.replace("_", " ").replace("-", " ").strip().capitalize()
    ext = os.path.splitext(path)[1].lower()
    kind = {".slideshow": "project",
            ".pptx": "PowerPoint", ".ppt": "PowerPoint",
            ".pdf": "PDF", ".html": "HTML", ".htm": "HTML",
            ".txt": "text script", ".md": "Markdown",
            ".markdown": "Markdown"}.get(ext, ext.strip("."))
    return f"{label}  ({kind})"
