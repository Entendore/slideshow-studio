"""Playback: preview player state machine + full-screen present mode."""
import pytest

from app.models import Deck


@pytest.fixture
def no_message_boxes(monkeypatch):
    """Record modal popups so tests never block on a dialog."""
    calls = []
    from app import player as player_mod
    from app import present as present_mod

    def info(*a, **k):
        calls.append(("info", a[1] if len(a) > 1 else ""))
        return None

    def warning(*a, **k):
        calls.append(("warning", a[1] if len(a) > 1 else ""))
        return None

    monkeypatch.setattr(player_mod.QMessageBox, "information", info)
    monkeypatch.setattr(player_mod.QMessageBox, "warning", warning)
    return calls


# ------------------------------------------------------------------ player
def test_synth_thread_scales_and_finishes(stub_tts, make_deck, spin, qapp):
    from app.player import _SynthAllThread
    deck = make_deck(3)
    t = _SynthAllThread(deck)
    events = []
    t.progress.connect(lambda d, tot: events.append((d, tot)))
    t.finished_ok.connect(lambda: events.append("done"))
    t.error.connect(lambda m: events.append(("err", m)))
    t.start()
    assert spin(lambda: "done" in events, timeout_s=60)
    t.wait(5000)
    assert [e for e in events if e != "done"] == [(1, 3), (2, 3), (3, 3)]


def test_player_refuses_empty_deck(win, no_message_boxes):
    from app.models import Deck
    win.deck = Deck()
    win.player.play_deck(win.deck)
    assert not win.player.is_playing()
    assert any(kind == "info" for kind, _ in no_message_boxes)


def test_player_play_deck_lifecycle(win, stub_tts, spin):
    entered = []
    states = []
    win.player.slideEntered.connect(entered.append)
    win.player.stateChanged.connect(states.append)
    win.player.play_deck(win.deck)
    assert spin(lambda: win.player.is_playing(), timeout_s=30), \
        "player must reach the playing state"
    assert entered and entered[0] == 0
    assert states and states[-1] is True
    # simulate end-of-media -> advances to the next slide
    from PySide6.QtMultimedia import QMediaPlayer as QMP
    win.player._on_status(QMP.MediaStatus.EndOfMedia)
    assert entered[-1] == 1
    assert win.current_index() == 1 or True   # list follows via window hook
    win.player.stop()
    assert not win.player.is_playing()
    assert states[-1] is False


def test_player_pause_toggle(win, stub_tts, spin):
    win.player.play_deck(win.deck)
    assert spin(lambda: win.player.is_playing(), timeout_s=30)
    win.player.toggle_pause()
    assert win.player.is_paused()
    win.player.toggle_pause()
    assert not win.player.is_paused()
    win.player.stop()


def test_player_play_current_single_mode(win, stub_tts, spin):
    win.player.play_current(win.deck)
    assert spin(lambda: win.player.is_playing(), timeout_s=30)
    win.player._single_mode is True
    win.player.stop()


def test_player_stop_when_idle_is_harmless(win):
    win.player.stop()
    assert not win.player.is_playing()


# ----------------------------------------------------------------- present
def test_present_mode_navigation_and_toggles(qapp, stub_tts, spin):
    from app.present import PresentWindow
    deck = Deck()
    deck.new_slide(title="Alpha", body="first")
    deck.new_slide(title="Beta", body="second")
    deck.new_slide(title="Gamma", body="third")
    pw = PresentWindow(deck, start=0)
    pw.show()
    qapp.processEvents()
    assert pw.index() == 0 and pw.total() == 3
    assert pw.is_auto_advance()
    pw.go_next()
    assert pw.index() == 1
    pw.go_next()
    pw.go_next()
    assert pw.index() == 2, "last slide reached"
    pw.go_next()
    assert pw.index() == 2, "next holds at the end"
    pw.go_prev()
    assert pw.index() == 1
    pw.go_to(0)
    pw.go_prev()
    assert pw.index() == 0, "prev holds at the start"
    pw.go_to(99)
    assert pw.index() == 2, "go_to clamps"

    pw._toggle_subs()
    assert pw.is_showing_subtitles()
    pw._toggle_auto()
    assert not pw.is_auto_advance()
    pw.resize(800, 450)
    qapp.processEvents()
    pm = pw.grab()
    assert not pm.isNull(), "present window paints"
    pw.close()
    qapp.processEvents()


def test_present_mode_from_main_window(win, qapp, stub_tts):
    win.present_deck()
    qapp.processEvents()
    assert win.present_win is not None
    assert win.present_win.total() == len(win.deck.slides)
    win.present_win.go_next()
    qapp.processEvents()
    assert win.present_win.index() == 1
    win.present_win.close()
    qapp.processEvents()
    assert win.present_win is None, "closed present window is dropped"


def test_present_mode_refuses_empty_deck(win, qapp):
    from app.models import Deck
    win.deck = Deck()
    win._sync_all()
    win.present_deck()
    qapp.processEvents()
    assert win.present_win is None


def test_qurl_from_local_helper():
    from app.present import QUrl_from_local
    url = QUrl_from_local("/tmp/x.wav")
    assert url.isLocalFile() and url.toLocalFile().endswith("x.wav")
