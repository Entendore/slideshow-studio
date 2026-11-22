"""Named export presets: save a whole export-dialog configuration under a
memorable name and recall it with one click.

A preset bundles every export option the dialog exposes — format, video
resolution, audio codec, per-slide pause, transition + length, subtitle
save/burn/size, PDF notes pages, music mixing and the auto-open toggle —
so recurring jobs ("YouTube 1080p", "Podcast MP3", "PDF handout + notes")
become a single selection instead of a dozen clicks.

Presets live in QSettings as a JSON list and are seeded with a set of
factory presets on first use; after that they are fully editable (save
overwrites, Delete removes — factory copies included). The module is
widget-free so tests can exercise it with a sandboxed QSettings.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings

PRESETS_KEY = "exp/presets"          # JSON list of preset dicts
LAST_PRESET_KEY = "exp/preset"       # name of the last selected preset

MODES = ("mp4", "audio", "html", "pdf", "pptx")
AUDIO_FORMATS = ("mp3", "wav")
RESOLUTION_LABELS = ("SD 854×480", "HD 1280×720", "Full HD 1920×1080",
                     "QHD 2560×1440")
TRANSITION_LABELS = ("None", "Crossfade", "Fade to black", "Dissolve",
                     "Wipe right", "Wipe left", "Slide up", "Slide down",
                     "Smooth left", "Circle open")


class Preset:
    """One named export configuration (all fields have safe defaults)."""

    def __init__(self, name: str = "My preset", mode: str = "mp4",
                 resolution: str = "Full HD 1920×1080",
                 audio_format: str = "mp3", pad: float = 0.7,
                 transition: str = "None", transition_dur: float = 0.8,
                 save_srt: bool = False, burn_subtitles: bool = False,
                 subtitle_size: int = 16, notes: bool = False,
                 use_music: bool = True, duck_music: bool = True,
                 open_folder: bool = False):
        self.name = name
        self.mode = mode
        self.resolution = resolution
        self.audio_format = audio_format
        self.pad = pad
        self.transition = transition
        self.transition_dur = transition_dur
        self.save_srt = save_srt
        self.burn_subtitles = burn_subtitles
        self.subtitle_size = subtitle_size
        self.notes = notes
        self.use_music = use_music
        self.duck_music = duck_music
        self.open_folder = open_folder

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mode": self.mode,
            "resolution": self.resolution,
            "audio_format": self.audio_format,
            "pad": float(self.pad),
            "transition": self.transition,
            "transition_dur": float(self.transition_dur),
            "save_srt": bool(self.save_srt),
            "burn_subtitles": bool(self.burn_subtitles),
            "subtitle_size": int(self.subtitle_size),
            "notes": bool(self.notes),
            "use_music": bool(self.use_music),
            "duck_music": bool(self.duck_music),
            "open_folder": bool(self.open_folder),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Preset":
        """Build a preset from a dict, degrading bad values to defaults."""
        d = dict(data or {})

        def _num(key, default, cast=float, lo=None, hi=None):
            try:
                v = cast(d.get(key, default))
            except (TypeError, ValueError):
                return default
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v

        def _flag(key, default=False):
            v = d.get(key, default)
            if isinstance(v, bool):
                return v
            return str(v).lower() in ("true", "1", "yes", "on")

        mode = str(d.get("mode", "mp4"))
        if mode not in MODES:
            mode = "mp4"
        resolution = str(d.get("resolution", "Full HD 1920×1080"))
        if resolution not in RESOLUTION_LABELS:
            resolution = "Full HD 1920×1080"
        audio_format = str(d.get("audio_format", "mp3"))
        if audio_format not in AUDIO_FORMATS:
            audio_format = "mp3"
        transition = str(d.get("transition", "None"))
        if transition not in TRANSITION_LABELS:
            transition = "None"
        return cls(
            name=str(d.get("name", "My preset")),
            mode=mode,
            resolution=resolution,
            audio_format=audio_format,
            pad=_num("pad", 0.7, float, 0.0, 5.0),
            transition=transition,
            transition_dur=_num("transition_dur", 0.8, float, 0.2, 2.0),
            save_srt=_flag("save_srt"),
            burn_subtitles=_flag("burn_subtitles"),
            subtitle_size=_num("subtitle_size", 16, int, 8, 40),
            notes=_flag("notes"),
            use_music=_flag("use_music", True),
            duck_music=_flag("duck_music", True),
            open_folder=_flag("open_folder"),
        )

    # ------------------------------------------------------------------ #
    def describe(self) -> str:
        """One-line human summary for tooltips and status messages."""
        if self.mode == "mp4":
            bits = [f"MP4 · {self.resolution}"]
            if self.transition != "None":
                bits.append(f"{self.transition} {self.transition_dur:g}s")
            if self.save_srt:
                bits.append("srt")
            if self.burn_subtitles:
                bits.append(f"burned subs {self.subtitle_size}px")
        elif self.mode == "audio":
            bits = [f"{self.audio_format.upper()} audio"]
        elif self.mode == "pdf":
            bits = ["PDF handout" + (" + notes" if self.notes else "")]
        elif self.mode == "pptx":
            bits = ["PowerPoint"]
        else:
            bits = ["HTML page"]
        bits.append(f"pause {self.pad:g}s")
        return " · ".join(bits)


# ------------------------------------------------------------------ #
# factory presets (seeded once, editable afterwards)
# ------------------------------------------------------------------ #
def factory_presets() -> list[Preset]:
    """The built-in starter set — fresh objects on every call."""
    return [
        Preset("YouTube 1080p", mode="mp4", resolution="Full HD 1920×1080",
               save_srt=True, use_music=True),
        Preset("Quick preview 720p", mode="mp4", resolution="HD 1280×720",
               pad=0.3, use_music=False),
        Preset("Cinematic crossfade", mode="mp4",
               resolution="Full HD 1920×1080", transition="Crossfade",
               transition_dur=0.8, pad=0.5),
        Preset("Burned subtitles", mode="mp4",
               resolution="Full HD 1920×1080", save_srt=True,
               burn_subtitles=True, subtitle_size=18),
        Preset("Podcast MP3", mode="audio", audio_format="mp3", pad=0.6),
        Preset("Archive WAV", mode="audio", audio_format="wav", pad=0.6),
        Preset("Web page", mode="html"),
        Preset("PDF handout + notes", mode="pdf", notes=True),
        Preset("PowerPoint + notes", mode="pptx"),
    ]


# ------------------------------------------------------------------ #
# persistence
# ------------------------------------------------------------------ #
def load_presets(settings: QSettings) -> list[Preset]:
    """Read the stored preset list, seeding factory presets on first use.

    A missing key seeds (and persists) the factory set; a corrupted value
    is reset to the factory set as well, so a broken INI never breaks the
    export dialog.
    """
    raw = settings.value(PRESETS_KEY, "") or ""
    if not raw:
        presets = factory_presets()
        save_presets(settings, presets)
        return presets
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("presets must be a list")
        presets = [Preset.from_dict(d) for d in data if isinstance(d, dict)]
    except (ValueError, TypeError):
        presets = factory_presets()
        save_presets(settings, presets)
        return presets
    if not presets:
        presets = factory_presets()
        save_presets(settings, presets)
    return presets


def save_presets(settings: QSettings, presets: list[Preset]) -> None:
    """Persist the preset list (names + all option values)."""
    settings.setValue(PRESETS_KEY,
                      json.dumps([p.to_dict() for p in presets]))


def upsert(presets: list[Preset], preset: Preset) -> list[Preset]:
    """Insert or replace *preset* (matched by exact name); returns a new
    list so callers can reassign safely."""
    out = [p for p in presets if p.name != preset.name]
    out.append(preset)
    return out


def find(presets: list[Preset], name: str) -> Preset | None:
    for p in presets:
        if p.name == name:
            return p
    return None
