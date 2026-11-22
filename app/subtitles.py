"""SRT subtitle generation for exported slideshows.

Cues are derived from each slide's narration, split at sentence boundaries
and timed proportionally inside the slide's narration window. Slide start
offsets account for crossfade transitions (which shorten the timeline).
"""
from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")
MAX_CUE_CHARS = 160
MIN_CUE_CHARS = 24


def _split_cues(text: str) -> list[str]:
    """Split narration into readable cues (sentences, merged/split)."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_RE.split(text) if p.strip()]

    # merge tiny fragments into the previous cue
    merged: list[str] = []
    for p in parts:
        if merged and (len(p) < MIN_CUE_CHARS or len(merged[-1]) < MIN_CUE_CHARS):
            merged[-1] = (merged[-1] + " " + p).strip()
        else:
            merged.append(p)

    # split overly long cues on commas / spaces
    out: list[str] = []
    for cue in merged:
        while len(cue) > MAX_CUE_CHARS:
            cut = cue.rfind(",", 0, MAX_CUE_CHARS)
            if cut < MAX_CUE_CHARS // 2:
                cut = cue.rfind(" ", 0, MAX_CUE_CHARS)
            if cut <= 0:
                break
            out.append(cue[:cut].rstrip(",;:").strip())
            cue = cue[cut:].lstrip(",;: ").strip()
        if cue:
            out.append(cue)
    return out or ([text] if text else [])


def _fmt(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(slides, durs: list[float], starts: list[float],
              pad: float = 0.0) -> str:
    """Build a full SRT document.

    slides  -- deck slides (narration text is taken from effective_narration)
    durs    -- per-slide durations in the final timeline
    starts  -- per-slide start offsets in the final timeline
    pad     -- the silent pause appended to each slide (excluded from cues)
    """
    blocks: list[str] = []
    n = 0
    for slide, dur, start in zip(slides, durs, starts):
        text = slide.effective_narration()
        cues = _split_cues(text)
        if not cues:
            continue
        # cues live inside the narration window (slide duration minus pause)
        window = max(1.0, dur - pad)
        total_chars = sum(len(c) for c in cues) or 1
        t = start
        for cue in cues:
            share = len(cue) / total_chars
            cdur = max(0.7, window * share)
            cdur = min(cdur, max(0.7, start + window - t))
            if cdur <= 0.05:
                break
            n += 1
            blocks.append(f"{n}\n{_fmt(t)} --> {_fmt(t + cdur - 0.03)}\n{cue}")
            t += cdur
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def slide_starts(durs: list[float], transition_dur: float = 0.0) -> list[float]:
    """Start offset of each slide on the final timeline.

    Crossfade transitions overlap consecutive slides, so every slide after
    the first starts T seconds earlier per preceding transition.
    """
    starts: list[float] = []
    acc = 0.0
    for i, d in enumerate(durs):
        starts.append(acc)
        acc += d - (transition_dur if i < len(durs) - 1 and transition_dur > 0
                    else 0.0)
    return starts
