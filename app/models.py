"""Data model for Slideshow Studio.

A Deck contains Slides and a Theme plus narration defaults. Everything is a
plain dataclass so it serialises cleanly to JSON for the .slideshow project
format.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from .htmlfmt import looks_like_html


def _uid() -> str:
    return uuid.uuid4().hex[:10]


# Ken Burns motion presets applied during MP4 export.
MOTIONS = [
    "none",
    "Zoom in",
    "Zoom out",
    "Pan right",
    "Pan left",
    "Pan up",
    "Pan down",
    "Zoom in + pan right",
    "Zoom out + pan left",
]


@dataclass
class VoiceSettings:
    """edge-tts narration parameters for a single slide (or the deck default)."""

    voice: str = "en-US-AriaNeural"
    rate: int = 0        # percent, -50..+50  (spoken speed)
    volume: int = 0      # percent, -100..+50
    pitch: int = 0       # Hz, -50..+50

    def edge_args(self) -> dict:
        return {
            "rate": f"{self.rate:+d}%",
            "volume": f"{self.volume:+d}%",
            "pitch": f"{self.pitch:+d}Hz",
        }

    @property
    def engine(self) -> str:
        """TTS engine of this voice: "edge" | "piper" | "qwen".

        The engine is carried by the voice id prefix ("piper:…",
        "qwen:…"); bare ids are legacy Microsoft edge voices.
        """
        from .tts import engine_of
        return engine_of(self.voice)

    def to_dict(self) -> dict:
        return {"voice": self.voice, "rate": self.rate,
                "volume": self.volume, "pitch": self.pitch}

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceSettings":
        if not d:
            return cls()
        return cls(
            voice=str(d.get("voice", "en-US-AriaNeural")),
            rate=int(d.get("rate", 0)),
            volume=int(d.get("volume", 0)),
            pitch=int(d.get("pitch", 0)),
        )

    def clone(self) -> "VoiceSettings":
        return VoiceSettings(self.voice, self.rate, self.volume, self.pitch)


BODY_FORMATS = ("plain", "html")

# Canonical UI labels for the MP4 transitions (export_worker maps each
# label to an ffmpeg xfade filter; "None" = hard cut).  A slide may
# override the deck-wide transition with one of these names ("") means
# deck default).
TRANSITION_NAMES = ("None", "Crossfade", "Fade to black", "Dissolve",
                    "Wipe right", "Wipe left", "Slide up", "Slide down",
                    "Smooth left", "Circle open")


@dataclass
class Slide:
    title: str = ""
    body: str = ""
    # "plain" -- body is plain text (blank line = paragraph)
    # "html"  -- body is a sanitised HTML subset (see app/htmlfmt.py)
    body_format: str = "plain"
    narration: str = ""
    image: Optional[str] = None          # absolute path to a background image
    voice: Optional[VoiceSettings] = None  # None => use deck default
    duration_override: float = 0.0       # seconds; 0 => auto (audio length + pad)
    motion: str = "none"                 # Ken Burns preset (see MOTIONS)
    motion_intensity: float = 0.5        # 0..1, zoom/pan amplitude
    transition: str = ""                 # "" = deck default; else a key of
                                         # export_worker.TRANSITIONS (MP4 only)
    id: str = field(default_factory=_uid)

    # ------------------------------------------------------------------ #
    def body_is_html(self) -> bool:
        return self.body_format == "html"

    def body_plain(self) -> str:
        """Body as readable plain text (HTML stripped when needed)."""
        if self.body_format != "html" or not self.body:
            return self.body or ""
        from .htmlfmt import html_to_plain
        return html_to_plain(self.body)

    def effective_narration(self) -> str:
        """Text actually spoken: narration if set, otherwise title + body."""
        n = (self.narration or "").strip()
        if n:
            return n
        parts = []
        if self.title.strip():
            parts.append(self.title.strip())
        body = self.body_plain().strip()
        if body:
            parts.append(body)
        return ". ".join(parts)

    def has_voice_settings(self) -> bool:
        return self.voice is not None

    def effective_voice(self, deck: "Deck") -> VoiceSettings:
        return self.voice.clone() if self.voice else deck.default_voice.clone()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "body_format": self.body_format,
            "narration": self.narration,
            "image": self.image,
            "voice": self.voice.to_dict() if self.voice else None,
            "duration_override": self.duration_override,
            "motion": self.motion,
            "motion_intensity": round(float(self.motion_intensity), 3),
            "transition": self.transition or "",
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Slide":
        fmt = str(d.get("body_format", "plain"))
        if fmt not in BODY_FORMATS:
            fmt = "html" if looks_like_html(str(d.get("body", ""))) \
                else "plain"
        return cls(
            id=d.get("id") or _uid(),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            body_format=fmt,
            narration=str(d.get("narration", "")),
            image=d.get("image"),
            voice=VoiceSettings.from_dict(d["voice"]) if d.get("voice") else None,
            duration_override=float(d.get("duration_override", 0.0)),
            motion=d.get("motion") if d.get("motion") in MOTIONS else "none",
            motion_intensity=float(d.get("motion_intensity", 0.5)),
            transition=cls._valid_transition(d.get("transition", "")),
        )

    @staticmethod
    def _valid_transition(value) -> str:
        """Keep only known transition names (\"\" = deck default)."""
        v = str(value or "")
        return v if v in TRANSITION_NAMES else ""


@dataclass
class Theme:
    name: str = "Custom"
    # background
    background_mode: str = "gradient"    # solid | gradient
    bg_color: str = "#101418"
    bg_color2: str = "#1c2b3a"
    gradient_angle: int = 90             # degrees
    image_overlay: float = 0.55          # 0..0.9 dark overlay when slide has an image
    # typography
    title_font: str = "Segoe UI"
    title_size: int = 62                 # px in the 1600x900 design space
    title_color: str = "#ffffff"
    title_bold: bool = True
    body_font: str = "Segoe UI"
    body_size: int = 34
    body_color: str = "#e6edf3"
    # accents
    accent_color: str = "#4da3ff"
    show_accent_bar: bool = True
    align: str = "left"                  # left | center

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "Theme":
        t = cls()
        for k, v in (d or {}).items():
            if hasattr(t, k):
                setattr(t, k, v)
        return t


PRESET_THEMES: dict[str, Theme] = {
    "Midnight Blue": Theme(name="Midnight Blue"),
    "Corporate Light": Theme(
        name="Corporate Light", background_mode="solid", bg_color="#f5f7fa",
        bg_color2="#e8edf3", title_color="#17212b", body_color="#2c3a47",
        accent_color="#1667d9"),
    "Dark Pro": Theme(
        name="Dark Pro", background_mode="solid", bg_color="#0b0b0d",
        bg_color2="#141418", accent_color="#e05a4e", body_color="#d8d8dc"),
    "Warm Sunset": Theme(
        name="Warm Sunset", background_mode="gradient", bg_color="#2d1b2e",
        bg_color2="#7a3b2e", accent_color="#ffb86b"),
    "Forest Calm": Theme(
        name="Forest Calm", background_mode="gradient", bg_color="#0f1f18",
        bg_color2="#1d3b2a", accent_color="#6fd08c"),
    "Minimal White": Theme(
        name="Minimal White", background_mode="solid", bg_color="#ffffff",
        bg_color2="#ffffff", title_color="#111111", body_color="#333333",
        accent_color="#111111"),
}


@dataclass
class Deck:
    name: str = "Untitled Deck"
    theme: Theme = field(default_factory=Theme)
    default_voice: VoiceSettings = field(default_factory=VoiceSettings)
    slides: List[Slide] = field(default_factory=list)
    music_path: Optional[str] = None
    music_volume: float = 0.15           # 0..0.5
    project_path: Optional[str] = None   # set by the app when saved/loaded
    # TTS text cleaning (applied to the spoken text, never to stored text)
    tts_clean_emoji: bool = True
    tts_clean_markdown: bool = True
    tts_clean_urls: bool = True
    tts_clean_symbols: bool = True
    tts_clean_abbrev: bool = True
    # video overlays (rendered by the shared renderer: canvas, thumbs, MP4)
    overlay_slide_numbers: bool = False
    overlay_progress: bool = False
    watermark_text: str = ""

    # ------------------------------------------------------------------ #
    def new_slide(self, **kwargs) -> Slide:
        s = Slide(**kwargs)
        self.slides.append(s)
        return s

    def insert_slide(self, index: int, slide: Slide) -> None:
        self.slides.insert(max(0, min(index, len(self.slides))), slide)

    def remove_slide(self, index: int) -> Optional[Slide]:
        if 0 <= index < len(self.slides):
            return self.slides.pop(index)
        return None

    def duplicate_slide(self, index: int) -> Optional[Slide]:
        if not (0 <= index < len(self.slides)):
            return None
        src = self.slides[index]
        dup = Slide.from_dict(src.to_dict())
        dup.id = _uid()
        self.insert_slide(index + 1, dup)
        return dup

    def move_slide(self, from_idx: int, to_idx: int) -> bool:
        n = len(self.slides)
        if not (0 <= from_idx < n):
            return False
        to_idx = max(0, min(to_idx, n - 1))
        if from_idx == to_idx:
            return False
        s = self.slides.pop(from_idx)
        self.slides.insert(to_idx, s)
        return True

    # ------------------------------------------------------------------ #
    def sanitize_options(self) -> dict:
        """TTS text-cleaning options as a dict for app/tts_sanitize.py."""
        return {
            "emoji": self.tts_clean_emoji,
            "markdown": self.tts_clean_markdown,
            "urls": self.tts_clean_urls,
            "symbols": self.tts_clean_symbols,
            "abbrev": self.tts_clean_abbrev,
        }

    def to_dict(self) -> dict:
        return {
            "format": "slideshow-studio-deck",
            "version": 1,
            "name": self.name,
            "theme": self.theme.to_dict(),
            "default_voice": self.default_voice.to_dict(),
            "music_path": self.music_path,
            "music_volume": self.music_volume,
            "tts_clean": self.sanitize_options(),
            "overlays": {
                "slide_numbers": self.overlay_slide_numbers,
                "progress": self.overlay_progress,
                "watermark": self.watermark_text,
            },
            "slides": [s.to_dict() for s in self.slides],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Deck":
        deck = cls(
            name=str(d.get("name", "Untitled Deck")),
            theme=Theme.from_dict(d.get("theme", {})),
            default_voice=VoiceSettings.from_dict(d.get("default_voice", {})),
            music_path=d.get("music_path"),
            music_volume=float(d.get("music_volume", 0.15)),
        )
        clean = d.get("tts_clean") or {}
        deck.tts_clean_emoji = bool(clean.get("emoji", True))
        deck.tts_clean_markdown = bool(clean.get("markdown", True))
        deck.tts_clean_urls = bool(clean.get("urls", True))
        deck.tts_clean_symbols = bool(clean.get("symbols", True))
        deck.tts_clean_abbrev = bool(clean.get("abbrev", True))
        ov = d.get("overlays") or {}
        deck.overlay_slide_numbers = bool(ov.get("slide_numbers", False))
        deck.overlay_progress = bool(ov.get("progress", False))
        deck.watermark_text = str(ov.get("watermark", "") or "")
        deck.slides = [Slide.from_dict(s) for s in d.get("slides", [])]
        return deck
