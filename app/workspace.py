"""Project persistence (.slideshow files) and the media workspace.

A .slideshow file is a ZIP container:
    project.json          -- full deck serialisation
    media/<id>.<ext>      -- slide background images referenced by the deck
    media/music.<ext>     -- background music track

Slide/image paths inside project.json are stored as archive-relative paths
("media/xxx.png"). On load, files are extracted to the app workspace
(QStandardPaths AppLocalData /media) and paths are rewritten to absolute.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile

from PySide6.QtCore import QStandardPaths

from .models import Deck


def workspace_dir() -> str:
    # pin a stable identity so the workspace (narration cache, downloaded
    # Piper voice models, autosave) is the same no matter how the app was
    # launched (main.py, tests, frozen binary)
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setOrganizationName("ZaiStudio")
    QCoreApplication.setApplicationName("SlideshowStudio")
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation)
    ws = os.path.join(base, "workspace")
    os.makedirs(ws, exist_ok=True)
    return ws


def media_dir() -> str:
    md = os.path.join(workspace_dir(), "media")
    os.makedirs(md, exist_ok=True)
    return md


def narr_cache_dir() -> str:
    nd = os.path.join(workspace_dir(), "narration")
    os.makedirs(nd, exist_ok=True)
    return nd


def piper_dir() -> str:
    """Local storage for downloaded Piper voice models (onnx + json)."""
    pd = os.path.join(workspace_dir(), "piper")
    os.makedirs(pd, exist_ok=True)
    return pd


def autosave_path() -> str:
    return os.path.join(workspace_dir(), "autosave.slideshow")


def session_path() -> str:
    """Session snapshot: the deck exactly as it was on screen at exit."""
    return os.path.join(workspace_dir(), "session.slideshow")


def stage_media(source_path: str) -> str:
    """Copy an image into the workspace and return the new absolute path."""
    ext = os.path.splitext(source_path)[1].lower() or ".png"
    dest = os.path.join(media_dir(), f"{uuid.uuid4().hex[:10]}{ext}")
    shutil.copy2(source_path, dest)
    return dest


def stage_image(img) -> str:
    """Save a QImage/QPixmap as PNG in the workspace; return its path."""
    from PySide6.QtCore import QBuffer, QIODevice
    ba = QBuffer()
    ba.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = img.save(ba, "PNG")
    if not ok or img.isNull():
        raise ValueError("The clipboard does not contain a usable image.")
    dest = os.path.join(media_dir(), f"{uuid.uuid4().hex[:10]}.png")
    with open(dest, "wb") as fh:
        fh.write(bytes(ba.data()))
    return dest


PROJECT_EXT = "*.slideshow"


def save_project(deck: Deck, path: str, set_path: bool = True) -> None:
    data = deck.to_dict()

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # slide images -> media/<slide_id>.<ext>
        for slide in deck.slides:
            if slide.image and os.path.isfile(slide.image):
                ext = os.path.splitext(slide.image)[1].lower() or ".png"
                arc = f"media/{slide.id}{ext}"
                zf.write(slide.image, arc)
                slide_dict = _find_slide_dict(data, slide.id)
                if slide_dict is not None:
                    slide_dict["image"] = arc
        # music
        if deck.music_path and os.path.isfile(deck.music_path):
            ext = os.path.splitext(deck.music_path)[1].lower() or ".mp3"
            arc = f"media/music{ext}"
            zf.write(deck.music_path, arc)
            data["music_path"] = arc

        zf.writestr("project.json",
                    json.dumps(data, indent=2, ensure_ascii=False))

    if set_path:
        deck.project_path = path


def load_project(path: str) -> Deck:
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        if "project.json" not in names:
            raise ValueError("Not a valid .slideshow project file "
                             "(missing project.json).")

        # extract media into a fresh per-load folder
        load_id = uuid.uuid4().hex[:10]
        extract_root = os.path.join(media_dir(), f"proj_{load_id}")
        os.makedirs(extract_root, exist_ok=True)
        for name in names:
            if name.startswith("media/"):
                safe = os.path.basename(name)  # flatten, avoid traversal
                if safe:
                    with zf.open(name) as src, \
                            open(os.path.join(extract_root, safe), "wb") as dst:
                        shutil.copyfileobj(src, dst)

        data = json.loads(zf.read("project.json").decode("utf-8"))

    deck = Deck.from_dict(data)
    for slide in deck.slides:
        if slide.image and not os.path.isabs(slide.image):
            slide.image = os.path.join(
                extract_root, os.path.basename(slide.image))
            if not os.path.isfile(slide.image):
                slide.image = None
    if deck.music_path and not os.path.isabs(deck.music_path):
        deck.music_path = os.path.join(
            extract_root, os.path.basename(deck.music_path))
        if not os.path.isfile(deck.music_path):
            deck.music_path = None
    deck.project_path = path
    return deck


def _find_slide_dict(data: dict, slide_id: str) -> dict | None:
    for s in data.get("slides", []):
        if s.get("id") == slide_id:
            return s
    return None
