"""Smart memory: the studio remembers your work between runs.

Three layers, all silent and crash-safe:

  Session snapshot   the deck exactly as it was on screen at exit is saved
                     to workspace/session.slideshow (plus small metadata in
                     QSettings). "Tools ▸ Reopen last session" — or the
                     startup toggle — puts everything back, including the
                     selected slide and inspector tab, and re-attaches the
                     project file if there still is one.
  Per-deck memory    the selected slide + inspector tab are remembered per
                     project path, so reopening a project restores your
                     place instead of jumping back to slide 1.
  Cache hygiene      narration-cache entries older than 60 days are pruned
                     automatically at startup; the voice-model manager can
                     clear caches on demand.

Pure Python apart from QSettings (no widgets), so tests can use it without
showing any UI.
"""
from __future__ import annotations

import json
import os
import time

from PySide6.QtCore import QSettings

from . import workspace

ORG = "ZaiStudio"
APP = "SlideshowStudio"

REOPEN_LAST_KEY = "reopen_last"          # "false" disables startup restore
DEFAULT_REOPEN_LAST = True


def _settings() -> QSettings:
    return QSettings(ORG, APP)


# ------------------------------------------------------------------ #
# session snapshot
# ------------------------------------------------------------------ #
def save_session(deck, index: int = 0, tab: int = 0) -> bool:
    """Snapshot the on-screen deck (never touches deck.project_path)."""
    try:
        workspace.save_project(deck, workspace.session_path(),
                               set_path=False)
    except Exception:
        return False
    meta = {
        "path": deck.project_path or "",
        "name": deck.name or "",
        "slides": len(deck.slides),
        "index": int(index),
        "tab": int(tab),
        "time": time.strftime("%Y-%m-%d %H:%M"),
    }
    s = _settings()
    s.setValue("session/meta", json.dumps(meta))
    return True


def session_info() -> dict | None:
    """Metadata about the remembered session, or None when there is none."""
    s = _settings()
    raw = s.value("session/meta", "") or ""
    if not raw:
        return None
    try:
        meta = json.loads(raw)
    except ValueError:
        return None
    if not os.path.isfile(workspace.session_path()):
        return None
    return meta


def load_session():
    """(deck, meta) for the remembered session, or None when unavailable."""
    info = session_info()
    if info is None:
        return None
    try:
        deck = workspace.load_project(workspace.session_path())
    except Exception:
        clear_session()
        return None
    return deck, info


def clear_session() -> None:
    """Forget the session snapshot (file + metadata)."""
    try:
        p = workspace.session_path()
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass
    s = _settings()
    s.remove("session/meta")


# ------------------------------------------------------------------ #
# per-deck memory (selected slide + inspector tab)
# ------------------------------------------------------------------ #
def _deck_key(project_path: str) -> str:
    return "deckstate/" + os.path.abspath(project_path)


def save_deck_state(project_path: str, index: int, tab: int) -> None:
    if not project_path:
        return
    _settings().setValue(_deck_key(project_path),
                         json.dumps({"index": int(index), "tab": int(tab)}))


def load_deck_state(project_path: str) -> dict:
    raw = _settings().value(_deck_key(project_path), "") or ""
    if not raw:
        return {}
    try:
        state = json.loads(raw)
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def forget_deck_state(project_path: str) -> None:
    _settings().remove(_deck_key(project_path))


# ------------------------------------------------------------------ #
# cache hygiene
# ------------------------------------------------------------------ #
def narration_cache_stats() -> tuple[int, int]:
    """(file count, total bytes) of the narration cache directory."""
    d = workspace.narr_cache_dir()
    count = 0
    total = 0
    try:
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                count += 1
                total += os.path.getsize(p)
    except OSError:
        pass
    return count, total


def prune_narration_cache(days: int = 60) -> int:
    """Delete narration-cache files older than *days*; returns the count."""
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    d = workspace.narr_cache_dir()
    try:
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


def clear_narration_cache() -> int:
    """Remove every cached narration file; returns the count removed."""
    removed = 0
    d = workspace.narr_cache_dir()
    try:
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    return removed


# ------------------------------------------------------------------ #
# startup preference
# ------------------------------------------------------------------ #
def reopen_last_enabled() -> bool:
    return str(_settings().value(REOPEN_LAST_KEY,
                                 "true" if DEFAULT_REOPEN_LAST else "false")
               ) not in ("false", "0", "False")


def set_reopen_last_enabled(on: bool) -> None:
    _settings().setValue(REOPEN_LAST_KEY, "true" if on else "false")
