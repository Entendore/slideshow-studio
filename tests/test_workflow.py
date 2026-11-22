"""Guided input -> MP4 workflow: pipeline bar, Quick convert, export dialog
post-export actions (v2.2)."""
import os

import pytest

from app.models import Slide


# ------------------------------------------------------------------ #
# workflow bar
# ------------------------------------------------------------------ #
def test_workflow_bar_states_and_tips(qapp):
    from app.workflow import STEPS, TIPS, WorkflowBar

    bar = WorkflowBar()
    assert len(bar.chips()) == len(STEPS) == 4
    # fresh state: nothing done, current = Import
    assert bar.current_step() == 0
    assert bar.done_flags() == [False, False, False, False]
    assert bar.tip_label.text() == TIPS[0]
    states = [c.property("wfState") for c in bar.chips()]
    assert states == ["current", "todo", "todo", "todo"]

    bar.set_state([True, True, False, False])
    assert bar.current_step() == 2
    assert bar.tip_label.text() == TIPS[2]
    assert [c.property("wfState") for c in bar.chips()] == \
        ["done", "done", "current", "todo"]

    # all done -> current points at Export
    bar.set_state([True, True, True, True])
    assert bar.current_step() == 3
    assert [c.property("wfState") for c in bar.chips()] == \
        ["done", "done", "done", "current"]

    # same state again: no change, no crash (early-out path)
    bar.set_state([True, True, True, True])
    assert bar.current_step() == 3

    # click emits the step index
    got = []
    bar.stepClicked.connect(got.append)
    bar.chips()[1].click()
    assert got == [1]


def test_main_window_workflow_lifecycle(win, qapp):
    from app.models import Deck

    # fresh studio: welcome deck, nothing done
    assert win.workflow.current_step() == 0
    assert win.workflow.done_flags() == [False, False, False, False]

    # an import advances step 1
    deck = Deck()
    deck.new_slide(title="S1", body="b1")
    deck.new_slide(title="S2", body="b2")
    win._apply_import(list(deck.slides), True, "Imported")
    assert win._content_loaded
    assert win.workflow.done_flags()[0] is True
    assert win.workflow.current_step() == 1   # next: narrate

    # narrating (auto-fill) advances step 2
    win._workflow_narrate()
    assert win._narration_touched
    assert all(s.narration.strip() for s in win.deck.slides)
    assert win.workflow.done_flags()[1] is True
    assert win.workflow.current_step() == 2   # next: preview

    # playing advances step 3
    win._on_play_state(True)
    assert win._previewed
    assert win.workflow.done_flags()[2] is True
    assert win.workflow.current_step() == 3   # next: export

    # a finished export completes the pipeline
    win._on_external_export("/tmp/whatever.mp4")
    assert win._exported
    assert win.workflow.done_flags() == [True, True, True, True]

    # a new deck resets the whole pipeline
    win._confirm_discard = lambda: True
    win.new_deck()
    assert win.workflow.done_flags() == [False, False, False, False]
    assert win.workflow.current_step() == 0


def test_workflow_narrate_step_is_undoable(win, qapp):
    win._apply_import([Slide(title="T", body="B")], True, "Undo deck")
    before = win.deck.to_dict()
    win._workflow_narrate()
    assert win.deck.slides[0].narration.strip() == "T. B"
    win.undo()
    assert win.deck.to_dict() == before


def test_workflow_preview_step_guard(win, qapp):
    # an empty deck is handled gracefully: guard message, no crash
    win.deck.slides.clear()
    win._workflow_step(2)
    assert "no slides" in win.statusBar().currentMessage().lower()


# ------------------------------------------------------------------ #
# quick convert dialog
# ------------------------------------------------------------------ #
@pytest.fixture
def qc(qapp):
    from app.quick_convert import QuickConvertDialog
    dlg = QuickConvertDialog(parent=None, ffmpeg_ok=True)
    yield dlg
    dlg.reject()


def test_quick_convert_gating(qc, tmp_path):
    # empty queue -> Convert disabled
    assert not qc.queued_paths()
    assert not qc.btn_convert.isEnabled()
    # an unsupported / missing file is refused
    assert qc.add_paths([str(tmp_path / "missing.txt")]) == 0
    assert qc.add_paths(["/etc/hostname"]) == 0
    assert not qc.btn_convert.isEnabled()
    # a real supported file enables it
    f = tmp_path / "ok.txt"
    f.write_text("# Hello\nbody\n~ hi there\n", encoding="utf-8")
    assert qc.add_paths([str(f)]) == 1
    assert qc.btn_convert.isEnabled()
    # duplicates are skipped
    assert qc.add_paths([str(f)]) == 0
    assert len(qc.queued_paths()) == 1


def test_quick_convert_ffmpeg_gate(qapp, tmp_path):
    from app.quick_convert import QuickConvertDialog
    dlg = QuickConvertDialog(parent=None, ffmpeg_ok=False)
    assert dlg.warn_label.isVisibleTo(dlg)
    f = tmp_path / "x.txt"
    f.write_text("# X\nbody\n", encoding="utf-8")
    dlg.add_paths([str(f)])
    assert not dlg.btn_convert.isEnabled()
    dlg.reject()


def test_quick_convert_prepare_deck(qc):
    from app.models import Deck
    deck = Deck()
    deck.new_slide(title="T1", body="B1")            # no narration
    s2 = deck.new_slide(title="T2", body="B2", narration="custom")
    qc.narr_check.setChecked(True)
    idx = qc.voice_combo.findData("en-US-GuyNeural")
    assert idx > 0
    qc.voice_combo.setCurrentIndex(idx)
    deck = qc._prepare_deck(deck)
    assert deck.slides[0].narration.strip() == "T1. B1"
    assert deck.slides[1].narration.strip() == "custom"
    assert deck.default_voice.voice == "en-US-GuyNeural"
    # toggling the convenience off keeps narrations untouched
    qc.narr_check.setChecked(False)
    deck2 = Deck()
    deck2.new_slide(title="T3", body="B3")
    deck2 = qc._prepare_deck(deck2)
    assert deck2.slides[0].narration == ""


def test_quick_convert_list_ops(qc, tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.md"
    f3 = tmp_path / "c.txt"
    for i, f in enumerate((f1, f2, f3)):
        f.write_text(f"# T{i}\nbody\n", encoding="utf-8")
    qc.add_paths([str(f1), str(f2), str(f3)])
    assert len(qc.queued_paths()) == 3
    # remove the selected row
    qc.file_list.setCurrentRow(1)
    qc._remove_selected()
    assert len(qc.queued_paths()) == 2
    assert str(f2) not in qc.queued_paths()
    # clear empties the queue and disables Convert again
    qc._clear()
    assert qc.queued_paths() == []
    assert not qc.btn_convert.isEnabled()


def test_quick_convert_settings_roundtrip(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from app.quick_convert import QuickConvertDialog
    d1 = QuickConvertDialog(parent=None, ffmpeg_ok=True)
    d1.res_combo.setCurrentText("HD 1280×720")
    d1.trans_combo.setCurrentText("Crossfade")
    d1.trans_dur.setValue(0.5)
    d1.pad_spin.setValue(1.2)
    d1.narr_check.setChecked(False)
    d1.srt_check.setChecked(True)
    idx = d1.voice_combo.findData("en-US-JennyNeural")
    d1.voice_combo.setCurrentIndex(idx)
    d1._out_dir = str(tmp_path)
    d1._save_settings()
    d1.reject()

    d2 = QuickConvertDialog(parent=None, ffmpeg_ok=True)
    assert d2.res_combo.currentText() == "HD 1280×720"
    assert d2.trans_combo.currentText() == "Crossfade"
    assert abs(d2.trans_dur.value() - 0.5) < 1e-6
    assert abs(d2.pad_spin.value() - 1.2) < 1e-6
    assert not d2.narr_check.isChecked()
    assert d2.srt_check.isChecked()
    assert d2.voice_combo.currentData() == "en-US-JennyNeural"
    d2.reject()

    s = QSettings("ZaiStudio", "SlideshowStudio")
    for k in ("quick/res", "quick/transition", "quick/trans_dur",
              "quick/pad", "quick/auto_narr", "quick/srt", "quick/voice",
              "quick/out_dir"):
        s.remove(k)


# ------------------------------------------------------------------ #
# end-to-end: files in -> MP4 out (offline TTS stub + real ffmpeg)
# ------------------------------------------------------------------ #
@pytest.mark.slow
def test_quick_convert_end_to_end_mp4(stub_tts, qc, qapp, tmp_path, spin):
    from PySide6.QtCore import QSettings

    narrated = tmp_path / "with_narr.txt"
    narrated.write_text("# With\nbody\n~ spoken words\n", encoding="utf-8")
    bare = tmp_path / "no_narr.md"
    bare.write_text("# Bare\nbody text here\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    qc.res_combo.setCurrentText("SD 854×480")
    qc.srt_check.setChecked(True)
    qc.out_edit.setText(str(out_dir))
    got = []
    qc.exported.connect(got.append)
    qc.add_paths([str(narrated), str(bare)])
    qc._convert()

    ok = spin(lambda: not qc._running and
              qc._ok_count + qc._fail_count == 2, timeout_s=420)
    assert ok, "conversion did not finish"
    assert qc._ok_count == 2 and qc._fail_count == 0
    assert len(got) == 2
    mp4s = sorted(f for f in os.listdir(out_dir) if f.endswith(".mp4"))
    assert mp4s == ["no_narr.mp4", "with_narr.mp4"]
    for mp4 in mp4s:
        assert os.path.getsize(out_dir / mp4) > 10000
    srts = [f for f in os.listdir(out_dir) if f.endswith(".srt")]
    assert len(srts) == 2
    assert qc._last_out.endswith(".mp4")
    assert "2 MP4(s) exported" in qc.status_label.text()

    s = QSettings("ZaiStudio", "SlideshowStudio")
    for k in ("quick/res", "quick/srt", "quick/out_dir", "quick/voice",
              "quick/transition", "quick/trans_dur", "quick/pad",
              "quick/auto_narr"):
        s.remove(k)


@pytest.mark.slow
def test_quick_convert_cancel_and_failure(stub_tts, qc, qapp, tmp_path,
                                          spin):
    out_dir = tmp_path / "out2"
    good = tmp_path / "good.txt"
    good.write_text("# Good\nbody\n~ narr\n", encoding="utf-8")
    bad = tmp_path / "bad.slideshow"
    bad.write_bytes(b"PK\x03\x04 broken zip")
    qc.res_combo.setCurrentText("SD 854×480")
    qc.srt_check.setChecked(False)
    qc.out_edit.setText(str(out_dir))
    qc.add_paths([str(bad), str(good)])
    qc._convert()
    ok = spin(lambda: not qc._running and
              qc._ok_count + qc._fail_count == 2, timeout_s=420)
    assert ok
    # the broken project failed without breaking the queue
    assert qc._ok_count == 1 and qc._fail_count == 1
    assert os.path.isfile(out_dir / "good.mp4")
    assert "failed" in qc.status_label.text()
    # cancelling while idle simply closes
    qc._cancel_or_close()


# ------------------------------------------------------------------ #
# export dialog post-export actions
# ------------------------------------------------------------------ #
def test_export_dialog_post_export_actions(qapp, tmp_path, make_deck):
    from app.export_dialog import ExportDialog

    dlg = ExportDialog(make_deck(2, "D"), parent=None, ffmpeg_ok=True)
    assert not dlg.btn_play.isEnabled()
    assert not dlg.btn_open.isEnabled()
    assert dlg.btn_start.text() == "Start export"

    got = []
    dlg.exported.connect(got.append)
    out = tmp_path / "done.mp4"
    out.write_bytes(b"x" * 100)
    dlg._on_done(str(out))

    assert got == [str(out)]
    assert dlg.btn_play.isEnabled()
    assert dlg.btn_open.isEnabled()
    assert dlg.btn_start.text() == "Export again"
    assert "Saved to" in dlg.status_label.text()
    dlg.reject()


def test_export_dialog_open_when_finished_persists(qapp, make_deck):
    from PySide6.QtCore import QSettings

    from app.export_dialog import ExportDialog
    d1 = ExportDialog(make_deck(1), parent=None, ffmpeg_ok=True)
    d1.open_check.setChecked(True)
    d1._save_settings()
    d1.reject()
    d2 = ExportDialog(make_deck(1), parent=None, ffmpeg_ok=True)
    assert d2.open_check.isChecked()
    d2.open_check.setChecked(False)
    d2._save_settings()
    d2.reject()
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.remove("exp/open_folder")


def test_main_window_menu_and_toolbar_have_quick_convert(win, qapp):
    assert win.act_quick.text() == "Quick convert to MP4…"
    assert win.act_quick.shortcut().toString() == "Ctrl+M"
    # step-by-step access with every intermediate bound: chained one-liners
    # through QAction.menu() trip a PySide6 wrapper-ownership quirk
    menubar = win.menuBar()
    file_action = menubar.actions()[0]
    file_menu = file_action.menu()
    texts = [a.text() for a in file_menu.actions()]
    assert "Quick convert to MP4…" in texts
    assert texts.index("Quick convert to MP4…") < texts.index("Export…")
    # the studio holds its menus on the instance (GC-safe)
    assert win.menu_file is file_menu
    assert win.act_quick in win.toolbar.actions()
    assert win.act_quick.iconText() == "Quick MP4"
