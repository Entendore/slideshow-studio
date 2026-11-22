"""Professional input & output folder management (v2.3).

Covers the settings layer (input folder, output root, layout policy,
recent folders), the organised output-path helper, the folder manager
dialog, and the main-window / export-dialog / quick-convert wiring.
"""
import os
import re

import pytest

FOLDER_KEYS = ("folders/input", "folders/output_root",
               "folders/output_layout", "folders/recent",
               "folders/temp_root",
               "last_export_dir", "last_dir")


@pytest.fixture
def clean_folders():
    """Give every folder test a pristine settings slate."""
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")

    def _wipe():
        for k in FOLDER_KEYS:
            s.remove(k)
    _wipe()
    yield
    _wipe()


# ------------------------------------------------------------------ #
# settings layer
# ------------------------------------------------------------------ #
def test_folder_defaults(clean_folders):
    from app import folders, paths

    assert folders.input_dir() == ""
    assert folders.using_default_output() is True
    assert folders.output_root(create=False) == paths.output_dir()
    assert folders.output_layout() == "flat"
    assert folders.recent_folders() == []


def test_input_output_roundtrip(clean_folders, tmp_path):
    from app import folders

    inp = tmp_path / "sources"
    inp.mkdir()
    out = tmp_path / "exports"
    folders.set_input_dir(str(inp))
    folders.set_output_root(str(out))
    assert folders.input_dir() == str(inp)
    assert folders.using_default_output() is False
    assert folders.output_root(create=False) == str(out)
    # output_root() creates the custom folder on demand
    assert os.path.isdir(folders.output_root())
    # empty string restores the defaults
    folders.set_input_dir("")
    folders.set_output_root("")
    assert folders.input_dir() == ""
    assert folders.using_default_output() is True


def test_output_layout_values(clean_folders):
    from app import folders

    for layout in ("per_deck", "dated", "flat"):
        folders.set_output_layout(layout)
        assert folders.output_layout() == layout
    folders.set_output_layout("bogus")          # ignored
    assert folders.output_layout() == "flat"


def test_layout_subdir(clean_folders):
    from app import folders

    folders.set_output_layout("flat")
    assert folders.layout_subdir("My Deck") == ""
    folders.set_output_layout("per_deck")
    assert folders.layout_subdir('My: "Deck"') == "My_ _Deck_"
    assert folders.layout_subdir("") == "slideshow"
    folders.set_output_layout("dated")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", folders.layout_subdir("x"))


def test_organized_output_path(clean_folders, tmp_path):
    from app import folders

    out = tmp_path / "exports"
    folders.set_output_root(str(out))
    folders.set_output_layout("per_deck")

    p1 = folders.organized_output_path("My Deck", "mp4")
    assert p1 == os.path.join(str(out), "My Deck", "My Deck.mp4")
    assert os.path.isdir(os.path.dirname(p1))   # subdir created on demand
    # collision-safe naming inside the subfolder
    open(p1, "wb").close()
    p2 = folders.organized_output_path("My Deck", "mp4")
    assert p2.endswith("My Deck-2.mp4")

    folders.set_output_layout("dated")
    p3 = folders.organized_output_path("Tour", "mp3")
    assert os.path.dirname(p3).startswith(str(out) + os.sep)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                        os.path.basename(os.path.dirname(p3)))


def test_suggest_output_path_priority(clean_folders, tmp_path):
    from app import folders, paths

    # 1) nothing configured -> bundled output folder
    p = folders.suggest_output_path("Deck A", "mp4")
    assert p.startswith(paths.output_dir())

    # 2) last_export_dir remembered -> that folder (flat naming)
    last = tmp_path / "last"
    last.mkdir()
    from PySide6.QtCore import QSettings
    QSettings("ZaiStudio", "SlideshowStudio").setValue(
        "last_export_dir", str(last))
    p = folders.suggest_output_path("Deck A", "mp4")
    assert os.path.dirname(p) == str(last)
    assert os.path.basename(p) == "Deck A.mp4"

    # 3) a custom output folder wins over last_export_dir (+ layout)
    custom = tmp_path / "custom-exports"
    custom.mkdir()
    folders.set_output_root(str(custom))
    folders.set_output_layout("per_deck")
    p = folders.suggest_output_path("Deck A", "mp4")
    assert p == os.path.join(str(custom), "Deck A", "Deck A.mp4")


def test_recent_folders_memory(clean_folders, tmp_path):
    from app import folders

    a = tmp_path / "a"
    b = tmp_path / "b"
    c = tmp_path / "c"
    for d in (a, b):
        d.mkdir()
    folders.remember_folder(str(a))
    folders.remember_folder(str(b))
    folders.remember_folder(str(a))             # dedupe: moves to front
    assert folders.recent_folders() == [str(a), str(b)]

    # a folder that later disappears is hidden from the live list but
    # still stored until it is removed explicitly
    gone = tmp_path / "gone"
    gone.mkdir()
    folders.remember_folder(str(gone))
    import shutil
    shutil.rmtree(gone)
    assert str(gone) not in folders.recent_folders()
    assert str(gone) in folders.recent_folders(all=True)
    folders.forget_folder(str(gone))
    assert str(gone) not in folders.recent_folders(all=True)

    folders.forget_folder(str(a))
    assert folders.recent_folders() == [str(b)]
    folders.clear_recent_folders()
    assert folders.recent_folders(all=True) == []

    # the list is capped
    dirs = []
    for i in range(12):
        d = tmp_path / f"d{i}"
        d.mkdir()
        dirs.append(str(d))
        folders.remember_folder(str(d))
    stored = folders.recent_folders(all=True)
    assert len(stored) == folders.MAX_RECENT
    assert stored[0] == dirs[-1]


def test_validate_dir(clean_folders, tmp_path):
    from app import folders

    good = tmp_path / "ok"
    good.mkdir()
    assert folders.validate_dir(str(good)) == ""
    assert folders.validate_dir("") != ""
    assert "not exist" in folders.validate_dir(str(tmp_path / "gone"))
    a_file = tmp_path / "f.txt"
    a_file.write_text("x")
    assert "not a folder" in folders.validate_dir(str(a_file))


def test_folder_stats_and_sizes(clean_folders, tmp_path):
    from app import folders

    d = tmp_path / "stats"
    d.mkdir()
    (d / "one.bin").write_bytes(b"x" * 2048)
    sub = d / "sub"
    sub.mkdir()
    (sub / "two.bin").write_bytes(b"y" * 1024)
    n, total = folders.folder_stats(str(d))
    assert (n, total) == (2, 3072)
    assert folders.human_size(0) == "0 B"
    assert folders.human_size(3072) == "3.0 KB"
    assert folders.human_size(5 * 1024 * 1024) == "5.0 MB"
    assert "2 files" in folders.describe_folder(str(d))
    assert folders.folder_stats(str(tmp_path / "missing")) == (0, 0)


def test_browse_dir_fallbacks(clean_folders, tmp_path):
    from app import folders, paths

    # nothing configured: input -> last_dir -> home, output -> bundled dir
    assert folders.browse_dir("input") == os.path.expanduser("~")
    assert folders.browse_dir("output") == paths.output_dir()

    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.setValue("last_dir", str(tmp_path))
    assert folders.browse_dir("input") == str(tmp_path)

    inp = tmp_path / "in"
    inp.mkdir()
    folders.set_input_dir(str(inp))
    assert folders.browse_dir("input") == str(inp)
    # for output dialogs a configured input folder is still a friendly
    # start; the bundled output dir is only used when nothing else fits
    assert folders.browse_dir("output") == str(inp)

    out = tmp_path / "out"
    out.mkdir()
    folders.set_output_root(str(out))
    assert folders.browse_dir("output") == str(out)


# ------------------------------------------------------------------ #
# the dialog
# ------------------------------------------------------------------ #
def test_folder_manager_dialog_roundtrip(qapp, clean_folders, tmp_path):
    from app import folders
    from app.folders import FolderManagerDialog

    inp = tmp_path / "src"
    out = tmp_path / "dst"
    inp.mkdir()
    out.mkdir()
    dlg = FolderManagerDialog()
    dlg.show()

    dlg.inp_edit.setText(str(inp))
    dlg.out_edit.setText(str(out))
    dlg.layout_combo.setCurrentIndex(1)          # per_deck
    dlg._save()
    assert folders.input_dir() == str(inp)
    assert folders.output_root(create=False) == str(out)
    assert folders.output_layout() == "per_deck"
    # applied settings are remembered as recent folders
    assert str(inp) in folders.recent_folders()

    # info labels reflect the folders (live stats)
    assert "0 files" in dlg.inp_info.text()
    assert "0 files" in dlg.out_info.text()

    # resets clear both settings
    dlg._reset_input()
    dlg._reset_output()
    assert folders.input_dir() == ""
    assert folders.using_default_output() is True

    # an invalid folder shows the validation error; it is still kept
    # in the edit box (e.g. a network drive that mounts later), and
    # browse_dir() skips it until it exists
    dlg.inp_edit.setText(str(tmp_path / "ghost"))
    dlg._save()
    assert dlg.inp_info.text().startswith("✗")
    assert folders.input_dir() == str(tmp_path / "ghost")
    assert folders.browse_dir("input") != str(tmp_path / "ghost")
    dlg.close()


def test_folder_manager_recent_actions(qapp, clean_folders, tmp_path):
    from app import folders
    from app.folders import FolderManagerDialog

    d1 = tmp_path / "recent1"
    d1.mkdir()
    folders.remember_folder(str(d1))
    dlg = FolderManagerDialog()
    dlg.show()
    assert dlg.recent_list.count() == 1

    # set-as-output applies the selected recent folder
    dlg.recent_list.setCurrentRow(0)
    dlg._apply_recent_selection(as_output=True)
    assert dlg.out_edit.text() == str(d1)
    assert folders.output_root(create=False) == str(d1)

    # remove + clear (the empty list shows a non-selectable placeholder)
    dlg._forget_recent()
    assert folders.recent_folders(all=True) == []
    assert "no folders" in dlg.recent_list.item(0).text()
    folders.remember_folder(str(d1))
    dlg._refresh_recent()
    assert dlg.recent_list.count() == 1
    dlg._clear_recent()
    assert folders.recent_folders(all=True) == []
    assert "no folders" in dlg.recent_list.item(0).text()
    dlg.close()


def test_main_window_folder_actions(win, qapp, clean_folders, tmp_path,
                                    monkeypatch):
    from app import folders

    # the manager opens (and is kept for reopening)
    dlg = win.folders_manager()
    assert dlg is win.folders_dlg
    assert dlg.isVisible()
    dlg.close()

    # Open input folder without configuration -> a hint, no file manager
    win._open_input_folder()
    assert "input" in win.statusBar().currentMessage().lower()

    # with a configured folder it reveals it (openUrl stubbed out)
    opened = []
    monkeypatch.setattr(
        "app.main_window.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()))
    inp = tmp_path / "reveal-me"
    inp.mkdir()
    folders.set_input_dir(str(inp))
    win._open_input_folder()
    assert opened and str(inp) in opened[0]
    assert win.statusBar().currentMessage()  # _open_folder reports it


def test_main_window_import_dialog_uses_input_folder(
        win, qapp, clean_folders, tmp_path, monkeypatch):
    from app import folders

    inp = tmp_path / "sources"
    inp.mkdir()
    script = inp / "deck.txt"
    script.write_text("# Imported\nBody text.\n~ Hello there.\n")
    folders.set_input_dir(str(inp))

    seen = {}
    monkeypatch.setattr(
        "app.main_window.QFileDialog.getOpenFileName",
        lambda *a, **k: seen.update(start=a[2]) or (str(script), ""))
    win._confirm_import_mode = lambda: True   # welcome deck on screen
    win._import_replace = True
    win.import_dialog()
    assert seen["start"] == str(inp)             # browsing starts there
    assert len(win.deck.slides) >= 1             # and the import happened
    assert str(inp) in folders.recent_folders()  # folder remembered


def test_expand_drop_folders(win, qapp, tmp_path):
    src = tmp_path / "drop"
    src.mkdir()
    (src / "a.md").write_text("# A\nbody\n")
    (src / "b.txt").write_text("# B\nbody\n")
    (src / "ignore.me").write_text("nope")
    (src / ".hidden").mkdir()
    (src / ".hidden" / "c.txt").write_text("# C\nbody\n")

    files = win._expand_drop([str(src)])
    names = {os.path.basename(f) for f in files}
    assert names == {"a.md", "b.txt"}            # scan: no hidden, no junk
    # plain file paths pass straight through
    direct = tmp_path / "solo.txt"
    direct.write_text("# S\nbody\n")
    assert win._expand_drop([str(direct)]) == [str(direct)]
    assert win._expand_drop([str(tmp_path / "ghost")]) == []


# ------------------------------------------------------------------ #
# dialog integrations
# ------------------------------------------------------------------ #
def test_export_dialog_honours_output_settings(
        qapp, clean_folders, tmp_path, make_deck):
    from app.export_dialog import ExportDialog
    from app import folders, paths

    deck = make_deck(name="Suggested deck")
    dlg = ExportDialog(deck, parent=None, ffmpeg_ok=True)
    # default settings -> bundled output folder
    assert dlg.out_edit.text().startswith(paths.output_dir())
    dlg.reject()

    # a custom output folder + per-deck layout shapes the suggestion
    custom = tmp_path / "pro-exports"
    custom.mkdir()
    folders.set_output_root(str(custom))
    folders.set_output_layout("per_deck")
    dlg2 = ExportDialog(deck, parent=None, ffmpeg_ok=True)
    assert dlg2.out_edit.text() == os.path.join(
        str(custom), "Suggested deck", "Suggested deck.mp4")
    dlg2.reject()


def test_quick_convert_default_output(qapp, clean_folders, tmp_path):
    from app.quick_convert import QuickConvertDialog
    from app import folders

    custom = tmp_path / "qc-out"
    custom.mkdir()
    folders.set_output_root(str(custom))
    qc = QuickConvertDialog(parent=None, ffmpeg_ok=True)
    # with no per-run override the placeholder points at the configured root
    assert folders.output_root(create=False) in qc.out_edit.placeholderText()
    qc.reject()


def test_diagnostics_report_includes_folder_section(win, qapp,
                                                    clean_folders):
    from app.diagnostics import collect_info

    rows = dict(collect_info(win.deck))["Folders"]
    labels = [k for k, _v in rows]
    assert "Input folder" in labels
    assert "Output folder" in labels
    assert "Output layout" in labels
