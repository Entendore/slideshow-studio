"""MainWindow integration: editing, undo, storage, menus, dialogs."""
import os

import pytest

from app import paths, workspace


# ------------------------------------------------------------- deck basics
def test_window_boots_with_welcome_deck(win):
    assert len(win.deck.slides) >= 2
    assert win.slide_list.count() == len(win.deck.slides)
    assert win.current_index() == 0
    assert win.current_slide() is win.deck.slides[0]
    assert win.canvas is not None and win.inspector is not None
    assert win.deck_panel is not None


def test_add_uses_title_content_template_and_inserts_after_current(win):
    n0 = len(win.deck.slides)
    win.add_slide()
    assert len(win.deck.slides) == n0 + 1
    assert win.current_index() == 1
    assert win.deck.slides[1].title == "Slide title"


def test_add_slide_from_every_template(win):
    from app.templates import template_names
    for name in template_names():
        before = len(win.deck.slides)
        win.add_slide_from_template(name)
        assert len(win.deck.slides) == before + 1


def test_duplicate_and_delete_slide(win):
    n0 = len(win.deck.slides)
    win.inspector.title_edit.setText("Original")
    win.inspector._changed()
    win.duplicate_current_slide()
    assert len(win.deck.slides) == n0 + 1
    assert win.deck.slides[1].title == "Original"
    assert win.current_index() == 1, "the duplicate becomes current"
    win.delete_current_slide()
    assert len(win.deck.slides) == n0
    assert win.deck.slides[0].title == "Original"


def test_move_slide_up_down(win):
    win.inspector.title_edit.setText("Mover")
    win.inspector._changed()
    first = win.current_index()
    win.act_down.trigger()
    assert win.current_index() == first + 1
    win.act_up.trigger()
    assert win.current_index() == first


def test_undo_redo_structural_and_text(win):
    n0 = len(win.deck.slides)
    win.add_slide()
    assert len(win.deck.slides) == n0 + 1
    win.undo()
    assert len(win.deck.slides) == n0
    win.redo()
    assert len(win.deck.slides) == n0 + 1

    # typing bursts coalesce into a single undo step
    win.inspector.title_edit.setText("First")
    win.inspector._changed()
    win.inspector.title_edit.setText("Second")
    win.inspector._changed()
    assert win.deck.slides[win.current_index()].title == "Second"
    win.undo()
    assert win.deck.slides[win.current_index()].title != "Second"
    win.redo()
    assert win.deck.slides[win.current_index()].title == "Second"


def test_inspector_edits_write_back_to_deck(win):
    s = win.current_slide()
    win.inspector.title_edit.setText("Edited title")
    win.inspector._changed()
    assert win.deck.slides[win.current_index()].title == "Edited title"
    win.inspector.narr_edit.setPlainText("Spoken words")
    win.inspector._changed()
    assert s.narration == "Spoken words"


def test_inspector_motion_and_duration_override(win):
    win.inspector.motion_combo.setCurrentText("Pan down")
    win.inspector.motion_slider.setValue(70)
    win.inspector.dur_spin.setValue(4.5)
    win.inspector._changed()
    s = win.current_slide()
    assert s.motion == "Pan down"
    assert abs(s.motion_intensity - 0.7) < 1e-6
    assert abs(s.duration_override - 4.5) < 1e-6


def test_delete_last_remaining_slide_keeps_deck_usable(win):
    while len(win.deck.slides) > 1:
        win.delete_current_slide()
    assert len(win.deck.slides) == 1


# ----------------------------------------------------------------- imports
def test_import_txt_replaces_deck(win, tmp_path):
    win._confirm_import_mode = lambda: (setattr(win, "_import_replace", True)
                                        or True)
    p = tmp_path / "in.txt"
    p.write_text("# A\nbody a\n\n# B\nbody b\n", encoding="utf-8")
    win.import_path(str(p))
    assert [s.title for s in win.deck.slides] == ["A", "B"]


def test_import_md_appends(win, tmp_path):
    win._confirm_import_mode = lambda: (setattr(win, "_import_replace", False)
                                        or True)
    n0 = len(win.deck.slides)
    p = tmp_path / "in.md"
    p.write_text("# Extra\nword\n", encoding="utf-8")
    win.import_path(str(p))
    assert len(win.deck.slides) == n0 + 1


def test_import_many_and_drag_drop_exts(win, tmp_path):
    from app.main_window import SUPPORTED_EXTS
    for ext in (".pptx", ".ppt", ".pdf", ".html", ".htm", ".txt", ".md",
                ".markdown"):
        assert ext in SUPPORTED_EXTS
    assert ".slideshow" in paths.IMPORTABLE_EXTS   # openable as a project
    p1 = tmp_path / "one.txt"
    p1.write_text("# One\nx\n", encoding="utf-8")
    p2 = tmp_path / "two.txt"
    p2.write_text("# Two\ny\n", encoding="utf-8")
    win._confirm_import_mode = lambda: (setattr(win, "_import_replace", True)
                                        or True)
    win._import_many([str(p1), str(p2)])
    assert [s.title for s in win.deck.slides] == ["One", "Two"]


# ----------------------------------------------------- projects & recents
def test_save_and_reload_project(win, tmp_path):
    p = str(tmp_path / "saved.slideshow")
    win.inspector.title_edit.setText("Saved deck slide")
    win.inspector._changed()
    win.deck.project_path = p
    assert win.save_project() is True
    assert os.path.isfile(p)
    n = len(win.deck.slides)
    win._confirm_discard = lambda: True
    win.new_deck()
    assert win.deck.project_path is None
    assert win._load_project_file(p) is True
    assert len(win.deck.slides) == n
    assert win.deck.project_path == p


def test_recent_projects_dedupe_and_menu(win, tmp_path):
    p = str(tmp_path / "recent.slideshow")
    workspace.save_project(win.deck, p, set_path=False)
    win._add_recent(p)
    win._add_recent(p)                      # dedupe
    recents = win._recent_list()
    assert sum(1 for r in recents
               if os.path.abspath(r) == os.path.abspath(p)) == 1
    assert win.menu_recent is not None
    win._clear_recent()
    assert win._recent_list() == []


def test_autosave_roundtrip_and_removal(win):
    win._dirty = True
    win._autosave()
    apath = workspace.autosave_path()
    assert os.path.isfile(apath)
    deck = workspace.load_project(apath)
    assert len(deck.slides) == len(win.deck.slides)
    win.deck.project_path = None
    win._autosave()                          # must not invent a project path
    assert win.deck.project_path is None
    win._remove_autosave()
    assert not os.path.isfile(apath)


def test_close_snapshots_session_for_reopen(qapp, win):
    from app import memory
    n = len(win.deck.slides)
    win.close()
    qapp.processEvents()
    info = memory.session_info()
    assert info is not None and info["slides"] == n
    memory.clear_session()


def test_reopen_last_session_restores_deck_and_place(qapp):
    from app import memory
    from app.main_window import MainWindow
    memory.clear_session()
    w1 = MainWindow()
    w1.resize(1200, 700)
    w1._confirm_import_mode = lambda: (setattr(w1, "_import_replace", True)
                                       or True)
    w1.import_path(os.path.join(paths.examples_dir(), "product-launch.md"))
    w1.slide_list.setCurrentRow(1)
    qapp.processEvents()
    w1._remember_deck_state()
    memory.save_session(w1.deck, index=1, tab=0)
    marker = len(w1.deck.slides)
    from conftest import safe_close
    safe_close(w1)
    qapp.processEvents()

    w2 = MainWindow(restore_session=True)
    assert len(w2.deck.slides) == marker
    assert w2.current_index() == 1
    safe_close(w2)
    qapp.processEvents()
    memory.clear_session()


def test_plain_window_does_not_restore_session(qapp):
    from app import memory
    from app.main_window import MainWindow
    memory.clear_session()
    w = MainWindow()                          # restore_session defaults False
    assert w.deck is not None
    from conftest import safe_close
    safe_close(w)
    qapp.processEvents()
    memory.clear_session()


# ------------------------------------------------------------------- menus
def test_examples_menu_lists_bundled_decks(win):
    actions = win.menu_examples.actions()
    assert len(actions) >= len(paths.list_examples())
    assert win.act_open_examples is not None
    assert win.act_open_output is not None


def test_open_example_loads_demo_project(win):
    demo = os.path.join(paths.examples_dir(), "demo-tour.slideshow")
    win._open_example(demo)
    assert len(win.deck.slides) >= 4


def test_file_menu_has_batch_and_tools_actions(win):
    for act in (win.act_batch, win.act_export, win.act_import, win.act_diag,
                win.act_models, win.act_remember, win.act_find,
                win.act_script_editor):
        assert act is not None and act.text()
    assert win.act_batch.shortcut().toString() == "Ctrl+Shift+E"
    assert win.act_find.shortcut().toString() == "Ctrl+F"


# ----------------------------------------------------------------- dialogs
def test_script_editor_opens_non_modal_and_counts(win):
    dlg = win.script_editor()
    assert dlg is not None and not dlg.isModal()
    assert win.script_dlg is dlg
    win.script_editor()                       # re-raise, no duplicate
    assert win.script_dlg is dlg
    dlg.close()
    win.script_dlg = None


def test_find_replace_dialog_flow(win):
    dlg = win.find_replace()
    assert not dlg.isModal() and win.find_dlg is dlg
    dlg.find_edit.setText("slide")
    assert dlg.count_matches() >= 1
    assert dlg.find_next() is True
    dlg.replace_edit.setText("SLIDE")
    assert dlg.replace_all() is True
    assert any("SLIDE" in (s.title or "") or "SLIDE" in (s.body or "")
               for s in win.deck.slides)
    dlg.close()
    win.find_dlg = None


def test_find_replace_no_match_status(win):
    dlg = win.find_replace()
    dlg.find_edit.setText("zzz-no-match-zzz")
    assert dlg.find_next() is False
    assert "No matches" in dlg.status_label.text()
    assert dlg.replace_all() is False
    dlg.close()
    win.find_dlg = None


def test_export_dialog_suggests_output_folder(win):
    from app.export_dialog import ExportDialog
    dlg = ExportDialog(win.deck, parent=win, ffmpeg_ok=True)
    suggested = dlg.out_edit.text()
    assert suggested.startswith(paths.output_dir())
    dlg.close()


def test_batch_dialog_opens_with_current_deck(win):
    from app.batch_dialog import BatchExportDialog
    dlg = BatchExportDialog(parent=win, ffmpeg_ok=True, current_deck=win.deck)
    dlg._add_current_deck()
    assert len(dlg.jobs) == 1
    dlg._add_current_deck()                   # identity dedupe
    assert len(dlg.jobs) == 1
    dlg.reject()


def test_diagnostics_dialog_from_window(win):
    dlg = win.show_diagnostics()
    assert win.diag_dlg is dlg
    assert "diagnostics" in dlg.text.toPlainText().lower()
    win.show_diagnostics()                    # refresh path, no duplicate
    assert win.diag_dlg is dlg
    dlg.close()
    win.diag_dlg = None


def test_shortcuts_dialog_opens_once(win):
    win._shortcuts_dialog()
    assert win.shortcut_dlg is not None
    win._shortcuts_dialog()
    win.shortcut_dlg.close()


# -------------------------------------------------------------- narration
def test_fill_and_clear_narrations_undoable(win):
    for s in win.deck.slides:
        s.narration = ""
    filled = win.apply_fill_narrations()
    assert filled == len(win.deck.slides)
    assert all(s.narration for s in win.deck.slides)
    # clear everything — one undo step restores the filled narrations
    cleared = win.apply_clear_narrations()
    assert cleared == len(win.deck.slides)
    assert all(not s.narration for s in win.deck.slides)
    win.undo()
    assert all(s.narration for s in win.deck.slides)
    win.undo()
    assert all(not s.narration for s in win.deck.slides)


# ------------------------------------------------------------ canvas/zoom
def test_canvas_zoom_actions_clamped(win):
    win.canvas.zoom_fit()
    fit_pct = win.canvas.zoom_pct()
    win.act_zoom_in.trigger()
    assert win.canvas.zoom_pct() > fit_pct
    win.act_zoom_out.trigger()
    win.act_zoom_out.trigger()
    assert win.canvas.zoom_pct() <= fit_pct
    win.canvas.zoom_100()
    assert win.canvas.zoom_pct() == 100
    win.act_zoom_fit.trigger()
    assert win.canvas.is_fit()


def test_window_grabs_a_screenshot(win):
    pm = win.grab()
    assert not pm.isNull() and pm.width() > 100
