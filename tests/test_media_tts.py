"""Media tools (ffmpeg) + the three TTS engines, caches and voice catalogs."""
import os
import wave

import pytest

from app import media, tts
from app.models import Deck, Slide, VoiceSettings
from app.workspace import narr_cache_dir


# ------------------------------------------------------------------- media
def test_ffmpeg_detection():
    assert media.ffmpeg_path()
    ok, msg = media.is_available()
    assert ok and "ffmpeg" in msg.lower()


def test_run_reports_failure_with_stderr_tail():
    with pytest.raises(RuntimeError) as ei:
        media.run([media.ffmpeg_path(), "-hide_banner", "-i",
                   "/nonexistent/missing.mp4", "-f", "null", "-"])
    assert "failed" in str(ei.value).lower()


def test_run_supports_cancellation():
    with pytest.raises(media.CancelledError):
        media.run([media.ffmpeg_path(), "-hide_banner", "-f", "lavfi",
                   "-i", "sine=frequency=440:duration=5", "-f", "null", "-"],
                  cancel_check=lambda: True)


def test_media_duration_of_tone(tone_wav):
    d = media.media_duration(tone_wav)
    assert 0.3 < d < 0.6


def test_media_duration_of_garbage_is_zero(tmp_path):
    p = tmp_path / "not-audio.txt"
    p.write_text("hello", encoding="utf-8")
    assert media.media_duration(str(p)) == 0.0


# ---------------------------------------------------------------- catalogs
def test_engine_helpers():
    assert tts.engine_of("piper:x") == "piper"
    assert tts.engine_of("qwen:x") == "qwen"
    assert tts.engine_of("en-US-AriaNeural") == "edge"
    assert tts.engine_of(None) == "edge"
    assert tts.prefixed_voice("edge", "en-US-AriaNeural") == "en-US-AriaNeural"
    assert tts.prefixed_voice("piper", "en_US-amy-medium") == \
        "piper:en_US-amy-medium"
    assert tts.bare_voice_name("piper:a-b") == "a-b"
    assert tts.bare_voice_name("bare") == "bare"


def test_voice_catalogs():
    assert len(tts.voices_for_engine("piper")) == 16
    assert len(tts.voices_for_engine("qwen")) == 14
    edge = tts.voices_for_engine("edge")
    assert len(edge) >= 10
    for v in tts.PIPER_VOICES:
        assert v["ShortName"].startswith("piper:")
    for v in tts.QWEN_VOICES:
        assert v["ShortName"].startswith("qwen:")


def test_voice_list_falls_back_offline(fresh_narration_cache, monkeypatch):
    async def boom():
        raise OSError("offline")
    monkeypatch.setattr(tts, "_list_voices_async", boom)
    voices, online = tts._real_list_voices_sync(timeout=1.0)
    assert online is False and len(voices) >= 10


def test_voice_list_persists_cache(fresh_narration_cache, monkeypatch):
    async def fake():
        return [{"ShortName": "en-US-FakeNeural", "Locale": "en-US",
                 "Gender": "Female"}]
    monkeypatch.setattr(tts, "_list_voices_async", fake)
    voices, online = tts._real_list_voices_sync(timeout=1.0)
    assert online is True and voices[0]["ShortName"] == "en-US-FakeNeural"
    cached = tts._read_cache()
    assert cached and cached[0]["ShortName"] == "en-US-FakeNeural"


# ------------------------------------------------------- spoken text + cache
def test_spoken_text_applies_deck_cleaning(make_deck):
    d = make_deck(1)
    s = d.slides[0]
    s.narration = "See https://x.y now"
    d.tts_clean_urls = True
    assert "link" in tts.spoken_text(s, d)
    d.tts_clean_urls = False
    assert "https://x.y" in tts.spoken_text(s, d)


def test_cache_key_tracks_voice_text_and_cleaning(make_deck):
    d = make_deck(1)
    s = d.slides[0]
    k0 = tts.narration_cache_key(s, d)
    assert k0 == tts.narration_cache_key(s, d)          # stable
    s.narration = "different words"
    assert tts.narration_cache_key(s, d) != k0
    d.tts_clean_emoji = not d.tts_clean_emoji
    assert tts.narration_cache_key(s, d) != k0
    d.default_voice = VoiceSettings("piper:en_US-amy-medium")
    assert tts.narration_cache_key(s, d) != k0


def test_synthesize_empty_text_is_friendly_error(tmp_path):
    with pytest.raises(RuntimeError) as ei:
        tts.synthesize("   ", VoiceSettings(), str(tmp_path / "o.mp3"))
    assert "Nothing to speak" in str(ei.value)


def test_cache_roundtrip_offline(fresh_narration_cache, tone_wav,
                                 monkeypatch):
    d = Deck()
    s = d.new_slide(title="T", narration="cache me please")
    assert tts.cached_narration_path(s, d) is None
    # first synthesis goes through tts.synthesize -> stub it with the tone
    calls = []

    def fake_synth(text, vs, out_path, retries=2):
        calls.append(out_path)
        with open(out_path, "wb") as fh:
            fh.write(b"\x00" * 4096)

    monkeypatch.setattr(tts, "synthesize", fake_synth)
    path = tts.synthesize_cached(s, d)
    assert os.path.isfile(path) and path.endswith(".mp3")   # edge default
    assert len(calls) == 1
    # second call must hit the cache — no second synth call
    assert tts.cached_narration_path(s, d) == path
    assert tts.synthesize_cached(s, d) == path
    assert len(calls) == 1


def test_cache_respects_too_small_files(fresh_narration_cache):
    d = Deck()
    s = d.new_slide(title="T", narration="tiny cache entry")
    key = tts.narration_cache_key(s, d)
    tiny = os.path.join(narr_cache_dir(), f"{key}.mp3")
    with open(tiny, "wb") as fh:
        fh.write(b"\x00" * 10)
    assert tts.cached_narration_path(s, d) is None


# ------------------------------------------------------------------ piper
def test_piper_model_paths_and_status():
    onnx, js = tts.piper_model_paths("piper:en_US-lessac-medium")
    assert onnx.endswith("en_US-lessac-medium.onnx")
    assert js == onnx + ".json"
    assert tts.piper_voice_installed("piper:never-downloaded") is False
    assert tts.piper_model_size("piper:never-downloaded") == 0
    assert tts.piper_delete_voice("piper:never-downloaded") is False


def test_piper_install_cycle_with_fake_models(tmp_path):
    vid = "piper:en_GB-alba-medium"
    onnx, js = tts.piper_model_paths(vid)
    os.makedirs(os.path.dirname(onnx), exist_ok=True)
    try:
        with open(onnx, "wb") as fh:
            fh.write(b"\0" * 1_100_000)             # >1 MB sentinel
        with open(js, "w", encoding="utf-8") as fh:
            fh.write("{}")
        assert tts.piper_voice_installed(vid) is True
        assert tts.piper_model_size(vid) >= 1_000_000
        assert tts.piper_total_size() >= 1_000_000
        assert tts.piper_installed_count() >= 1
        assert tts.piper_delete_voice(vid) is True
        assert tts.piper_voice_installed(vid) is False
    finally:
        for f in (onnx, js):
            if os.path.isfile(f):
                os.remove(f)


@pytest.mark.slow
def test_piper_synthesis_offline():
    """Real ONNX synthesis with a sandbox-downloaded Piper voice."""
    pytest.importorskip("piper")
    vid = "piper:en_US-kathleen-low"
    if not tts.piper_voice_installed(vid):
        try:                                   # fetch once (~20 MB)
            tts.download_piper_voice(vid)
        except Exception as exc:
            pytest.skip(f"piper model unavailable: {exc}")
    out = os.path.join(narr_cache_dir(), "piper_pytest.wav")
    tts.synthesize("Piper local voices work completely offline.",
                   VoiceSettings(voice=vid, rate=-30, volume=10), out)
    assert os.path.getsize(out) > 10_000
    with wave.open(out, "rb") as wf:
        dur = wf.getnframes() / max(1, wf.getframerate())
    assert dur > 0.8
    # full dispatch through the cache
    d = Deck()
    d.default_voice = VoiceSettings(voice=vid)
    s = d.new_slide(title="P", narration="Cached piper dispatch.")
    path = tts.synthesize_cached(s, d)
    assert path.endswith(".wav") and os.path.getsize(path) > 10_000
    assert tts.synthesize_cached(s, d) == path, "second call hits the cache"


# ------------------------------------------------------------------- qwen
def test_qwen_api_key_and_region_settings():
    saved_key = tts.get_qwen_api_key()
    saved_region = tts.get_qwen_region()
    try:
        tts.set_qwen_api_key("sk-test-abc")
        assert tts.get_qwen_api_key() == "sk-test-abc"
        tts.set_qwen_api_key(None)
        assert tts.get_qwen_api_key() is None
        tts.set_qwen_region("china")
        assert tts.get_qwen_region() == "china"
    finally:
        tts.set_qwen_api_key(saved_key)
        tts.set_qwen_region(saved_region)


def test_qwen_without_key_friendly_error(tmp_path):
    saved = tts.get_qwen_api_key()
    try:
        tts.set_qwen_api_key(None)
        with pytest.raises(RuntimeError) as ei:
            tts.synthesize_qwen("Hello.", VoiceSettings("qwen:Cherry"),
                                str(tmp_path / "x.wav"))
        assert "DashScope" in str(ei.value) or "API key" in str(ei.value)
    finally:
        tts.set_qwen_api_key(saved)


def test_qwen_chunks_long_text_at_sentence_boundaries():
    long_text = "This is a spoken sentence for the test. " * 25
    chunks = tts._split_qwen_chunks(long_text)
    assert len(chunks) > 1
    assert all(len(c) <= tts.QWEN_MAX_CHARS for c in chunks)
    assert "".join(chunks).replace("\n", "").count("This is a spoken") == 25


def test_qwen_synthesis_with_mocked_http(tone_wav, tmp_path):
    fake = os.path.join(tone_wav)          # reuse tone as returned audio
    calls = {"n": 0}

    def fake_post(url, key, payload, timeout=120.0):
        calls["n"] += 1
        assert payload["model"] == "qwen3-tts-flash"
        assert payload["input"]["voice"] == "Cherry"
        assert len(payload["input"]["text"]) <= tts.QWEN_MAX_CHARS
        return {"output": {"audio": {"url": "file://" + fake}}}

    saved = tts.get_qwen_api_key()
    orig_post = tts._qwen_http_post
    try:
        tts.set_qwen_api_key("sk-test")
        tts._qwen_http_post = fake_post
        vs = VoiceSettings("qwen:Cherry")
        out1 = str(tmp_path / "q1.wav")
        tts.synthesize_qwen("Short text.", vs, out1)
        assert os.path.getsize(out1) > 200 and calls["n"] == 1
        long_text = "This is a spoken sentence for the test. " * 25
        n_chunks = len(tts._split_qwen_chunks(long_text))
        out2 = str(tmp_path / "q2.wav")
        tts.synthesize_qwen(long_text, vs, out2)
        assert calls["n"] == 1 + n_chunks
        with wave.open(out2, "rb") as wf:
            frames = wf.getnframes()
        assert frames > 0
        assert not [f for f in os.listdir(tmp_path) if ".part" in f]
    finally:
        tts._qwen_http_post = orig_post
        tts.set_qwen_api_key(saved)


def test_qwen_cached_dispatch_uses_wav(fresh_narration_cache, tone_wav):
    d = Deck()
    d.default_voice = VoiceSettings(voice="qwen:Cherry")
    s = d.new_slide(title="Q", narration="Qwen cached path.")
    key = tts.narration_cache_key(s, d)
    cached = os.path.join(narr_cache_dir(), key + ".wav")
    with open(cached, "wb") as fh:
        fh.write(b"\x00" * 2048)
    assert tts.cached_narration_path(s, d) == cached
    assert tts.synthesize_cached(s, d) == cached


# ------------------------------------------------------------------ online
@pytest.mark.online
def test_edge_online_voice_list_and_synthesis():
    orig = tts._real_list_voices_sync or tts.list_voices_sync
    voices, online = orig(timeout=20)
    assert len(voices) > 5, "edge-tts service must list voices when online"
    out = os.path.join(narr_cache_dir(), "pytest_online.mp3")
    tts.synthesize("This is a narration test.",
                   VoiceSettings("en-US-AriaNeural"), out)
    assert os.path.getsize(out) > 1000
    assert media.media_duration(out) > 0.5
