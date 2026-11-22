"""v2.7 'Presets & waveform': named export presets in the export dialog
and the narration waveform strip under the preview canvas.

Fully offline: presets round-trip through a sandboxed QSettings, peaks
are decoded from a locally generated sine WAV, and the waveform widget
is exercised by grabbing pixmaps offscreen.
"""
import json
import os

import pytest

from app.presets import (LAST_PRESET_KEY, PRESETS_KEY, Preset,
                         factory_presets, find, load_presets, save_presets,
                         upsert)


# ------------------------------------------------------------------ #
# Preset model
# ------------------------------------------------------------------ #
def test_factory_presets_unique_and_populated():
    presets = factory_presets()
    assert len(presets) >= 8
    names = [p.name for p in presets]
    assert len(names) == len(set(names))
    modes = {p.mode for p in presets}
    assert {"mp4", "audio", "html", "pdf", "pptx"} <= modes


def test_preset_roundtrip_all_fields():
    p = Preset("Round trip", mode="mp4", resolution="HD 1280×720",
               audio_format="wav", pad=1.25, transition="Crossfade",
               transition_dur=1.1, save_srt=True, burn_subtitles=True,
               subtitle_size=22, notes=True, use_music=False,
               duck_music=False, open_folder=True)
    q = Preset.from_dict(p.to_dict())
    assert q.to_dict() == p.to_dict()


def test_preset_from_dict_degrades_bad_values():
    p = Preset.from_dict({
        "name": 123, "mode": "avi", "resolution": "8K", "audio_format": "flac",
        "pad": "not a number", "transition": "Explosion", "transition_dur": 99,
        "subtitle_size": None, "save_srt": "true", "notes": 1,
    })
    assert p.name == "123"                    # name is whatever it gets
    assert p.mode == "mp4"
    assert p.resolution == "Full HD 1920×1080"
    assert p.audio_format == "mp3"
    assert p.pad == 0.7                       # default after cast failure
    assert p.transition == "None"
    assert p.transition_dur == 2.0            # clamped to the max
    assert p.subtitle_size == 16
    assert p.save_srt is True and p.notes is True


def test_preset_from_dict_empty_and_none():
    a = Preset.from_dict({})
    b = Preset.from_dict(None)
    assert a.to_dict() == Preset("My preset").to_dict()
    assert b.to_dict() == Preset("My preset").to_dict()


def test_preset_describe_per_mode():
    assert "MP4" in Preset(mode="mp4").describe()
    assert "Full HD" in Preset(mode="mp4").describe()
    assert "srt" in Preset(mode="mp4", save_srt=True).describe()
    assert "burned subs" in Preset(mode="mp4", burn_subtitles=True,
                                   subtitle_size=20).describe()
    assert "MP3" in Preset(mode="audio").describe()
    assert "WAV" in Preset(mode="audio", audio_format="wav").describe()
    assert "notes" in Preset(mode="pdf", notes=True).describe()
    assert "PowerPoint" in Preset(mode="pptx").describe()
    assert "HTML" in Preset(mode="html").describe()
    assert "Crossfade" in Preset(mode="mp4",
                                 transition="Crossfade").describe()


def test_upsert_replaces_by_name_and_appends():
    base = factory_presets()
    n = len(base)
    merged = upsert(base, Preset("YouTube 1080p", mode="audio"))
    assert len(merged) == n                    # replaced, not duplicated
    assert find(merged, "YouTube 1080p").mode == "audio"
    merged2 = upsert(merged, Preset("Brand new"))
    assert len(merged2) == n + 1
    assert find(merged2, "Brand new") is not None
    assert find(base, "Brand new") is None     # input list untouched


# ------------------------------------------------------------------ #
# persistence
# ------------------------------------------------------------------ #
def test_load_presets_seeds_factory_once(qapp):
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.remove(PRESETS_KEY)
    first = load_presets(s)
    assert len(first) == len(factory_presets())
    # seeded into storage as real JSON
    data = json.loads(s.value(PRESETS_KEY))
    assert [d["name"] for d in data] == [p.name for p in first]
    # second load reads storage (no reseed churn)
    second = load_presets(s)
    assert [p.to_dict() for p in second] == [p.to_dict() for p in first]


def test_save_presets_roundtrip_with_edits(qapp):
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    presets = load_presets(s)
    presets = upsert(presets, Preset("My custom", mode="pdf", notes=True))
    presets = [p for p in presets if p.name != "Archive WAV"]
    save_presets(s, presets)
    again = load_presets(s)
    assert find(again, "My custom").mode == "pdf"
    assert find(again, "Archive WAV") is None
    # cleanup: restore factory seed for other tests
    s.remove(PRESETS_KEY)
    s.remove(LAST_PRESET_KEY)


def test_load_presets_corrupt_json_resets_to_factory(qapp):
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.setValue(PRESETS_KEY, "{definitely not json")
    loaded = load_presets(s)
    assert [p.name for p in loaded] == [p.name for p in factory_presets()]
    s.remove(PRESETS_KEY)
    s.remove(LAST_PRESET_KEY)


# ------------------------------------------------------------------ #
# export dialog integration
# ------------------------------------------------------------------ #
@pytest.fixture
def dlg(qtstub_defaults, make_deck):
    from app.export_dialog import ExportDialog
    d = ExportDialog(make_deck(2, name="Preset deck"))
    yield d
    d.close()


@pytest.fixture
def qtstub_defaults(qapp):
    """Start the dialog with factory presets and no remembered state."""
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.remove(PRESETS_KEY)
    s.remove(LAST_PRESET_KEY)
    for key in ("exp/mode_idx", "exp/res", "exp/pad", "exp/audio_fmt",
                "exp/transition", "exp/trans_dur", "exp/srt", "exp/burn",
                "exp/sub_size", "exp/music", "exp/duck", "exp/open_folder",
                "exp/notes"):
        s.remove(key)
    yield
    s.remove(PRESETS_KEY)
    s.remove(LAST_PRESET_KEY)


def test_dialog_seeds_and_lists_factory_presets(dlg):
    names = [dlg.preset_combo.itemText(i)
             for i in range(dlg.preset_combo.count())]
    assert names[0] == "(custom)"
    assert "YouTube 1080p" in names
    assert "Podcast MP3" in names
    assert dlg.preset_combo.count() == 1 + len(factory_presets())


def test_dialog_selecting_preset_applies_values(dlg):
    idx = dlg.preset_combo.findText("Podcast MP3")
    dlg.preset_combo.setCurrentIndex(idx)
    from app.export_dialog import MODE_KEYS
    assert MODE_KEYS[dlg.mode_combo.currentIndex()] == "audio"
    assert dlg.aud_combo.currentText() == "mp3"
    assert abs(dlg.pad_spin.value() - 0.6) < 1e-6
    assert "MP3" in dlg.status_label.text()

    idx = dlg.preset_combo.findText("Cinematic crossfade")
    dlg.preset_combo.setCurrentIndex(idx)
    assert MODE_KEYS[dlg.mode_combo.currentIndex()] == "mp4"
    assert dlg.trans_combo.currentText() == "Crossfade"
    assert abs(dlg.trans_dur.value() - 0.8) < 1e-6
    assert dlg.trans_dur.isEnabled()

    idx = dlg.preset_combo.findText("PDF handout + notes")
    dlg.preset_combo.setCurrentIndex(idx)
    assert MODE_KEYS[dlg.mode_combo.currentIndex()] == "pdf"
    assert not dlg.notes_check.isHidden()


def test_dialog_selected_preset_is_remembered(dlg):
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("Quick preview 720p"))
    assert s.value(LAST_PRESET_KEY) == "Quick preview 720p"
    dlg.preset_combo.setCurrentIndex(0)
    assert not s.value(LAST_PRESET_KEY, "")


def test_dialog_user_tweak_flips_to_custom(dlg):
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("Podcast MP3"))
    assert dlg.preset_combo.currentText() == "Podcast MP3"
    dlg.pad_spin.setValue(1.7)                 # manual edit
    assert dlg.preset_combo.currentText() == "(custom)"
    # applying another preset still works after going custom
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("Archive WAV"))
    assert dlg.aud_combo.currentText() == "wav"


def test_dialog_preset_save_upserts_and_persists(dlg, monkeypatch):
    from PySide6.QtCore import QSettings
    # choose a preset, tweak one value, save under a new name
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("Quick preview 720p"))
    dlg.pad_spin.setValue(0.5)
    monkeypatch.setattr(
        "app.export_dialog.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("My 720p half-sec", True)))
    dlg._preset_save()
    s = QSettings("ZaiStudio", "SlideshowStudio")
    stored = [Preset.from_dict(d) for d in json.loads(s.value(PRESETS_KEY))]
    mine = find(stored, "My 720p half-sec")
    assert mine is not None
    assert mine.mode == "mp4" and abs(mine.pad - 0.5) < 1e-6
    assert dlg.preset_combo.currentText() == "My 720p half-sec"
    # saving again with the same name overwrites
    dlg.pad_spin.setValue(0.9)
    dlg._preset_save()
    stored = [Preset.from_dict(d) for d in json.loads(s.value(PRESETS_KEY))]
    assert sum(1 for p in stored if p.name == "My 720p half-sec") == 1
    assert abs(find(stored, "My 720p half-sec").pad - 0.9) < 1e-6
    assert dlg.preset_combo.count() == 1 + len(stored)


def test_dialog_preset_save_empty_name_is_ignored(dlg, monkeypatch):
    n_before = dlg.preset_combo.count()
    monkeypatch.setattr(
        "app.export_dialog.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("   ", True)))
    dlg._preset_save()
    assert dlg.preset_combo.count() == n_before


def test_dialog_preset_delete_removes_and_persists(dlg):
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("Archive WAV"))
    assert dlg.btn_preset_del.isEnabled()
    dlg._preset_delete()
    names = [dlg.preset_combo.itemText(i)
             for i in range(dlg.preset_combo.count())]
    assert "Archive WAV" not in names
    stored = [Preset.from_dict(d) for d in json.loads(s.value(PRESETS_KEY))]
    assert find(stored, "Archive WAV") is None
    assert dlg.preset_combo.currentText() == "(custom)"
    assert not dlg.btn_preset_del.isEnabled()
    # deleting at "(custom)" is a safe no-op
    dlg._preset_delete()
    assert dlg.preset_combo.currentText() == "(custom)"


def test_dialog_delete_button_disabled_on_custom(dlg):
    assert not dlg.btn_preset_del.isEnabled()
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("Web page"))
    assert dlg.btn_preset_del.isEnabled()
    dlg.preset_combo.setCurrentIndex(0)
    assert not dlg.btn_preset_del.isEnabled()


def test_dialog_running_state_disables_preset_controls(dlg):
    dlg.preset_combo.setCurrentIndex(
        dlg.preset_combo.findText("YouTube 1080p"))
    dlg._set_running(True)
    assert not dlg.preset_combo.isEnabled()
    assert not dlg.btn_preset_save.isEnabled()
    assert not dlg.btn_preset_del.isEnabled()
    dlg._set_running(False)
    assert dlg.preset_combo.isEnabled()
    assert dlg.btn_preset_save.isEnabled()
    assert dlg.btn_preset_del.isEnabled()


def test_dialog_last_preset_restored_on_reopen(qtstub_defaults, make_deck):
    from app.export_dialog import ExportDialog
    from PySide6.QtCore import QSettings
    s = QSettings("ZaiStudio", "SlideshowStudio")
    d1 = ExportDialog(make_deck(1))
    d1.preset_combo.setCurrentIndex(
        d1.preset_combo.findText("Podcast MP3"))
    d1.close()
    d2 = ExportDialog(make_deck(1))
    assert d2.preset_combo.currentText() == "Podcast MP3"
    from app.export_dialog import MODE_KEYS
    assert MODE_KEYS[d2.mode_combo.currentIndex()] == "audio"
    d2.close()
    s.remove(PRESETS_KEY)
    s.remove(LAST_PRESET_KEY)


# ------------------------------------------------------------------ #
# waveform: peak extraction
# ------------------------------------------------------------------ #
@pytest.fixture(scope="module")
def sine_wav(tmp_path_factory):
    import subprocess
    path = str(tmp_path_factory.mktemp("wave") / "sine.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1.2", "-ar", "22050", path],
        check=True, capture_output=True)
    return path


def test_compute_peaks_shape_and_range(sine_wav):
    from app.waveform import BUCKETS, compute_peaks
    peaks = compute_peaks(sine_wav)
    assert len(peaks) == BUCKETS
    assert all(0.0 <= v <= 1.0 for v in peaks)
    assert max(peaks) > 0.05                 # audible tone
    assert min(peaks) >= 0.0


def test_compute_peaks_custom_bucket_count(sine_wav):
    from app.waveform import compute_peaks
    assert len(compute_peaks(sine_wav, buckets=64)) == 64
    assert len(compute_peaks(sine_wav, buckets=1)) == 1
    with pytest.raises(ValueError):
        compute_peaks(sine_wav, buckets=0)


def test_compute_peaks_silence_is_flat(sine_wav, tmp_path):
    import subprocess
    from app.waveform import compute_peaks
    silent = str(tmp_path / "silent.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=22050:cl=mono", "-t", "0.5", silent],
                   check=True, capture_output=True)
    peaks = compute_peaks(silent, buckets=32)
    assert max(peaks) < 0.01


def test_compute_peaks_missing_file_raises(sine_wav, tmp_path):
    from app.waveform import compute_peaks
    with pytest.raises(RuntimeError):
        compute_peaks(str(tmp_path / "nope.wav"))


# ------------------------------------------------------------------ #
# waveform: widget + loader
# ------------------------------------------------------------------ #
def test_waveform_bar_paint_states(qtstub_defaults, sine_wav):
    from app.waveform import WaveformBar
    w = WaveformBar()
    w.resize(640, 64)
    # hint state paints
    w.set_message("Narration waveform — no audio yet")
    assert not w.grab().isNull()
    # data state paints, progress moves, playing style toggles
    w.set_peaks([abs(i % 20 - 10) / 10.0 for i in range(200)])
    w.set_progress(0.35)
    w.set_playing(True)
    assert abs(w._frac - 0.35) < 1e-6
    assert not w.grab().isNull()
    w.set_playing(False)
    assert not w.grab().isNull()
    # progress clamps
    w.set_progress(2.0)
    assert w._frac == 1.0
    w.set_progress(-1.0)
    assert w._frac == 0.0


def test_waveform_bar_click_and_drag_seek(qtstub_defaults):
    from app.waveform import WaveformBar
    w = WaveformBar()
    w.resize(600, 64)
    w.set_peaks([0.5] * 100)
    seen = []
    w.seekRequested.connect(seen.append)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=QPoint(306, 32))
    assert seen and abs(seen[-1] - 0.5) < 0.02
    assert w._pressed
    QTest.mouseMove(w, QPoint(606, 32))
    assert abs(seen[-1] - 1.0) < 0.02
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=QPoint(606, 32))
    assert not w._pressed
    # click without data is ignored (no crash, no seek)
    w.set_message("empty")
    n = len(seen)
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(300, 32))
    assert len(seen) == n


def test_waveform_loader_async_and_stale_guard(qtstub_defaults, sine_wav,
                                               spin):
    from app.waveform import WaveformLoader
    results = []
    loader = WaveformLoader()
    loader.loaded.connect(lambda p, pk: results.append((p, pk)))
    loader.failed.connect(lambda p, e: results.append((p, e)))
    # request A then immediately B: only B's result may arrive
    loader.load(sine_wav)
    loader.load(sine_wav)
    assert spin(lambda: any(r[0] == sine_wav for r in results), 30)
    assert len(results) == 1
    loader.cancel()
    loader.wait(5000)
    assert not loader.isRunning()


def test_waveform_loader_bad_file_reports_failure(qtstub_defaults, tmp_path,
                                                  spin):
    from app.waveform import WaveformLoader
    bad = str(tmp_path / "garbage.wav")
    with open(bad, "wb") as f:
        f.write(b"this is not audio at all")
    results = []
    loader = WaveformLoader()
    loader.failed.connect(lambda p, e: results.append((p, e)))
    loader.load(bad)
    assert spin(lambda: bool(results), 30)
    assert results[0][0] == bad
    assert "ffmpeg" in results[0][1].lower()
    loader.cancel()
    loader.wait(5000)


def test_waveform_bar_show_path_loads_async(qtstub_defaults, sine_wav, spin):
    from app.waveform import WaveformBar
    w = WaveformBar()
    w.resize(600, 64)
    w.show_path(sine_wav)
    assert spin(lambda: w._peaks is not None, 30)
    assert w._path == sine_wav and len(w._peaks) == 900
    # same path again just resets the playhead (no reload)
    w.set_progress(0.7)
    w.show_path(sine_wav)
    assert w._frac == 0.0 and w._peaks is not None
    # empty path clears to a message
    w.show_path("")
    assert w._peaks is None and not w._path
    # a stale late result for the old path is dropped
    w._on_loaded(sine_wav, [0.1] * 10)
    assert w._peaks is None
    w.shutdown()


def test_waveform_bar_failure_message(qtstub_defaults, tmp_path, spin):
    from app.waveform import WaveformBar
    w = WaveformBar()
    w.resize(400, 64)
    bad = str(tmp_path / "notaudio.wav")
    with open(bad, "wb") as f:
        f.write(b"junk")
    w.show_path(bad)
    assert spin(lambda: "unavailable" in (w._msg or ""), 30)
    assert w._peaks is None
    assert not w.grab().isNull()
    w.shutdown()


# ------------------------------------------------------------------ #
# player position / seek plumbing
# ------------------------------------------------------------------ #
def test_player_position_and_seek_api(qapp):
    from PySide6.QtCore import QObject

    from app.player import PreviewPlayer

    class _Win(QObject):
        def current_index(self):
            return 0

    p = PreviewPlayer(_Win())
    seen = []
    p.positionChanged.connect(lambda pos, dur: seen.append((pos, dur)))
    p._on_position(1200)
    p._on_duration(4000)
    assert seen[-1] == (0, 4000)          # duration handler re-emits position
    p._on_position(2000)
    assert seen[-1] == (2000, 4000)
    # seek without a player / duration is a safe no-op
    p.seek_fraction(0.5)
    p._dur = 0
    p.seek_fraction(0.5)
    # clamping
    p._dur = 10000
    p._player = _FakePlayer()
    p.seek_fraction(1.5)
    assert p._player.position == 10000
    p.seek_fraction(-2)
    assert p._player.position == 0


class _FakePlayer:
    def __init__(self):
        self.position = -1

    def setPosition(self, pos):
        self.position = pos


def test_player_narration_signal_exists(qapp):
    from app.player import PreviewPlayer
    assert hasattr(PreviewPlayer, "narrationChanged")
    assert hasattr(PreviewPlayer, "positionChanged")


# ------------------------------------------------------------------ #
# main window integration
# ------------------------------------------------------------------ #
def test_main_window_waveform_present_and_wired(win, qapp):
    from app.waveform import WaveformBar
    assert isinstance(win.waveform, WaveformBar)
    # idle deck with no cached narration -> hint message
    assert "waveform" in win.waveform._msg.lower()
    # the seek wiring is connected end to end (player API absorbs it)
    win.player.seek_fraction(0.5)          # no player yet: safe no-op
    qapp.processEvents()


def test_main_window_idle_refresh_uses_cached_narration(win, qapp):
    slide = win.deck.slides[0]
    slide.narration = "Cached narration line."
    # pretend the preview already cached this narration (correct engine
    # extension and big enough to pass the cache sanity check)
    from app import tts
    key = tts.narration_cache_key(slide, win.deck)
    ext = tts._cache_ext(slide.effective_voice(win.deck).engine)
    cache_path = os.path.join(tts.narr_cache_dir(), f"{key}.{ext}")
    os.makedirs(tts.narr_cache_dir(), exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(b"\0" * 4096)
    try:
        win._refresh_waveform_idle()
        assert win.waveform._path == cache_path
        assert win.waveform._peaks is not None or \
            win.waveform._pending == cache_path
        qapp.processEvents()
    finally:
        if os.path.isfile(cache_path):
            os.remove(cache_path)
    win._refresh_waveform_idle()
    assert not win.waveform._path


def test_main_window_play_state_updates_waveform_flag(win, qapp):
    win._on_play_state(True)
    assert win.waveform._playing
    win._on_play_state(False)
    assert not win.waveform._playing
    qapp.processEvents()
