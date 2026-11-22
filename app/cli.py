"""Headless command-line export — Slideshow Studio without the GUI.

Turns the studio into a scriptable converter for automation and CI:

    python main.py deck.slideshow --headless --format mp4 --out video.mp4
    python main.py talk.pptx --headless --format pdf --notes
    python main.py photos/ --headless --format mp4          # photo folder

The pipeline is exactly the one the GUI uses (same renderer, same TTS,
same ffmpeg settings); rendering runs on the ``offscreen`` Qt platform so
no display is needed. Exit codes: 0 = exported, 1 = export failed,
2 = command-line usage error.
"""
from __future__ import annotations

import argparse
import os
import sys

FORMATS = ("mp4", "mp3", "wav", "html", "pdf", "pptx")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Slideshow Studio — narrated slideshow studio. "
                    "Run without arguments for the graphical editor, or "
                    "pass a project/source plus --headless to export from "
                    "the command line.")
    p.add_argument("project", nargs="?",
                   help=".slideshow project, or a source file/folder to "
                        "import (PPTX, PDF, HTML, TXT, MD, images)")
    p.add_argument("--headless", action="store_true",
                   help="export without showing the GUI (needs --format)")
    p.add_argument("--format", choices=list(FORMATS),
                   help="output format for --headless (default: mp4)")
    p.add_argument("--out", metavar="FILE",
                   help="output file path (default: inside the app's "
                        "output folder, honouring the folder settings)")
    p.add_argument("--notes", action="store_true",
                   help="PDF: interleave notes pages (slide + spoken text)")
    p.add_argument("--no-music", action="store_true",
                   help="leave the deck's background music out")
    p.add_argument("--srt", action="store_true",
                   help="also write an .srt subtitle file (MP4/audio)")
    p.add_argument("--resolution", metavar="PRESET",
                   help="video resolution preset, e.g. 'Full HD 1920×1080' "
                        "(default)")
    p.add_argument("--voice", metavar="ID",
                   help="speak everything with this voice id (e.g. "
                        "en-US-AriaNeural, piper:en_US-amy-medium); "
                        "overrides per-slide voices")
    p.add_argument("--version", action="store_true",
                   help="print the app version and exit")
    return p


# ------------------------------------------------------------------ #
def _import_folder(path: str) -> list:
    """Every importable file inside a folder (photo folders, mixed)."""
    from app import importers, paths
    files = []
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(names):
            if os.path.splitext(fn)[1].lower() in paths.IMPORTABLE_EXTS:
                files.append(os.path.join(root, fn))
    if not files:
        raise RuntimeError(f"No importable files inside {path}")
    slides = []
    errors = []
    for f in files:
        try:
            slides.extend(importers.import_file(f))
        except Exception as exc:
            errors.append(f"{os.path.basename(f)}: {exc}")
    if not slides:
        raise RuntimeError("Nothing could be imported:\n" + "\n".join(errors))
    for e in errors:
        print(f"warning: skipped {e}", file=sys.stderr)
    return slides


def _load_deck(path: str):
    """Deck from a .slideshow project, a source file, or a folder."""
    from app import importers, workspace
    from app.models import Deck

    if os.path.isdir(path):
        slides = _import_folder(path)
    elif os.path.splitext(path)[1].lower() == ".slideshow":
        deck = workspace.load_project(path)
        deck.project_path = path
        return deck
    else:
        slides = importers.import_file(path)
    if not slides:
        raise RuntimeError(f"No slides could be imported from {path}")
    deck = Deck()
    deck.name = os.path.splitext(os.path.basename(path))[0] or "Slideshow"
    deck.slides.extend(slides)
    return deck


def _print_progress(pct: int, msg: str) -> None:
    print(f"\r[{pct:3d}%] {msg:<58}", end="", flush=True)


def run(argv: list[str] | None = None) -> int:
    """Execute the headless export; returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    from app import APP_VERSION

    if args.version:
        print(f"Slideshow Studio {APP_VERSION}")
        return 0

    if not args.headless:
        parser.error("pass --headless for a command-line export, or run "
                     "main.py without arguments for the GUI")
    if not args.project:
        parser.error("a project or source file is required for --headless")
    fmt = args.format or "mp4"

    # offscreen rendering: the document/video renderer needs a Qt GUI
    # application (fonts) but no display
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    try:
        deck = _load_deck(args.project)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not len(deck.slides):
        print("error: the deck has no slides to export.", file=sys.stderr)
        return 1

    if args.voice:
        from app.models import VoiceSettings
        deck.default_voice = VoiceSettings(voice=args.voice)
        for s in deck.slides:
            s.voice = None
        print(f"Voice override: {args.voice}")

    from app import folders
    out = args.out or folders.suggest_output_path(deck.name, fmt)
    out = os.path.abspath(out)

    print(f"Slideshow Studio — exporting '{deck.name}' "
          f"({len(deck.slides)} slides) to {fmt.upper()}")

    if fmt == "html":
        try:
            from app import html_export
            path = html_export.export_html(deck, out)
        except Exception as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            return 1
        print(f"\r{' ' * 76}\rSaved: {path}")
        return 0

    from app.export_worker import RESOLUTIONS, ExportOptions, ExportWorker

    resolution = args.resolution or "Full HD 1920×1080"
    if resolution not in RESOLUTIONS:
        print(f"error: unknown resolution '{args.resolution}' — choose one "
              f"of: {', '.join(RESOLUTIONS)}", file=sys.stderr)
        return 1

    opts = ExportOptions(
        mode=("audio" if fmt in ("mp3", "wav") else fmt),
        resolution=resolution,
        audio_format=(fmt if fmt in ("mp3", "wav") else "mp3"),
        out_path=out,
        use_music=not args.no_music,
        duck_music=True,
        save_srt=args.srt,
        notes=args.notes,
    )
    worker = ExportWorker(deck, opts)
    worker.progress.connect(_print_progress)
    result = {"path": "", "error": ""}
    worker.finished_ok.connect(lambda p: result.update(path=p))
    worker.failed.connect(lambda m: result.update(error=m))
    worker.run()                    # synchronous: no event loop needed
    if result["error"]:
        print(f"\nerror: {result['error']}", file=sys.stderr)
        return 1
    if args.srt:
        srt = os.path.splitext(result["path"])[0] + ".srt"
        if os.path.isfile(srt):
            print(f"\nSaved: {result['path']}\nSaved: {srt}")
            return 0
    print(f"\r{' ' * 76}\rSaved: {result['path']}")
    return 0
