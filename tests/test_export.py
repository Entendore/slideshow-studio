"""Export pipelines: MP4 / MP3 / WAV via ExportWorker, plus HTML export.

All heavy ffmpeg runs are marked ``slow`` and use the offline TTS stub, so
the suite never touches the network.
"""
import os
import subprocess

import pytest

from app import html_export, media
from app.export_worker import RESOLUTIONS, TRANSITIONS, ExportOptions, \
    ExportWorker
from app.models import Deck


# ------------------------------------------------------------------ helpers
def _feature_deck(make_deck):
    d = make_deck(2, "Export deck")
    return d


def _run_worker(deck, opts, spin):
    result = {"ok": None, "err": None, "cancelled": False, "pct": -1}

    def on_ok(p):
        result["ok"] = p

    def on_err(m):
        result["err"] = m

    w = ExportWorker(deck, opts)
    w.progress.connect(lambda p, m: result.update(pct=p))
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


def _expect_export(deck, out_path, spin, **opt_kw):
    opts = ExportOptions(mode=opt_kw.pop("mode", "mp4"),
                         resolution=opt_kw.pop("resolution", "SD 854×480"),
                         pad=opt_kw.pop("pad", 0.3),
                         use_music=opt_kw.pop("use_music", False),
                         out_path=out_path, **opt_kw)
    result = _run_worker(deck, opts, spin)
    assert result["ok"] == out_path, result["err"] or "cancelled"
    assert os.path.isfile(out_path) and os.path.getsize(out_path) > 10000
    return result


def _probe_codecs(path):
    out = subprocess.run(
        [media.ffprobe_path(), "-v", "error", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=30)
    return sorted(set(out.stdout.strip().splitlines()))


# -------------------------------------------------------------- unit level
def test_resolution_and_transition_tables():
    assert "HD 1280×720" in RESOLUTIONS and RESOLUTIONS["HD 1280×720"] == \
        (1280, 720)
    assert TRANSITIONS["None"] is None
    assert TRANSITIONS["Crossfade"] == "fade"
    assert len(TRANSITIONS) >= 8


def test_worker_rejects_empty_deck(spin, tmp_path):
    opts = ExportOptions(out_path=str(tmp_path / "empty.mp4"))
    result = _run_worker(Deck(), opts, spin)
    assert result["err"] and "no slides" in result["err"].lower()


def test_worker_cancelled_before_start(spin, tmp_path, stub_tts, make_deck):
    deck = make_deck(2)
    opts = ExportOptions(mode="mp4", resolution="SD 854×480",
                         out_path=str(tmp_path / "c.mp4"))
    w = ExportWorker(deck, opts)
    result = {"cancelled": False, "err": None, "ok": None}
    w.cancelled.connect(lambda: result.update(cancelled=True))
    w.failed.connect(lambda m: result.update(err=m))
    w.finished_ok.connect(lambda p: result.update(ok=p))
    w.cancel()                       # flag set before the thread runs
    w.start()
    assert spin(lambda: result["cancelled"] or result["err"] or result["ok"],
                timeout_s=60)
    w.wait(10000)
    assert result["cancelled"] and not result["ok"]
    assert not os.path.isfile(str(tmp_path / "c.mp4"))


# -------------------------------------------------------------- slow: video
@pytest.mark.slow
def test_export_mp4_basic(stub_tts, make_deck, spin, tmp_path):
    out = str(tmp_path / "basic.mp4")
    _expect_export(_feature_deck(make_deck), out, spin)
    assert media.media_duration(out) > 1.0
    codecs = _probe_codecs(out)
    assert "h264" in codecs and "aac" in codecs


@pytest.mark.slow
def test_export_mp4_motion_transitions_subtitles(stub_tts, make_deck, spin,
                                                 tmp_path):
    deck = _feature_deck(make_deck)
    deck.slides[0].motion = "Zoom in"
    deck.slides[0].motion_intensity = 0.7
    deck.slides[1].motion = "Pan right"
    out = str(tmp_path / "feature.mp4")
    _expect_export(deck, out, spin, transition="Crossfade",
                   transition_dur=0.5, save_srt=True, burn_subtitles=True,
                   subtitle_size=14)
    assert media.media_duration(out) > 1.0
    codecs = _probe_codecs(out)
    assert "h264" in codecs and "aac" in codecs
    srt = os.path.splitext(out)[0] + ".srt"
    assert os.path.isfile(srt) and os.path.getsize(srt) > 50
    assert "Narration for slide 1" in open(srt, encoding="utf-8").read()


@pytest.mark.slow
def test_export_mp4_music_mix_ducked(stub_tts, make_deck, spin, tmp_path,
                                     tone_wav):
    deck = _feature_deck(make_deck)
    deck.music_path = tone_wav
    deck.music_volume = 0.3
    out = str(tmp_path / "music.mp4")
    _expect_export(deck, out, spin, use_music=True)
    assert media.media_duration(out) > 1.0


@pytest.mark.slow
def test_export_srt_sidecar_audio_only(stub_tts, make_deck, spin, tmp_path):
    out = str(tmp_path / "audio.mp3")
    _expect_export(_feature_deck(make_deck), out, spin, mode="audio",
                   save_srt=True)
    srt = os.path.splitext(out)[0] + ".srt"
    assert os.path.isfile(srt) and os.path.getsize(srt) > 50
    assert media.media_duration(out) > 1.0


@pytest.mark.slow
def test_export_wav_audio_format(stub_tts, make_deck, spin, tmp_path):
    out = str(tmp_path / "audio.wav")
    _expect_export(_feature_deck(make_deck), out, spin, mode="audio",
                   audio_format="wav")
    assert out.lower().endswith(".wav")
    assert media.media_duration(out) > 1.0


@pytest.mark.slow
def test_export_music_mix_audio_only(stub_tts, make_deck, spin, tmp_path,
                                     tone_wav):
    deck = _feature_deck(make_deck)
    deck.music_path = tone_wav
    out = str(tmp_path / "music.mp3")
    _expect_export(deck, out, spin, mode="audio", use_music=True)
    assert media.media_duration(out) > 1.0


# ------------------------------------------------------------ html export
def test_html_export_builds_standalone_document(make_deck, tmp_path,
                                                png_image):
    deck = _feature_deck(make_deck)
    deck.slides[0].image = png_image
    deck.name = "HTML Deck"
    doc = html_export.build_html(deck, embed_notes=True)
    assert doc.count("<section") == 2
    assert "HTML Deck" in doc
    assert "data:image/png;base64," in doc        # slide image embedded
    assert 'class="notes"' in doc                 # speaker notes included
    assert deck.theme.accent_color in doc
    # keyboard navigation + fullscreen + print hints shipped by the template
    for token in ("keydown", "fullscreen"):
        assert token in doc.lower()


def test_html_export_notes_can_be_omitted(make_deck, tmp_path):
    deck = _feature_deck(make_deck)
    doc = html_export.build_html(deck, embed_notes=False)
    assert 'class="notes"' not in doc


def test_html_export_writes_file(make_deck, tmp_path):
    deck = _feature_deck(make_deck)
    path = str(tmp_path / "out.html")
    assert html_export.export_html(deck, path) == path
    assert os.path.getsize(path) > 5000
    # extension added automatically when missing
    path2 = html_export.export_html(deck, str(tmp_path / "noext"))
    assert path2.endswith(".html") and os.path.isfile(path2)


def test_html_export_sanitizes_slide_bodies():
    deck = Deck()
    deck.new_slide(title="X",
                   body="<p onclick='evil()'>safe <script>bad()</script></p>",
                   body_format="html")
    doc = html_export.build_html(deck)
    assert "onclick" not in doc and "bad()" not in doc
    assert "safe" in doc
