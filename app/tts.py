"""Multi-engine TTS: edge-tts (online), Piper (local) and Qwen TTS (API),
plus cached narration synthesis.

Every narration is run through app/tts_sanitize.py *before* synthesis; the
cleaned text (and the cleaning options) is part of the cache key, so the
original stored text is never modified.

Engines
    edge   Microsoft neural voices via edge-tts (online, free).
           Supports rate / volume / pitch. Output: .mp3
    piper  Rhasspy Piper ONNX voices, fully local/offline. Voice models
           (~60 MB) download on first use into the app workspace.
           Supports rate (length_scale) and volume; pitch not available.
           Output: .wav
    qwen   Alibaba Qwen3-TTS via the DashScope REST API. Requires the user's
           API key (stored in app settings or DASHSCOPE_API_KEY env var).
           Text is chunked at sentence boundaries (600-char API limit) and
           merged with ffmpeg. Rate/volume/pitch are not applied.
           Output: .wav

All functions are *blocking* and meant to be called from worker threads.
Voice ids carry their engine as a prefix ("piper:…", "qwen:…"); bare ids
are legacy edge voices.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
import urllib.request
import wave

from .models import Deck, Slide
from .tts_sanitize import sanitize_for_tts
from .workspace import narr_cache_dir, piper_dir

VOICES_CACHE = "voices_cache.json"
VOICES_CACHE_TTL = 7 * 24 * 3600  # one week

ENGINES = ("edge", "piper", "qwen")
ENGINE_LABELS = {
    "edge": "Microsoft Edge voices (online, free)",
    "piper": "Piper voices (local, offline)",
    "qwen": "Qwen TTS (DashScope API key)",
}
ENGINE_SHORT = {"edge": "Microsoft Edge (online)",
                "piper": "Piper (local, offline)",
                "qwen": "Qwen TTS (DashScope)"}

FALLBACK_VOICES: list[dict] = [
    {"ShortName": "en-US-AriaNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "en-US-GuyNeural", "Locale": "en-US", "Gender": "Male"},
    {"ShortName": "en-US-JennyNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "en-US-AnaNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "en-US-ChristopherNeural", "Locale": "en-US", "Gender": "Male"},
    {"ShortName": "en-US-EricNeural", "Locale": "en-US", "Gender": "Male"},
    {"ShortName": "en-GB-SoniaNeural", "Locale": "en-GB", "Gender": "Female"},
    {"ShortName": "en-GB-RyanNeural", "Locale": "en-GB", "Gender": "Male"},
    {"ShortName": "en-GB-LibbyNeural", "Locale": "en-GB", "Gender": "Female"},
    {"ShortName": "en-AU-NatashaNeural", "Locale": "en-AU", "Gender": "Female"},
    {"ShortName": "en-AU-WilliamNeural", "Locale": "en-AU", "Gender": "Male"},
    {"ShortName": "en-IN-NeerjaNeural", "Locale": "en-IN", "Gender": "Female"},
    {"ShortName": "zh-CN-XiaoxiaoNeural", "Locale": "zh-CN", "Gender": "Female"},
    {"ShortName": "zh-CN-YunxiNeural", "Locale": "zh-CN", "Gender": "Male"},
    {"ShortName": "zh-CN-YunyangNeural", "Locale": "zh-CN", "Gender": "Male"},
    {"ShortName": "zh-TW-HsiaoChenNeural", "Locale": "zh-TW", "Gender": "Female"},
    {"ShortName": "de-DE-KatjaNeural", "Locale": "de-DE", "Gender": "Female"},
    {"ShortName": "de-DE-ConradNeural", "Locale": "de-DE", "Gender": "Male"},
    {"ShortName": "fr-FR-DeniseNeural", "Locale": "fr-FR", "Gender": "Female"},
    {"ShortName": "es-ES-ElviraNeural", "Locale": "es-ES", "Gender": "Female"},
    {"ShortName": "it-IT-ElsaNeural", "Locale": "it-IT", "Gender": "Female"},
    {"ShortName": "pt-BR-FranciscaNeural", "Locale": "pt-BR", "Gender": "Female"},
    {"ShortName": "ja-JP-NanamiNeural", "Locale": "ja-JP", "Gender": "Female"},
    {"ShortName": "ko-KR-SunHiNeural", "Locale": "ko-KR", "Gender": "Female"},
    {"ShortName": "ru-RU-SvetlanaNeural", "Locale": "ru-RU", "Gender": "Female"},
    {"ShortName": "ar-EG-SalmaNeural", "Locale": "ar-EG", "Gender": "Female"},
    {"ShortName": "hi-IN-SwaraNeural", "Locale": "hi-IN", "Gender": "Female"},
]


# --------------------------------------------------------------------- #
# engine helpers
# --------------------------------------------------------------------- #
def engine_of(voice: str) -> str:
    """Derive the engine from a voice id ("piper:x", "qwen:x", else edge)."""
    v = voice or ""
    if v.startswith("piper:"):
        return "piper"
    if v.startswith("qwen:"):
        return "qwen"
    return "edge"


def prefixed_voice(engine: str, name: str) -> str:
    if engine == "edge":
        return name
    return f"{engine}:{name}"


def bare_voice_name(voice: str) -> str:
    return voice.split(":", 1)[1] if ":" in (voice or "") else (voice or "")


# --------------------------------------------------------------------- #
# voice catalogs (piper / qwen)
# --------------------------------------------------------------------- #
_PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

# (locale, name, quality, gender) -- all URLs verified reachable
_PIPER_CATALOG = [
    ("en_US", "lessac", "medium", "Female"),
    ("en_US", "amy", "medium", "Female"),
    ("en_US", "arctic", "medium", "Male"),
    ("en_US", "hfc_female", "medium", "Female"),
    ("en_US", "hfc_male", "medium", "Male"),
    ("en_US", "ryan", "high", "Male"),
    ("en_US", "kathleen", "low", "Female"),
    ("en_US", "ljspeech", "high", "Female"),
    ("en_GB", "alba", "medium", "Female"),
    ("en_GB", "northern_english_male", "medium", "Male"),
    ("de_DE", "thorsten", "medium", "Male"),
    ("fr_FR", "siwis", "medium", "Female"),
    ("es_ES", "sharvard", "medium", "Female"),
    ("it_IT", "riccardo", "x_low", "Male"),
    ("zh_CN", "huayan", "medium", "Female"),
    ("ru_RU", "dmitri", "medium", "Male"),
]


def _piper_path(locale: str, name: str, quality: str) -> str:
    lang = locale.split("_")[0]
    return f"{lang}/{locale}/{name}/{quality}/{locale}-{name}-{quality}"


PIPER_VOICES: list[dict] = [
    {"ShortName": f"piper:{locale}-{name}-{quality}",
     "Locale": locale, "Gender": gender, "Quality": quality}
    for locale, name, quality, gender in _PIPER_CATALOG
]

QWEN_VOICES: list[dict] = [
    {"ShortName": "qwen:Cherry", "Locale": "multi", "Gender": "Female",
     "Note": "Sunny, friendly young woman"},
    {"ShortName": "qwen:Serena", "Locale": "multi", "Gender": "Female",
     "Note": "Gentle young woman"},
    {"ShortName": "qwen:Ethan", "Locale": "multi", "Gender": "Male",
     "Note": "Warm, energetic"},
    {"ShortName": "qwen:Chelsie", "Locale": "multi", "Gender": "Female",
     "Note": "Virtual-girlfriend style"},
    {"ShortName": "qwen:Vivian", "Locale": "multi", "Gender": "Female",
     "Note": "Confident and cute"},
    {"ShortName": "qwen:Moon", "Locale": "multi", "Gender": "Male",
     "Note": "Bold and handsome"},
    {"ShortName": "qwen:Maia", "Locale": "multi", "Gender": "Female",
     "Note": "Intellect and gentleness"},
    {"ShortName": "qwen:Kai", "Locale": "multi", "Gender": "Male",
     "Note": "Soothing, calm"},
    {"ShortName": "qwen:Nofish", "Locale": "multi", "Gender": "Male",
     "Note": "Casual designer voice"},
    {"ShortName": "qwen:Jennifer", "Locale": "multi", "Gender": "Female",
     "Note": "Cinematic American English"},
    {"ShortName": "qwen:Ryan", "Locale": "multi", "Gender": "Male",
     "Note": "Dramatic, rhythmic"},
    {"ShortName": "qwen:Katerina", "Locale": "multi", "Gender": "Female",
     "Note": "Mature, rich rhythm"},
    {"ShortName": "qwen:Elias", "Locale": "multi", "Gender": "Female",
     "Note": "Storytelling teacher"},
    {"ShortName": "qwen:Neil", "Locale": "multi", "Gender": "Male",
     "Note": "News-anchor delivery"},
]


def voices_for_engine(engine: str, edge_voices: list[dict] | None = None
                      ) -> list[dict]:
    """Voice dicts (ShortName/Locale/Gender) for one engine."""
    if engine == "piper":
        return [dict(v) for v in PIPER_VOICES]
    if engine == "qwen":
        return [dict(v) for v in QWEN_VOICES]
    return [dict(v) for v in (edge_voices or FALLBACK_VOICES)]


# --------------------------------------------------------------------- #
# edge voice list cache (online)
# --------------------------------------------------------------------- #
def _cache_path() -> str:
    return os.path.join(narr_cache_dir(), VOICES_CACHE)


def _read_cache() -> list[dict] | None:
    try:
        if time.time() - os.path.getmtime(_cache_path()) < VOICES_CACHE_TTL:
            with open(_cache_path(), "r", encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    return None


def _write_cache(voices: list[dict]) -> None:
    try:
        with open(_cache_path(), "w", encoding="utf-8") as fh:
            json.dump(voices, fh)
    except OSError:
        pass


def list_voices_sync(timeout: float = 12.0) -> tuple[list[dict], bool]:
    """(edge voices, online). Blocks; call from a worker thread."""
    cached = _read_cache()
    try:
        voices = asyncio.run(asyncio.wait_for(_list_voices_async(),
                                              timeout=timeout))
        if voices:
            _write_cache(voices)
            return voices, True
    except Exception:
        pass
    if cached:
        return cached, False
    return FALLBACK_VOICES, False


async def _list_voices_async() -> list[dict]:
    import edge_tts
    raw = await edge_tts.list_voices()
    out = []
    for v in raw:
        out.append({
            "ShortName": v.get("ShortName", ""),
            "Locale": v.get("Locale", ""),
            "Gender": v.get("Gender", ""),
        })
    return out


# --------------------------------------------------------------------- #
# piper engine
# --------------------------------------------------------------------- #
_PIPER_VOICE_CACHE: dict[str, "object"] = {}


def piper_model_paths(voice_id: str) -> tuple[str, str]:
    """(onnx_path, json_path) for a piper voice id in the workspace."""
    name = bare_voice_name(voice_id)          # en_US-lessac-medium
    onnx = os.path.join(piper_dir(), name + ".onnx")
    return onnx, onnx + ".json"


def piper_voice_installed(voice_id: str) -> bool:
    onnx, js = piper_model_paths(voice_id)
    return os.path.isfile(onnx) and os.path.isfile(js) \
        and os.path.getsize(onnx) > 1_000_000


def piper_installed_count() -> int:
    return sum(1 for v in PIPER_VOICES if piper_voice_installed(v["ShortName"]))


def piper_model_size(voice_id: str) -> int:
    """Total bytes on disk for an installed model (0 when not installed)."""
    onnx, js = piper_model_paths(voice_id)
    total = 0
    for p in (onnx, js):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def piper_total_size() -> int:
    """Bytes used by every downloaded Piper model in the workspace."""
    total = 0
    try:
        for fn in os.listdir(piper_dir()):
            try:
                total += os.path.getsize(os.path.join(piper_dir(), fn))
            except OSError:
                pass
    except OSError:
        pass
    return total


def piper_delete_voice(voice_id: str) -> bool:
    """Delete a downloaded Piper model (onnx + json); returns success."""
    onnx, js = piper_model_paths(voice_id)
    removed = False
    for p in (onnx, js):
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed = True
        except OSError:
            pass
    _PIPER_VOICE_CACHE.pop(onnx, None)      # drop any loaded instance
    return removed


def edge_cache_info() -> tuple[int, float]:
    """(voice count, cache age in seconds; -1 when there is no cache)."""
    cached = _read_cache()
    try:
        age = time.time() - os.path.getmtime(_cache_path())
    except OSError:
        return (len(cached) if cached else 0), -1.0
    return (len(cached) if cached else 0), age


def edge_cache_clear() -> None:
    """Drop the cached edge voice list so the next fetch is fresh."""
    try:
        os.remove(_cache_path())
    except OSError:
        pass


def _download(url: str, dest: str, timeout: float = 900.0,
              progress=None) -> None:
    """Download *url* to *dest* atomically; progress(done, total) is called
    with byte counts (total may be -1 when the server omits it)."""
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, \
            open(tmp, "wb") as fh:
        try:
            total = int(resp.headers.get("Content-Length", -1))
        except (TypeError, ValueError):
            total = -1
        done = 0
        while True:
            block = resp.read(1 << 16)
            if not block:
                break
            fh.write(block)
            done += len(block)
            if progress:
                progress(done, total)
    os.replace(tmp, dest)


def download_piper_voice(voice_id: str, progress=None) -> str:
    """Download a piper voice model; returns the onnx path.

    progress(done_bytes, total_bytes) is reported while the model body
    downloads. Raises RuntimeError with a friendly message on failure.
    """
    name = bare_voice_name(voice_id)          # en_US-lessac-medium
    # locale-quality name -> HF sub path via the catalog
    entry = next((v for v in PIPER_VOICES if v["ShortName"] == voice_id), None)
    if entry is None:
        raise RuntimeError(f"Unknown Piper voice: {name}")
    rel = _piper_path(entry["Locale"], name.rsplit("-", 2)[-2],
                      entry["Quality"])
    onnx, js = piper_model_paths(voice_id)
    try:
        if not (os.path.isfile(js) and os.path.getsize(js) > 256):
            _download(f"{_PIPER_HF}/{rel}.onnx.json", js, timeout=120)
        if not (os.path.isfile(onnx)
                and os.path.getsize(onnx) > 1_000_000):
            _download(f"{_PIPER_HF}/{rel}.onnx", onnx, timeout=900,
                      progress=progress)
        elif progress:
            progress(1, 1)
    except Exception as exc:
        raise RuntimeError(
            f"Could not download the Piper voice '{name}' ({exc}).\n"
            "Check your internet connection — voice models come from "
            "huggingface.co.")
    return onnx


def _load_piper(onnx_path: str):
    try:
        from piper import PiperVoice
    except ImportError:
        raise RuntimeError(
            "The Piper engine is not installed.\n"
            "Install it with:  pip install piper-tts")
    voice = _PIPER_VOICE_CACHE.get(onnx_path)
    if voice is None:
        voice = PiperVoice.load(onnx_path)
        _PIPER_VOICE_CACHE[onnx_path] = voice
    return voice


def synthesize_piper(text: str, voice_settings, out_path: str) -> None:
    voice_id = voice_settings.voice
    if not piper_voice_installed(voice_id):
        download_piper_voice(voice_id)
    onnx, _js = piper_model_paths(voice_id)
    pv = _load_piper(onnx)
    rate = getattr(voice_settings, "rate", 0) or 0
    volume = getattr(voice_settings, "volume", 0) or 0
    length_scale = max(0.4, min(2.5, 1.0 / (1.0 + rate / 100.0)))
    gain = max(0.1, min(2.0, 1.0 + volume / 100.0))
    from piper import SynthesisConfig
    cfg = SynthesisConfig(length_scale=length_scale, volume=gain)
    tmp = out_path + ".part.wav"
    with wave.open(tmp, "wb") as wf:
        pv.synthesize_wav(text, wf, syn_config=cfg)
    os.replace(tmp, out_path)


# --------------------------------------------------------------------- #
# qwen engine (DashScope REST)
# --------------------------------------------------------------------- #
_QWEN_KEY: str | None = None
_QWEN_REGION: str = "international"

QWEN_ENDPOINTS = {
    "international":
        "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation",
    "china":
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation",
}
QWEN_MODEL = "qwen3-tts-flash"
QWEN_MAX_CHARS = 550          # API limit 600 — stay under with margin


def set_qwen_api_key(key: str | None) -> None:
    global _QWEN_KEY
    _QWEN_KEY = (key or "").strip() or None


def set_qwen_region(region: str) -> None:
    global _QWEN_REGION
    _QWEN_REGION = "china" if str(region).lower().startswith("china") \
        else "international"


def get_qwen_api_key() -> str | None:
    if _QWEN_KEY:
        return _QWEN_KEY
    return (os.environ.get("DASHSCOPE_API_KEY") or "").strip() or None


def get_qwen_region() -> str:
    return _QWEN_REGION


def _qwen_http_post(url: str, key: str, payload: dict,
                    timeout: float = 120.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "SlideshowStudio/1.4"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_qwen_chunks(text: str, limit: int = QWEN_MAX_CHARS
                       ) -> list[str]:
    """Split at sentence boundaries so every chunk fits the API limit."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        while len(s) > limit:                 # pathological single sentence
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > limit * 0.5 else limit
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        if cur and len(cur) + 1 + len(s) > limit:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if c]


def _qwen_fetch_audio(url: str, dest: str, timeout: float = 180.0) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "SlideshowStudio"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, \
            open(dest + ".part", "wb") as fh:
        while True:
            block = resp.read(1 << 16)
            if not block:
                break
            fh.write(block)
    os.replace(dest + ".part", dest)


def synthesize_qwen(text: str, voice_settings, out_path: str) -> None:
    key = get_qwen_api_key()
    if not key:
        raise RuntimeError(
            "Qwen TTS needs a DashScope API key.\n"
            "Enter it under Deck & Theme ▸ Narration engine, or set the "
            "DASHSCOPE_API_KEY environment variable.")
    voice = bare_voice_name(voice_settings.voice)
    chunks = _split_qwen_chunks(text)
    if not chunks:
        raise RuntimeError("Nothing to speak for this slide.")
    try:
        parts: list[str] = []
        for i, chunk in enumerate(chunks):
            data = _qwen_http_post(
                QWEN_ENDPOINTS.get(_QWEN_REGION,
                                   QWEN_ENDPOINTS["international"]),
                key,
                {"model": QWEN_MODEL,
                 "input": {"text": chunk, "voice": voice}})
            audio = (data.get("output") or {}).get("audio") or {}
            url = audio.get("url") or ""
            b64 = audio.get("data") or ""
            part = f"{out_path}.part{i}"
            if b64:
                with open(part, "wb") as fh:
                    fh.write(base64.b64decode(b64))
            elif url:
                _qwen_fetch_audio(url, part)
            else:
                raise RuntimeError("the API returned no audio data")
            parts.append(part)
        if len(parts) == 1:
            os.replace(parts[0], out_path)
        else:
            _concat_wav(parts, out_path)
    except RuntimeError:
        raise
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg or "InvalidApiKey" in msg:
            raise RuntimeError(
                "Qwen TTS rejected the DashScope API key (401). Check the "
                "key under Deck & Theme ▸ Narration engine.")
        if "Throttling" in msg or "429" in msg:
            raise RuntimeError("Qwen TTS rate limit reached (429) — "
                               "retry in a moment.")
        raise RuntimeError(
            f"Qwen TTS failed ({exc.__class__.__name__}: {exc}).\n"
            "Check the API key and your internet connection.")
    finally:
        for i in range(len(chunks)):
            p = f"{out_path}.part{i}"
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def _concat_wav(parts: list[str], out_path: str) -> None:
    """Concatenate same-format WAV parts (raw data append)."""
    import shutil
    first = parts[0]
    with wave.open(first, "rb") as wf:
        params = wf.getparams()
    with wave.open(out_path + ".part.wav", "wb") as out:
        out.setparams(params)
        for p in parts:
            with wave.open(p, "rb") as wf:
                if (wf.getframerate() != params.framerate
                        or wf.getnchannels() != params.nchannels
                        or wf.getsampwidth() != params.sampwidth):
                    raise RuntimeError(
                        "Qwen returned mismatched audio segments — "
                        "install ffmpeg and retry the export.")
                out.writeframes(wf.readframes(wf.getnframes()))
    os.replace(out_path + ".part.wav", out_path)
    _ = shutil


# --------------------------------------------------------------------- #
# synthesis + cache (engine dispatch)
# --------------------------------------------------------------------- #
def spoken_text(slide: Slide, deck: Deck) -> str:
    """The narration text actually sent to the engine (after cleaning)."""
    return sanitize_for_tts(slide.effective_narration(),
                            deck.sanitize_options())


def narration_cache_key(slide: Slide, deck: Deck) -> str:
    vs = slide.effective_voice(deck)
    text = spoken_text(slide, deck)
    opts = json.dumps(deck.sanitize_options(), sort_keys=True)
    payload = (f"{vs.engine}|{vs.voice}|{vs.rate}|{vs.volume}|{vs.pitch}"
               f"|{opts}|{text}")
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cache_ext(engine: str) -> str:
    return "wav" if engine in ("piper", "qwen") else "mp3"


def cached_narration_path(slide: Slide, deck: Deck) -> str | None:
    engine = slide.effective_voice(deck).engine
    key = narration_cache_key(slide, deck)
    path = os.path.join(narr_cache_dir(), f"{key}.{_cache_ext(engine)}")
    return path if os.path.isfile(path) and os.path.getsize(path) > 512 else None


def synthesize_cached(slide: Slide, deck: Deck) -> str:
    """Synthesize slide narration into the cache dir; returns the path.

    Raises RuntimeError with a user-friendly message on failure.
    """
    cached = cached_narration_path(slide, deck)
    if cached:
        return cached
    vs = slide.effective_voice(deck)
    key = narration_cache_key(slide, deck)
    path = os.path.join(narr_cache_dir(), f"{key}.{_cache_ext(vs.engine)}")
    synthesize(spoken_text(slide, deck), vs, path)
    return path


def synthesize(text: str, voice_settings, out_path: str,
               retries: int = 2) -> None:
    """Blocking single synthesis of already-cleaned *text*.

    Transient network failures are retried with a growing delay; only the
    final failure is raised.
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("Nothing to speak for this slide.")
    engine = getattr(voice_settings, "engine", engine_of(voice_settings.voice))

    if engine == "piper":
        synthesize_piper(text, voice_settings, out_path)
        if not os.path.isfile(out_path) or os.path.getsize(out_path) < 256:
            raise RuntimeError("Piper returned no audio for this slide.")
        return

    if engine == "qwen":
        synthesize_qwen(text, voice_settings, out_path)
        if not os.path.isfile(out_path) or os.path.getsize(out_path) < 256:
            raise RuntimeError("Qwen TTS returned no audio for this slide.")
        return

    # ---- edge (default) ----------------------------------------------
    import edge_tts
    args = voice_settings.edge_args()

    async def _run():
        com = edge_tts.Communicate(text, voice_settings.voice, **args)
        await com.save(out_path)

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            asyncio.run(_run())
            last_exc = None
            break
        except Exception as exc:  # transient network/service errors
            last_exc = exc
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    if last_exc is not None:
        raise RuntimeError(
            f"Text-to-speech failed ({last_exc.__class__.__name__}: "
            f"{last_exc}).\n"
            "Check your internet connection — edge-tts needs access to "
            "Microsoft's speech service.")
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 256:
        raise RuntimeError("Text-to-speech returned no audio. Check the "
                           "voice name and your internet connection.")
