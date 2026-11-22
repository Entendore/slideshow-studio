"""v2.6 "Present like a pro & finer control".

Rehearse timings (window, clock, apply), presenter notes in present
mode, per-slide transition overrides (model + inspector + ffmpeg graph)
and slide -> image export (file & clipboard).
"""
import os

import pytest

from app import media
from app.export_worker import (ExportOptions, ExportWorker, TRANSITIONS,
                               transition_graph)
from app.models import TRANSITION_NAMES, Deck, Slide
from app.rehearse import RehearseWindow, format_summary


# ------------------------------------------------------------------ helpers
def _clock_win(deck, qapp, start=0):
    """RehearseWindow with an injectable fake clock, re-anchored."""
    import time
    win = RehearseWindow(deck, start=start)
    t = {"v": time.monotonic()}
    win._now = lambda: t["v"]
    win._t0 = t["v"]
    win._run_t0 = t["v"]
    win._secs = [0.0] * len(deck.slides)
    win._fake = t
    return win


def _advance(win, secs):
    win._fake["v"] += secs


def _feature_deck(make_deck):
    d = make_deck(2, "Transitions deck")
    return d


def _run_worker(deck, opts, spin):
    result = {"ok": None, "err": None, "cancelled": False}

    def on_ok(p):
        result["ok"] = p

    def on_err(m):
        result["err"] = m

    w = ExportWorker(deck, opts)
    w.finished_ok.connect(on_ok)
    w.failed.connect(on_err)
    w.cancelled.connect(lambda: result.update(cancelled=True))
    w.start()
    done = spin(lambda: result["ok"] is not None or result["err"] is not None
                or result["cancelled"], timeout_s=420)
    if not done:
        w.cancel()
    w.wait(15000)
    return result


# ===================================================================== #
# rehearse timings
# ===================================================================== #
def test_rehearse_window_basics(make_deck, qapp):
    d = make_deck(3)
    win = _clock_win(d, qapp)
    try:
        assert win.total() == 3 and win.index() == 0
        assert "REHEARSING" in win.pos_label.text()
        assert "1/3" in win.pos_label.text()
        assert "Esc finish" in win.hint.text()
    finally:
        win.close()
        qapp.processEvents()


def test_rehearse_navigation_clamps(make_deck, qapp):
    d = make_deck(2)
    win = _clock_win(d, qapp)
    try:
        win.go_prev()                      # already first
        assert win.index() == 0
        win.go_next()
        win.go_next()                      # already last -> holds
        assert win.index() == 1
        win.go_to(99)
        assert win.index() == 1
    finally:
        win.close()
        qapp.processEvents()


def test_rehearse_records_time(make_deck, qapp):
    d = make_deck(3)
    win = _clock_win(d, qapp)
    try:
        _advance(win, 4.0)
        win.go_next()
        assert abs(win.timings()[0] - 4.0) < 1e-6
        _advance(win, 2.5)
        win.go_next()
        assert abs(win.timings()[1] - 2.5) < 1e-6
        assert win.timings()[2] == 0.0
    finally:
        win.close()
        qapp.processEvents()


def test_rehearse_revisit_adds_up(make_deck, qapp):
    d = make_deck(2)
    win = _clock_win(d, qapp)
    try:
        _advance(win, 4.0)
        win.go_next()
        _advance(win, 2.5)
        win.go_to(0)                       # back to slide 1
        _advance(win, 1.0)
        win.go_next()                      # forward again
        _advance(win, 1.0)
        win.finish()                       # bank current (slide 2)
        t = win.timings()
        assert abs(t[0] - 5.0) < 1e-6, t
        assert abs(t[1] - 3.5) < 1e-6, t
    finally:
        qapp.processEvents()


def test_rehearse_finish_banks_current_and_signals(make_deck, qapp):
    d = make_deck(3)
    win = _clock_win(d, qapp)
    got = []
    win.finishedRun.connect(got.append)
    try:
        _advance(win, 3.0)
        win.finish()                       # Esc: bank current, emit, close
        assert len(got) == 1
        assert abs(got[0][0] - 3.0) < 1e-6
        assert got[0][1] == 0.0
    finally:
        qapp.processEvents()


def test_rehearse_clock_and_total(make_deck, qapp):
    d = make_deck(2)
    win = _clock_win(d, qapp)
    try:
        _advance(win, 65.0)
        win._update_clock()
        assert "1:05" in win.clock_label.text()
        assert abs(win.total_elapsed() - 65.0) < 1e-6
        assert abs(win.elapsed_slide_seconds() - 65.0) < 1e-6
    finally:
        win.close()
        qapp.processEvents()


def test_rehearse_empty_deck_is_safe(qapp):
    win = RehearseWindow(Deck())
    try:
        assert win.total() == 0
        win.go_next()                      # no-op
        win.finish()                       # emits [ ]
    finally:
        qapp.processEvents()


def test_format_summary():
    s = format_summary([65.0, 0.0, 12.4])
    assert "Slide 1 — 1:05" in s
    assert "Slide 2 — (not rehearsed)" in s
    assert "Slide 3 — 0:12" in s
    assert format_summary([]) == "Nothing recorded."


def test_main_window_rehearse_flow(win, qapp, monkeypatch):
    win.deck.new_slide(title="R1", narration="a")
    win.deck.new_slide(title="R2", narration="b")
    n = len(win.deck.slides)
    win.rehearse_timings()
    assert win.rehearse_win is not None
    rw = win.rehearse_win
    monkeypatch.setattr(win, "_ask_apply_rehearsal", lambda times: True)
    times = [0.0] * (n - 2) + [7.0, 0.0]
    rw.finishedRun.emit(times)
    qapp.processEvents()
    assert win.rehearse_win is None
    assert abs(win.deck.slides[-2].duration_override - 7.0) < 1e-6
    assert win.deck.slides[-1].duration_override == 0.0
    # one undo step restores the pre-rehearsal durations
    win.undo()
    assert win.deck.slides[-2].duration_override == 0.0
    # discard path leaves the deck untouched
    win.rehearse_timings()
    rw2 = win.rehearse_win
    monkeypatch.setattr(win, "_ask_apply_rehearsal", lambda times: False)
    rw2.finishedRun.emit([4.0] * n)
    qapp.processEvents()
    assert win.deck.slides[-2].duration_override == 0.0
    assert win.rehearse_win is None


def test_main_window_rehearse_empty_deck(win, qapp):
    win.deck.slides.clear()
    win.rehearse_timings()
    assert win.rehearse_win is None


def test_main_window_closeEvent_closes_rehearse(qapp):
    from app.main_window import MainWindow
    from conftest import safe_close
    w = MainWindow()
    w.deck.new_slide(title="X", narration="y")
    w.rehearse_timings()
    assert w.rehearse_win is not None
    safe_close(w)
    qapp.processEvents()
    assert w.rehearse_win is None


# ===================================================================== #
# presenter notes overlay
# ===================================================================== #
def _present(deck, qapp, **kw):
    from app.present import PresentWindow
    p = PresentWindow(deck, **kw)
    t = {"v": 1000.0}
    p._now = lambda: t["v"]
    p._slide_t0 = t["v"]
    p._fake = t
    p.show()
    qapp.processEvents()
    return p


def test_present_notes_toggle(make_deck, qapp):
    p = _present(make_deck(2), qapp, auto_advance=False)
    try:
        assert not p.is_showing_notes()
        assert not p.notes_label.isVisible()
        p._toggle_notes()
        assert p.is_showing_notes() and p.notes_label.isVisible()
        p._toggle_notes()
        assert not p.is_showing_notes()
        assert not p.notes_label.isVisible()
    finally:
        p.close()
        qapp.processEvents()


def test_present_notes_content(make_deck, qapp):
    p = _present(make_deck(2), qapp, auto_advance=False)
    try:
        p._toggle_notes()
        assert "Narration for slide 1." in p.notes_text()
        assert "NOTES · SLIDE 1/2" in p.notes_label.text()
        p.go_next()
        assert "Narration for slide 2." in p.notes_text()
        assert "2/2" in p.notes_label.text()
    finally:
        p.close()
        qapp.processEvents()


def test_present_notes_fallback_and_empty(make_deck, qapp):
    d = make_deck(2)
    d.slides[0].narration = ""               # falls back to title + body
    d.slides[1].narration = ""
    d.slides[1].title = ""
    d.slides[1].body = ""
    p = _present(d, qapp, auto_advance=False)
    try:
        p._toggle_notes()
        assert "Slide 1" in p.notes_text() and "Body of slide 1" \
            in p.notes_text()
        p.go_next()
        assert "No speaker notes" in p.notes_label.text()
    finally:
        p.close()
        qapp.processEvents()


def test_present_notes_clock_ticks(make_deck, qapp):
    d = make_deck(2)                     # 2 slides so go_next can advance
    p = _present(d, qapp, auto_advance=False)
    try:
        p._toggle_notes()
        p._fake["v"] += 75.0
        p._update_notes()
        assert abs(p.elapsed_slide_seconds() - 75.0) < 1e-6
        assert "1:15" in p.notes_label.text()
        p.go_next()                      # clock resets per slide
        assert abs(p.elapsed_slide_seconds()) < 1e-6
        assert "NOTES · SLIDE 2/2" in p.notes_label.text()
    finally:
        p.close()
        qapp.processEvents()


def test_present_hint_mentions_notes(make_deck, qapp):
    p = _present(make_deck(1), qapp, auto_advance=False)
    try:
        assert "N notes" in p.hint.text()
    finally:
        p.close()
        qapp.processEvents()


def test_present_close_stops_notes_timer(make_deck, qapp):
    p = _present(make_deck(1), qapp, auto_advance=False)
    p._toggle_notes()
    assert p._notes_timer.isActive()
    p.close()
    qapp.processEvents()
    assert not p._notes_timer.isActive()


# ===================================================================== #
# per-slide transition overrides
# ===================================================================== #
def test_transition_model_roundtrip():
    s = Slide(title="t", transition="Wipe right")
    assert Slide.from_dict(s.to_dict()).transition == "Wipe right"
    assert Slide().transition == ""          # deck default
    assert Slide().to_dict()["transition"] == ""
    assert Slide.from_dict({"transition": "Bogus"}).transition == ""
    assert Slide.from_dict({}).transition == ""


def test_transitions_mapping_covers_labels():
    from app.export_worker import _XFADE
    assert len(TRANSITIONS) == len(TRANSITION_NAMES)
    assert TRANSITIONS["None"] is None
    for name in TRANSITION_NAMES[1:]:
        assert TRANSITIONS[name] == _XFADE[name]


def test_transition_graph_all_xfade():
    g, fv, fa = transition_graph([5.0, 4.0, 3.0], ["fade", "fadeblack"], 1.0)
    # join 1 enters at durs[0]-t; join 2 at the accumulated timeline - t
    assert "xfade=transition=fade:duration=1.000:offset=4.000" in g
    assert "xfade=transition=fadeblack:duration=1.000:offset=7.000" in g
    assert "[v1][2:v]" in g and fa == "a2" and fv == "v2"
    assert g.count("xfade") == 2 and g.count("acrossfade") == 2


def test_transition_graph_mixed_cut():
    g, fv, fa = transition_graph([5.0, 4.0, 3.0], [None, "fade"], 1.0)
    assert "concat=n=2:v=1:a=0[v1]" in g     # hard cut joins 1 -> 2
    assert "concat=n=2:v=0:a=1[a1]" in g
    # the fade then enters at (5+4) - 1
    assert "xfade=transition=fade:duration=1.000:offset=8.000" in g
    assert g.count("xfade") == 1 and g.count("acrossfade") == 1


def test_transition_graph_mixed_normalises_operands():
    g, _, _ = transition_graph([5.0, 4.0, 3.0], [None, "fade"], 1.0, fps=30)
    # concat output AND the direct segment are normalised to AVTB/30fps
    # before the xfade (ffmpeg rejects a raw concat -> xfade chain)
    assert "[v1]settb=AVTB,fps=30[vn2a]" in g, g
    assert "[2:v]settb=AVTB,fps=30[vn2b]" in g, g
    assert "[vn2a][vn2b]xfade=transition=fade" in g, g
    # all-xfade graphs stay un-normalised even with fps given
    g2, _, _ = transition_graph([5.0, 4.0], ["fade"], 1.0, fps=30)
    assert "settb" not in g2


def test_transition_graph_single_segment():
    assert transition_graph([5.0], [], 1.0) == ("", "0:v", "0:a")


def test_worker_join_names(make_deck):
    d = make_deck(3)
    w = ExportWorker(d, ExportOptions())     # deck default: None
    assert w._join_names(d.slides) == [None, None]
    w2 = ExportWorker(d, ExportOptions(transition="Crossfade"))
    assert w2._join_names(d.slides) == ["fade", "fade"]
    d.slides[1].transition = "None"          # force a cut on slide 2
    d.slides[2].transition = "Wipe right"
    assert w2._join_names(d.slides) == [None, "wiperight"]
    d.slides[2].transition = "Bogus"         # unknown -> deck default
    assert w2._join_names(d.slides) == [None, "fade"]


def test_inspector_transition_roundtrip(win, qapp):
    win.deck.new_slide(title="T", narration="n")
    s = win.deck.slides[-1]
    win.inspector.set_slide(s)
    combo = win.inspector.trans_combo
    assert combo.currentText() == "— Deck default —"
    combo.setCurrentIndex(combo.findText("Circle open"))
    assert s.transition == "Circle open"
    combo.setCurrentIndex(combo.findText("None"))
    assert s.transition == "None"
    combo.setCurrentIndex(0)
    assert s.transition == ""
    win.inspector.set_slide(s)               # reload shows the same value
    combo.setCurrentIndex(combo.findText("Dissolve"))
    win.inspector.set_slide(win.deck.slides[0])
    assert win.deck.slides[-1].transition == "Dissolve"


def test_diagnostics_reports_transition_and_durations(win, qapp):
    win.deck.new_slide(title="D", narration="n", transition="Crossfade",
                       duration_override=9.0)
    from app.diagnostics import collect_info
    text = "\n".join(f"{k}: {v}" for _t, rows in collect_info(win.deck)
                     for k, v in rows)
    assert "Per-slide transition overrides: 1" in text
    assert "Minimum durations set: 1" in text


# ===================================================================== #
# slide -> image
# ===================================================================== #
def test_slide_image_export_file(win, qapp, tmp_path):
    out = str(tmp_path / "slide.png")
    assert win.export_slide_image(out) == out
    assert os.path.isfile(out) and os.path.getsize(out) > 5000
    from PySide6.QtGui import QImage
    img = QImage(out)
    assert img.width() == 2000 and img.height() == 1125   # 16:9


def test_slide_image_export_no_slide(win, qapp, tmp_path):
    win.deck.slides.clear()
    win.inspector.set_slide(None)
    assert win.export_slide_image(str(tmp_path / "x.png")) == ""


def test_slide_image_copy_clipboard(win, qapp):
    from PySide6.QtGui import QGuiApplication
    win.copy_slide_image()
    pm = QGuiApplication.clipboard().pixmap()
    assert pm.width() == 2000 and pm.height() == 1125


def test_slide_image_actions_exist(win, qapp):
    assert win.act_slide_png.text() == "Export current slide as image…"
    assert win.act_slide_copy.text() == "Copy slide image"
    assert win.act_slide_copy.shortcut().toString() == "Ctrl+Shift+C"


def test_slide_image_no_slide_copy(win, qapp):
    win.deck.slides.clear()
    win.inspector.set_slide(None)
    win.copy_slide_image()                   # must not raise


# ===================================================================== #
# minimum-duration semantics
# ===================================================================== #
def test_duration_override_is_minimum_with_audio(make_deck, stub_tts):
    d = make_deck(2)
    d.slides[0].duration_override = 2.5      # > tone(0.4) + pad(0.3)
    d.slides[1].duration_override = 0.1      # < audio -> ignored
    w = ExportWorker(d, ExportOptions(pad=0.3))
    durs = w._slide_durations(d.slides, [stub_tts, stub_tts])
    assert abs(durs[0] - 2.5) < 1e-6, durs
    assert abs(durs[1] - 0.7) < 1e-6, durs   # 0.4 s tone + 0.3 s pad


def test_duration_override_without_audio(make_deck):
    d = make_deck(2)
    d.slides[0].duration_override = 12.0
    d.slides[1].duration_override = 0.0
    w = ExportWorker(d, ExportOptions())
    durs = w._slide_durations(d.slides, ["", ""])
    assert durs == [12.0, 3.0]


# ===================================================================== #
# slow: real ffmpeg run with a per-slide transition override
# ===================================================================== #
@pytest.mark.slow
def test_export_mp4_per_slide_transition(stub_tts, make_deck, spin,
                                         tmp_path):
    deck = _feature_deck(make_deck)
    deck.slides[1].transition = "Circle open"   # deck-wide default: None
    out = str(tmp_path / "per_slide.mp4")
    result = _run_worker(
        deck, ExportOptions(mode="mp4", resolution="SD 854×480", pad=0.3,
                            use_music=False, out_path=out), spin)
    assert result["ok"] == out, result["err"] or "cancelled"
    assert os.path.isfile(out) and os.path.getsize(out) > 10000
    assert media.media_duration(out) > 1.0


@pytest.mark.slow
def test_export_mp4_mixed_transitions(stub_tts, make_deck, spin, tmp_path):
    deck = make_deck(3, "Mixed")
    deck.slides[1].transition = "None"          # hard cut
    deck.slides[2].transition = "Crossfade"     # fade in on slide 3
    out = str(tmp_path / "mixed.mp4")
    result = _run_worker(
        deck, ExportOptions(mode="mp4", resolution="SD 854×480", pad=0.3,
                            use_music=False, out_path=out,
                            transition="None"), spin)
    assert result["ok"] == out, result["err"] or "cancelled"
    assert media.media_duration(out) > 1.5
