"""Shared fixtures for the Slideshow Studio test suite.

The suite is hermetic:

* Qt runs on the ``offscreen`` platform (set before any Qt import).
* ``QStandardPaths`` test mode + a sandboxed ``QSettings`` path keep the
  real user workspace, narration cache and settings untouched.
* TTS voice listing and synthesis are stubbed offline by default; tests
  that genuinely need the network are marked ``@pytest.mark.online``.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

SANDBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sandbox")
os.makedirs(SANDBOX, exist_ok=True)

import pytest


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """One QApplication for the whole session + sandboxed settings."""
    from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths
    from PySide6.QtWidgets import QApplication

    QStandardPaths.setTestModeEnabled(True)      # workspace -> ~/.qttest
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope,
                      os.path.join(SANDBOX, "settings"))
    QCoreApplication.setOrganizationName("ZaiStudio")
    QCoreApplication.setApplicationName("SlideshowStudio")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session", autouse=True)
def sandbox_temp_root():
    """Keep the managed working (temp) folder inside the test sandbox.

    The app defaults to tmp/ in the current working directory; during
    tests that is redirected so the project tree stays clean. Tests that
    exercise the default location restore this override on teardown.
    """
    from PySide6.QtCore import QSettings
    from app import folders
    s = QSettings(folders.ORG, folders.APP)
    s.setValue(folders.TEMP_KEY, os.path.join(SANDBOX, "tmp"))
    yield
    s.setValue(folders.TEMP_KEY, os.path.join(SANDBOX, "tmp"))


@pytest.fixture(scope="session", autouse=True)
def offline_voice_listing():
    """Keep the GUI from hitting the network for the edge voice list.

    Every ``MainWindow`` spawns a voice-list fetch; stub it for the whole
    session. The one ``online`` test restores the real implementation via
    ``tts._real_list_voices_sync``.
    """
    from app import tts
    orig = tts.list_voices_sync
    tts._real_list_voices_sync = orig
    tts.list_voices_sync = lambda timeout=12.0: (list(tts.FALLBACK_VOICES),
                                                 False)
    yield
    tts.list_voices_sync = orig


@pytest.fixture(scope="session")
def tone_wav():
    """Short sine-tone WAV (built with ffmpeg) — offline stand-in for TTS."""
    import subprocess
    path = os.path.join(SANDBOX, "tone.wav")
    if not os.path.isfile(path):
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=0.4", "-ar", "22050", path],
            check=True, capture_output=True)
    return path


@pytest.fixture
def stub_tts(tone_wav, monkeypatch):
    """tts.synthesize_cached returns the tone without any network use."""
    from app import tts
    monkeypatch.setattr(tts, "synthesize_cached", lambda slide, deck: tone_wav)
    return tone_wav


@pytest.fixture(scope="session")
def png_image():
    """A small PNG file usable as a slide background image."""
    from PySide6.QtGui import QColor, QImage, QPainter
    path = os.path.join(SANDBOX, "sample_img.png")
    if not os.path.isfile(path):
        img = QImage(320, 180, QImage.Format.Format_RGB32)
        img.fill(QColor("#336699"))
        p = QPainter(img)
        p.setPen(QColor("white"))
        p.drawText(20, 90, "sample")
        p.end()
        assert img.save(path, "PNG")
    return path


@pytest.fixture
def fresh_narration_cache():
    """Wipe the (sandboxed) narration cache so cache tests start clean."""
    import shutil
    from app import workspace
    shutil.rmtree(workspace.narr_cache_dir(), ignore_errors=True)
    yield


@pytest.fixture
def make_deck():
    """Factory for small decks with sensible text on every slide."""
    def _make(n=3, name="Test deck", **slide_kw):
        from app.models import Deck
        d = Deck()
        d.name = name
        for i in range(n):
            d.new_slide(title=f"Slide {i + 1}",
                        body=f"Body of slide {i + 1}.",
                        narration=f"Narration for slide {i + 1}.",
                        **slide_kw)
        return d
    return _make


@pytest.fixture
def spin(qapp):
    """Process Qt events until cond() is true or the timeout elapses."""
    import time

    def _spin(cond, timeout_s=60.0):
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            qapp.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        return cond()
    return _spin


def safe_close(win) -> None:
    """Close a MainWindow without tripping the modal discard prompt."""
    win._confirm_discard = lambda: True
    win.close()


@pytest.fixture
def win(qapp):
    """A ready MainWindow that closes safely after the test."""
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 700)
    yield w
    safe_close(w)
    qapp.processEvents()
