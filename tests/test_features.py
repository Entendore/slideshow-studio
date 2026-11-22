"""Feature surfaces: diagnostics report, voice-model manager, batch export."""
import os

import pytest
from PySide6.QtCore import Qt

from app import diagnostics, paths
from app.batch_dialog import (JOB_DONE, JOB_FAILED, BatchExportDialog,
                              kind_label, scan_folder, unique_path)
from app.models import Deck


# -------------------------------------------------------------- diagnostics
def test_collect_info_sections_without_deck():
    sections = diagnostics.collect_info()
    titles = [t for t, _rows in sections]
    for expected in ("Application", "Environment", "Media tools",
                     "Speech engines", "Storage", "Folders"):
        assert expected in titles
    rows = dict()
    for _t, rr in sections:
        rows.update(rr)
    assert rows["Version"]
    assert "ffmpeg" in rows["ffmpeg"] or rows["ffmpeg"] == \
        "NOT FOUND — MP4/audio export disabled"
    assert "Edge voices cached" in rows
    assert "Piper voices downloaded" in rows
    assert "Workspace" in rows and "Narration cache" in rows
    assert "Session snapshot" in rows and "Reopen at startup" in rows
    assert "Examples" in rows and "Output folder" in rows
    assert "Input folder" in rows and "Output layout" in rows
    assert "Recent folders" in rows


def test_collect_info_includes_deck_section(make_deck):
    d = make_deck(2)
    d.overlay_slide_numbers = True
    d.watermark_text = "WM"
    d.music_path = "/tmp/music.mp3"
    sections = diagnostics.collect_info(d)
    assert sections[-1][0] == "Current deck"
    rows = dict(sections[-1][1])
    assert rows["Slides"] == "2"
    assert rows["Narrations written"] == "2 / 2"
    assert "slide numbers" in rows["Overlays"]
    assert "watermark" in rows["Overlays"]
    assert rows["Music track"] == "/tmp/music.mp3"
    assert rows["Project file"] == "unsaved"


def test_format_report_layout(make_deck):
    report = diagnostics.format_report(diagnostics.collect_info(make_deck(1)))
    assert report.startswith("Slideshow Studio")
    assert "[Application]" in report and "[Storage]" in report
    assert " : " in report


def test_diagnostics_dialog_copy_to_clipboard(qapp, make_deck):
    from PySide6.QtWidgets import QApplication
    dlg = diagnostics.build_dialog(make_deck(2))
    assert "diagnostics" in dlg.text.toPlainText().lower()
    dlg._copy()
    cb = QApplication.clipboard()
    assert "Slideshow Studio" in (cb.text() or "")
    dlg.refresh(make_deck(5))
    assert "5" in dlg.text.toPlainText()
    dlg.close()


# ------------------------------------------------------------ voice models
def test_human_size_helper():
    from app.models_dialog import human_size
    assert human_size(0) == "—"
    assert human_size(500) == "500 B"
    assert "KB" in human_size(2048) and "MB" in human_size(5 * 1024 * 1024)


def test_models_dialog_lists_catalog_and_manages_models(qapp):
    from app import tts
    from app.models_dialog import VoiceModelsDialog
    dlg = VoiceModelsDialog()
    assert dlg.tree.topLevelItemCount() == len(tts.PIPER_VOICES) == 16
    # nothing installed in the sandbox -> not downloaded, download enabled
    dlg.tree.setCurrentItem(dlg.tree.topLevelItem(0))
    qapp.processEvents()
    assert dlg.selected_status() == "not downloaded"
    assert dlg.btn_download.isEnabled() and not dlg.btn_delete.isEnabled()
    # fake-install one model, refresh, delete it again
    vid = "piper:ru_RU-dmitri-medium"
    onnx, js = tts.piper_model_paths(vid)
    os.makedirs(os.path.dirname(onnx), exist_ok=True)
    try:
        with open(onnx, "wb") as fh:
            fh.write(b"\0" * 1_100_000)
        with open(js, "w", encoding="utf-8") as fh:
            fh.write("{}")
        dlg.populate()
        items = dlg.tree.findItems(vid, Qt.MatchFlag.MatchExactly, 0)
        assert items, "installed voice still listed"
        dlg.tree.setCurrentItem(items[0])
        qapp.processEvents()
        assert dlg.selected_status() == "installed"
        assert not dlg.btn_download.isEnabled() and dlg.btn_delete.isEnabled()
        dlg._confirm = lambda *a, **k: True          # test seam
        dlg._delete_selected()
        qapp.processEvents()
        assert tts.piper_voice_installed(vid) is False
    finally:
        for f in (onnx, js):
            if os.path.isfile(f):
                os.remove(f)
    dlg.populate()
    dlg.close()


def test_models_dialog_edge_cache_and_narration_clear(qapp,
                                                      fresh_narration_cache,
                                                      monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app import tts
    from app.models_dialog import VoiceModelsDialog
    # auto-answer the confirmation dialog (it is modal)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k:
                                     QMessageBox.StandardButton.Yes))
    # seed an edge voice cache so the label has something to show
    tts._write_cache(list(tts.FALLBACK_VOICES))
    dlg = VoiceModelsDialog()
    assert "Edge voice list" in dlg.cache_label.text()
    assert "Narration cache" in dlg.cache_label.text()
    # clear the narration cache through the dialog button
    d = tts.narr_cache_dir()
    with open(os.path.join(d, "x.mp3"), "wb") as fh:
        fh.write(b"x" * 1024)
    dlg._clear_narration_cache()
    qapp.processEvents()
    assert not [f for f in os.listdir(d) if f.endswith(".mp3")]
    # edge cache refresh path (no dialogs involved)
    dlg._refresh_edge_cache()
    assert tts._read_cache() is None
    dlg.close()


def test_models_dialog_emits_changed_signal(qapp, monkeypatch, tone_wav):
    """Download path: thread reports ok -> refresh + modelsChanged."""
    from PySide6.QtCore import QThread
    from app import tts
    from app import models_dialog as md

    vid = "piper:fr_FR-siwis-medium"
    onnx, js = tts.piper_model_paths(vid)
    os.makedirs(os.path.dirname(onnx), exist_ok=True)

    def fake_download(voice_id, progress=None):
        with open(onnx, "wb") as fh:
            fh.write(b"\0" * 1_100_000)
        with open(js, "w", encoding="utf-8") as fh:
            fh.write("{}")

    monkeypatch.setattr(tts, "download_piper_voice", fake_download)
    dlg = md.VoiceModelsDialog()
    items = dlg.tree.findItems(vid, Qt.MatchFlag.MatchExactly, 0)
    dlg.tree.setCurrentItem(items[0])
    got = []
    dlg.modelsChanged.connect(lambda: got.append(True))
    try:
        dlg._download_selected()
        # wait for the worker thread to finish
        assert dlg._thread is not None
        dlg._thread.wait(20000)
        for _ in range(50):
            qapp.processEvents()
            if got:
                break
            qapp.thread().msleep(20)
        assert got, "modelsChanged must fire after a successful download"
        assert tts.piper_voice_installed(vid) is True
    finally:
        tts.piper_delete_voice(vid)
    dlg.close()


# ------------------------------------------------------------------- batch
def test_kind_labels_for_every_source():
    assert kind_label("a.slideshow") == "Project"
    assert kind_label("a.pptx") == "PowerPoint"
    assert kind_label("a.pdf") == "PDF"
    assert kind_label("a.html") == "HTML"
    assert kind_label("a.txt") == "Text script"
    assert kind_label("a.md") == "Markdown"


def test_unique_path_sanitizes_and_uniquifies(tmp_path):
    folder = str(tmp_path)
    first = unique_path(folder, "My: Deck", "mp4")
    assert os.path.basename(first) == "My_ Deck.mp4"
    open(first, "w").close()
    second = unique_path(folder, "My: Deck", "mp4")
    assert second.endswith("My_ Deck-2.mp4")
    open(second, "w").close()
    third = unique_path(folder, "My: Deck", "mp4")
    assert third.endswith("My_ Deck-3.mp4")


def test_scan_folder_finds_importables_skips_hidden(tmp_path):
    (tmp_path / "a.txt").write_text("# A\nx\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\ny\n", encoding="utf-8")
    (tmp_path / "skip.exe").write_bytes(b"x")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "c.txt").write_text("# C\nz\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.slideshow").write_bytes(b"PK\x03\x04")
    found = [os.path.basename(f) for f in scan_folder(str(tmp_path))]
    assert sorted(found) == ["a.txt", "b.md", "d.slideshow"]


def test_batch_dialog_queue_management(qapp):
    dlg = BatchExportDialog(parent=None, ffmpeg_ok=True, current_deck=None)
    assert not dlg.btn_start.isEnabled()
    deck = Deck()
    deck.name = "Cur"
    deck.new_slide(title="s")
    dlg.current_deck = deck
    dlg._add_current_deck()
    assert len(dlg.jobs) == 1
    assert dlg.jobs[0].kind == "Current deck"
    dlg._add_current_deck()
    assert len(dlg.jobs) == 1, "identity dedupe"
    # file dedupe + remove + clear
    t1 = os.path.join(paths.examples_dir(), "getting-started.txt")
    assert dlg.add_paths([t1]) == 1
    assert dlg.add_paths([t1]) == 0
    assert len(dlg.jobs) == 2
    dlg.tree.selectAll()
    dlg._remove_selected()
    assert not dlg.jobs
    dlg._add_current_deck()
    dlg._clear_jobs()
    assert not dlg.jobs and not dlg.tree.topLevelItemCount()
    dlg.reject()


def test_batch_dialog_start_gating(qapp, tmp_path):
    dlg = BatchExportDialog(parent=None, ffmpeg_ok=False, current_deck=None)
    deck = Deck()
    deck.new_slide(title="s")
    dlg.current_deck = deck
    dlg._add_current_deck()
    # MP4 mode without ffmpeg: start disabled + warning visible
    dlg.mode_combo.setCurrentIndex(0)
    assert not dlg.btn_start.isEnabled()
    assert not dlg.warn_label.isHidden()
    # HTML mode works without ffmpeg
    dlg.mode_combo.setCurrentIndex(2)
    assert dlg.btn_start.isEnabled()
    assert dlg.warn_label.isHidden()
    dlg.reject()


def test_batch_dialog_settings_persist(qapp, tmp_path, make_deck):
    from PySide6.QtCore import QSettings
    d1 = BatchExportDialog(parent=None, ffmpeg_ok=True,
                           current_deck=make_deck(1))
    d1.mode_combo.setCurrentIndex(2)
    d1.pad_spin.setValue(1.1)
    d1.srt_check.setChecked(True)
    d1._out_dir = str(tmp_path)
    d1._save_settings()
    d2 = BatchExportDialog(parent=None, ffmpeg_ok=True,
                           current_deck=make_deck(1))
    assert d2.mode_combo.currentIndex() == 2
    assert abs(d2.pad_spin.value() - 1.1) < 1e-6
    assert d2.srt_check.isChecked()
    d1.reject()
    d2.reject()
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.remove("batch/mode_idx")
    s.remove("batch/pad")
    s.remove("batch/srt")
    s.remove("batch/out_dir")


@pytest.mark.slow
def test_batch_end_to_end_html(qapp, tmp_path, spin):
    out_dir = str(tmp_path / "out")
    src = tmp_path / "src"
    src.mkdir()
    (src / "one.txt").write_text("# One\nbody one\n~ narr one\n",
                                 encoding="utf-8")
    (src / "two.md").write_text("# Two\nbody two\n", encoding="utf-8")
    dlg = BatchExportDialog(parent=None, ffmpeg_ok=True, current_deck=None)
    dlg.mode_combo.setCurrentIndex(2)                 # HTML
    dlg.open_check.setChecked(False)                  # don't pop a browser
    dlg.out_edit.setText(out_dir)
    dlg.add_paths([str(src / "one.txt"), str(src / "two.md")])
    assert len(dlg.jobs) == 2
    dlg._start()
    ok = spin(lambda: not dlg._running and dlg._n_done == 2, timeout_s=120)
    assert ok
    assert dlg._ok_count == 2 and dlg._fail_count == 0
    for job in dlg.jobs:
        assert job.status == JOB_DONE
        assert os.path.isfile(job.out_path)
        assert job.out_path.endswith(".html")
    assert "2 exported" in dlg.status_label.text()


@pytest.mark.slow
def test_batch_end_to_end_mp4_with_failure(stub_tts, qapp, tmp_path, spin):
    out_dir = str(tmp_path / "out")
    good = tmp_path / "good.txt"
    good.write_text("# Good\nbody\n~ narration here\n", encoding="utf-8")
    bad = tmp_path / "bad.slideshow"
    bad.write_bytes(b"PK\x03\x04 broken zip")
    dlg = BatchExportDialog(parent=None, ffmpeg_ok=True, current_deck=None)
    dlg.mode_combo.setCurrentIndex(0)                 # MP4
    dlg.res_combo.setCurrentText("SD 854×480")
    dlg.music_check.setChecked(False)
    dlg.srt_check.setChecked(True)
    dlg.trans_combo.setCurrentText("None")
    dlg.open_check.setChecked(False)
    dlg.out_edit.setText(out_dir)
    dlg.add_paths([str(good), str(bad)])
    dlg._start()
    ok = spin(lambda: not dlg._running and
              dlg._ok_count + dlg._fail_count == 2, timeout_s=420)
    assert ok
    assert dlg._ok_count == 1 and dlg._fail_count == 1
    ok_jobs = [j for j in dlg.jobs if j.status == JOB_DONE]
    failed = [j for j in dlg.jobs if j.status == JOB_FAILED]
    assert len(ok_jobs) == 1 and len(failed) == 1
    assert os.path.isfile(ok_jobs[0].out_path)
    assert ok_jobs[0].out_path.endswith(".mp4")
    assert failed[0].detail, "failure reason shown in Details"
    assert os.path.isfile(os.path.splitext(ok_jobs[0].out_path)[0] + ".srt")


@pytest.mark.slow
def test_batch_cancel_before_worker_starts(stub_tts, qapp, tmp_path, spin):
    out_dir = str(tmp_path / "out")
    files = []
    for i in range(3):
        p = tmp_path / f"cc{i}.txt"
        p.write_text(f"# C{i}\nbody {i}\n~ narration {i}\n",
                     encoding="utf-8")
        files.append(str(p))
    dlg = BatchExportDialog(parent=None, ffmpeg_ok=True, current_deck=None)
    dlg.mode_combo.setCurrentIndex(0)
    dlg.res_combo.setCurrentText("SD 854×480")
    dlg.open_check.setChecked(False)
    dlg.out_edit.setText(out_dir)
    dlg.add_paths(files)
    dlg._start()
    dlg._cancel_or_close()          # cancel before the first worker starts
    ok = spin(lambda: not dlg._running, timeout_s=120)
    assert ok
    assert dlg._ok_count == 0
    assert dlg._skip_count == 3
    assert "0 exported" in dlg.status_label.text()
    assert not [f for f in os.listdir(out_dir) if f.endswith(".mp4")]


def test_batch_job_load_slideshow_project(qapp, tmp_path, make_deck):
    from app import workspace
    dlg = BatchExportDialog(parent=None, ffmpeg_ok=True, current_deck=None)
    p = str(tmp_path / "proj.slideshow")
    workspace.save_project(make_deck(3, "Loaded"), p)
    deck = dlg._load_deck(type("J", (), {"path": p, "deck": None})())
    assert deck.name == "Loaded" and len(deck.slides) == 3
