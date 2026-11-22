"""Professional working (temp) folder management (v2.4).

The working folder defaults to ``tmp/`` inside the current working
directory; this suite covers the settings layer (default location,
custom override, fallback chain), the scratch helpers, cleanup +
startup pruning, the safety guards, the folder-manager UI, and the
export / importer / main-window / diagnostics wiring.
"""
import os
import time

import pytest

SANDBOX_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "_sandbox", "tmp")


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    """A two-page generated PDF (same recipe as test_importers)."""
    import fitz
    path = tmp_path_factory.mktemp("pdf") / "gen.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=800, height=600)
        page.insert_textbox(fitz.Rect(60, 60, 740, 540),
                            f"PDF Page {i + 1}\n\n"
                            f"Content paragraph {i + 1} with enough text "
                            "to be extracted by the importer.")
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="module")
def sample_pptx(tmp_path_factory, png_image):
    """A generated PPTX with a picture slide (same as test_importers)."""
    from pptx import Presentation
    from pptx.util import Inches
    path = tmp_path_factory.mktemp("pptx") / "gen.pptx"
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Deck Title"
    s1.placeholders[1].text = "Subtitle line"
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Bullets"
    s2.shapes.add_picture(png_image, Inches(1), Inches(2))
    prs.save(str(path))
    return str(path)


@pytest.fixture
def clean_temp(monkeypatch):
    """Wipe the temp-root setting; tests chdir where they need it."""
    from PySide6.QtCore import QSettings
    from app import folders
    s = QSettings(folders.ORG, folders.APP)
    s.setValue(folders.TEMP_KEY, "")          # default: tmp/ in the cwd
    yield
    s.setValue(folders.TEMP_KEY, SANDBOX_TMP)  # sandboxed again


# ------------------------------------------------------------------ #
# settings layer
# ------------------------------------------------------------------ #
def test_temp_defaults_in_cwd(clean_temp, tmp_path, monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)
    assert folders.using_default_temp() is True
    assert folders.cwd_temp_dir() == str(tmp_path / "tmp")
    assert folders.temp_dir(create=False) == str(tmp_path / "tmp")
    d = folders.temp_dir()                    # created on demand
    assert d == str(tmp_path / "tmp")
    assert os.path.isdir(d)
    assert folders.temp_source() == \
        "tmp/ folder in the current working directory"
    assert folders.temp_fallback_reason() == ""


def test_temp_custom_override(clean_temp, tmp_path):
    from app import folders

    custom = tmp_path / "scratch"
    folders.set_temp_dir(str(custom))
    assert folders.using_default_temp() is False
    assert folders.temp_dir(create=False) == str(custom)
    assert folders.temp_dir() == str(custom)  # created on demand
    assert os.path.isdir(custom)
    assert folders.temp_source() == "custom folder"
    # empty string restores the cwd default
    folders.set_temp_dir("")
    assert folders.using_default_temp() is True


def test_temp_fallback_chain(clean_temp, tmp_path, monkeypatch):
    from app import folders

    # the preferred location is unusable (it is a plain file) -> the
    # chain continues with tmp/ next to the app, then system temp
    blocked = tmp_path / "blocked"
    blocked.write_text("not a folder")
    monkeypatch.setattr(folders, "cwd_temp_dir",
                        lambda: str(blocked))
    monkeypatch.setattr(folders.paths, "app_dir",
                        lambda: str(tmp_path / "apphome"))
    assert folders.temp_dir(create=False) == str(blocked)  # no fallback yet
    d = folders.temp_dir()
    assert d == str(tmp_path / "apphome" / "tmp")
    assert os.path.isdir(d)
    assert "not usable" in folders.temp_fallback_reason()


def test_temp_fallback_to_system_temp(clean_temp, tmp_path, monkeypatch):
    from app import folders

    blocked = tmp_path / "blocked"
    blocked.write_text("file in the way")
    monkeypatch.setattr(folders, "cwd_temp_dir", lambda: str(blocked))
    # the app-folder candidate is inside the blocked file path too, so
    # the chain must end at the system temporary folder
    monkeypatch.setattr(folders.paths, "app_dir",
                        lambda: str(tmp_path / "gone" / "deeper"))
    (tmp_path / "gone").write_text("file in the way")   # blocks makedirs
    monkeypatch.setattr(folders.tempfile, "gettempdir",
                        lambda: str(tmp_path / "systmp"))
    d = folders.temp_dir()
    assert d == str(tmp_path / "systmp")
    assert os.path.isdir(d)
    assert "system" in folders.temp_source()


def test_new_temp_dir_and_path(clean_temp, tmp_path, monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)
    a = folders.new_temp_dir("export")
    b = folders.new_temp_dir("export")
    assert a != b
    for d in (a, b):
        assert os.path.isdir(d)
        assert os.path.dirname(d) == str(tmp_path / "tmp")
        assert os.path.basename(d).startswith("export-")
    # pid is embedded so two app instances never collide
    assert str(os.getpid()) in os.path.basename(a)

    p1 = folders.new_temp_path("pdf", ".png")
    p2 = folders.new_temp_path("pdf", ".png")
    assert p1 != p2
    assert os.path.dirname(p1) == str(tmp_path / "tmp")
    assert p1.endswith(".png") and not os.path.exists(p1)
    assert folders.new_temp_path("subs", "srt").endswith(".srt")


# ------------------------------------------------------------------ #
# cleanup + startup prune
# ------------------------------------------------------------------ #
def test_cleanup_temp_removes_everything_inside(clean_temp, tmp_path,
                                                monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)
    root = folders.temp_dir()
    (tmp_path / "tmp" / "f1.bin").write_bytes(b"x" * 100)
    (tmp_path / "tmp" / "f2.bin").write_bytes(b"y" * 50)
    sub = tmp_path / "tmp" / "export-1-1"
    sub.mkdir()
    (sub / "seg.mp4").write_bytes(b"z" * 200)

    removed, freed = folders.cleanup_temp()
    assert (removed, freed) == (3, 350)
    assert os.path.isdir(root)                 # the folder itself stays
    assert os.listdir(root) == []


def test_cleanup_temp_age_filter(clean_temp, tmp_path, monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)
    folders.temp_dir()
    old = tmp_path / "tmp" / "old.txt"
    new = tmp_path / "tmp" / "new.txt"
    old.write_text("old")
    new.write_text("new")
    t = time.time() - 3 * 3600
    os.utime(old, (t, t))

    removed, _freed = folders.cleanup_temp(older_than_hours=1.0)
    assert removed == 1
    assert not old.exists() and new.exists()

    removed, _freed = folders.cleanup_temp()   # no age filter: the rest
    assert removed == 1 and not new.exists()


def test_cleanup_temp_safety_guards(clean_temp, monkeypatch):
    from app import folders

    home = os.path.expanduser("~")
    for unsafe in ("/", home, os.path.dirname(home)):
        monkeypatch.setattr(folders, "temp_dir",
                            lambda create=True, _u=unsafe: _u)
        assert folders.cleanup_temp() == (0, 0)
    # the home directory is still intact
    assert os.path.isdir(home)


def test_auto_clean_and_remove_if_empty(clean_temp, tmp_path, monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)
    folders.temp_dir()
    stale = tmp_path / "tmp" / "export-1-1"
    stale.mkdir()
    (stale / "seg.mp4").write_bytes(b"x" * 128)
    fresh = tmp_path / "tmp" / "fresh.txt"
    fresh.write_text("recent")
    t = time.time() - 30 * 3600
    os.utime(stale, (t, t))

    removed, freed = folders.auto_clean_temp()      # default: 24 h
    assert removed == 1 and freed == 128
    assert fresh.exists()                           # recent work survives

    fresh.unlink()
    assert folders.remove_temp_dir_if_empty() is True
    assert not (tmp_path / "tmp").exists()          # no litter in the cwd

    # a custom folder is never auto-removed
    custom = tmp_path / "keepme"
    custom.mkdir()
    folders.set_temp_dir(str(custom))
    assert folders.remove_temp_dir_if_empty() is False
    assert custom.exists()


def test_remove_temp_dir_if_empty_noop_when_absent(clean_temp, tmp_path,
                                                   monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)                     # tmp/ never created
    assert folders.remove_temp_dir_if_empty() is False


# ------------------------------------------------------------------ #
# pipeline wiring
# ------------------------------------------------------------------ #
def test_export_worker_uses_managed_temp(clean_temp, tmp_path, monkeypatch,
                                         make_deck):
    from app import folders
    from app.export_worker import ExportOptions, ExportWorker

    monkeypatch.chdir(tmp_path)
    calls = []
    real = folders.new_temp_dir
    monkeypatch.setattr(folders, "new_temp_dir",
                        lambda prefix="work": calls.append(prefix)
                        or real(prefix))
    monkeypatch.setattr("app.export_worker.media.ffmpeg_path",
                        lambda: None)     # fail fast, after scratch setup
    w = ExportWorker(make_deck(), ExportOptions(
        mode="mp4", out_path=str(tmp_path / "out.mp4")))
    w.run()                               # synchronous; fails on ffmpeg
    assert calls == ["export"]
    assert os.path.isdir(str(tmp_path / "tmp"))   # scratch root was used
    assert os.listdir(str(tmp_path / "tmp")) == []  # and cleaned up


def test_importers_use_managed_temp(clean_temp, tmp_path, monkeypatch,
                                    sample_pdf, sample_pptx):
    from app import folders, importers

    monkeypatch.chdir(tmp_path)
    prefixes = []
    real_path = folders.new_temp_path
    monkeypatch.setattr(folders, "new_temp_path",
                        lambda prefix="file", suffix=".tmp":
                        prefixes.append(prefix)
                        or real_path(prefix, suffix))

    slides = importers.import_pdf(sample_pdf)
    assert len(slides) == 2
    assert "pdf" in prefixes
    # scratch plates were staged into the deck and removed again
    leftovers = [f for f in os.listdir(str(tmp_path / "tmp"))
                 if f.startswith("pdf-")]
    assert leftovers == []
    assert slides[0].image                # the plate lives in the deck

    slides = importers.import_pptx(sample_pptx)
    assert len(slides) >= 2
    assert "pptx" in prefixes
    leftovers = [f for f in os.listdir(str(tmp_path / "tmp"))
                 if f.startswith("pptx-")]
    assert leftovers == []


# ------------------------------------------------------------------ #
# GUI wiring
# ------------------------------------------------------------------ #
def test_folder_manager_temp_ui(qapp, clean_temp, tmp_path, monkeypatch):
    from app import folders
    from app.folders import FolderManagerDialog

    monkeypatch.chdir(tmp_path)   # the default temp root lands here
    dlg = FolderManagerDialog()
    dlg.show()
    assert "tmp/" in dlg.tmp_edit.placeholderText()

    # custom folder round-trip with live stats
    custom = tmp_path / "scratch"
    custom.mkdir()
    (custom / "junk.bin").write_bytes(b"x" * 2048)
    dlg.tmp_edit.setText(str(custom))
    dlg._save()
    assert folders.using_default_temp() is False
    assert "1 file" in dlg.tmp_info.text()

    # an unusable path is reported but kept (like input/output folders)
    dlg.tmp_edit.setText(str(tmp_path / "ghost"))
    dlg._save()
    assert dlg.tmp_info.text().startswith("✗")
    assert folders.using_default_temp() is False

    dlg._reset_temp()
    assert folders.using_default_temp() is True
    assert "Default in use" in dlg.tmp_info.text()

    # Clean up now wipes leftovers and reports what it freed
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp" / "leftover.bin").write_bytes(b"x" * 512)
    shown = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a[2] if len(a) > 2
                                                     else k.get("text", "")))
    dlg._clean_temp()
    assert shown and shown[0].startswith("Removed 1 leftover item")
    assert folders.temp_stats() == (0, 0)
    dlg.close()


def test_main_window_temp_actions(win, qapp, clean_temp, tmp_path,
                                  monkeypatch):
    from app import folders

    monkeypatch.chdir(tmp_path)

    # File ▸ Open temp folder reveals the resolved working folder
    opened = []
    monkeypatch.setattr(
        "app.main_window.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()))
    win.act_open_temp.trigger()
    assert opened and folders.temp_dir() in opened[0]

    # Tools ▸ Clean temp folder — quiet when there is nothing to do
    win._clean_temp_folder()
    assert "already clean" in win.statusBar().currentMessage()

    # ...and informative when something was removed
    (tmp_path / "tmp" / "junk.bin").write_bytes(b"x" * 256)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win._clean_temp_folder()
    msg = win.statusBar().currentMessage()
    assert "cleaned" in msg.lower() and "freed" in msg


def test_main_window_startup_prune_and_exit(qapp, clean_temp, tmp_path,
                                            monkeypatch):
    from conftest import safe_close

    from app import folders
    from app.main_window import MainWindow

    prunes, exits = [], []
    monkeypatch.setattr(folders, "auto_clean_temp",
                        lambda *a, **k: prunes.append(1) or (0, 0))
    monkeypatch.setattr(folders, "remove_temp_dir_if_empty",
                        lambda: exits.append(1) or False)
    w = MainWindow()
    assert prunes                          # startup hygiene ran
    safe_close(w)
    assert exits                           # clean exit tidies tmp/
    qapp.processEvents()


def test_diagnostics_reports_working_folder(win, qapp, clean_temp,
                                            tmp_path, monkeypatch):
    from app import folders
    from app.diagnostics import collect_info

    monkeypatch.chdir(tmp_path)
    rows = dict(collect_info(win.deck))["Folders"]
    labels = [k for k, _v in rows]
    assert "Working (temp) folder" in labels
    value = dict(rows)["Working (temp) folder"]
    assert folders.temp_dir() in value
    assert "tmp/ folder in the current working directory" in value

    # a fallback is explained right in the report
    blocked = tmp_path / "blocked"
    blocked.write_text("x")
    monkeypatch.setattr(folders, "cwd_temp_dir", lambda: str(blocked))
    monkeypatch.setattr(folders.paths, "app_dir", lambda: str(tmp_path))
    folders.temp_dir()                     # triggers the fallback note
    rows = dict(collect_info(win.deck))["Folders"]
    value = dict(rows)["Working (temp) folder"]
    assert "fallback" in value
