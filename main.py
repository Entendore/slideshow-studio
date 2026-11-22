#!/usr/bin/env python3
"""Slideshow Studio — create, edit and export narrated slideshows.

Usage:
    python main.py                       # graphical editor
    python main.py deck.slideshow        # GUI, opens the project
    python main.py deck.slideshow --headless --format mp4 --out video.mp4
    python main.py --version

Headless export renders on the offscreen Qt platform — for scripts, CI
and servers. Requires ffmpeg on PATH for MP4/MP3/WAV (see README).
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    # offscreen rendering is only for CI/tests; normal runs use the desktop
    os.environ.setdefault("QT_API", "pyside6")

    # command-line export? (--version / --headless) — handled without the GUI
    argv = sys.argv[1:]
    if argv and any(a in ("--headless", "--version", "-h", "--help")
                    for a in argv):
        from app import cli
        return cli.run(argv)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Slideshow Studio")
    app.setOrganizationName("ZaiStudio")
    app.setStyle("Fusion")

    from PySide6.QtCore import QSettings
    theme = str(QSettings("ZaiStudio", "SlideshowStudio")
                .value("theme", "dark"))
    from app import icons, paths, styles
    styles.apply_theme(app, theme if theme in styles.THEMES else "dark")
    app.setWindowIcon(icons.icon("film"))
    paths.output_dir()          # make sure the default export folder exists

    from app.main_window import MainWindow
    # smart memory: bring back the deck that was on screen at last exit
    win = MainWindow(restore_session=True)
    # `python main.py deck.slideshow` opens the project in the editor
    if argv and os.path.splitext(argv[0])[1].lower() == ".slideshow" \
            and os.path.isfile(argv[0]):
        win._load_project_file(os.path.abspath(argv[0]))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
