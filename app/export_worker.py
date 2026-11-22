"""Export pipelines run inside a QThread.

MP4 mode:  render slides -> TTS per slide -> per-slide video segments
           (still image + narration, padded, optional Ken Burns motion) ->
           concat (optionally with crossfade transitions) -> optional
           subtitle burn-in + music mix.
Audio mode: TTS per slide -> WAV segments padded to slide durations ->
           concat -> optional music mix -> encode MP3 or keep WAV.
Document modes: PDF handout (one page per slide, optional notes pages)
           and PowerPoint (.pptx with narration in the speaker notes) —
           both rendered by app/document_export.py, no ffmpeg needed.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess

from PySide6.QtCore import QThread, Signal

from . import folders, media, subtitles, tts
from .models import TRANSITION_NAMES, Deck, Slide
from .render import overlay_info, render_slide

RESOLUTIONS = {
    "SD 854×480": (854, 480),
    "HD 1280×720": (1280, 720),
    "Full HD 1920×1080": (1920, 1080),
    "QHD 2560×1440": (2560, 1440),
}

# formats that need ffmpeg on the system (documents render internally)
FFMPEG_MODES = ("mp4", "audio")

# UI label -> ffmpeg xfade transition name (labels are canonical in
# models.TRANSITION_NAMES; "None" means a hard cut between segments)
_XFADE = {
    "Crossfade": "fade",
    "Fade to black": "fadeblack",
    "Dissolve": "dissolve",
    "Wipe right": "wiperight",
    "Wipe left": "wipeleft",
    "Slide up": "slideup",
    "Slide down": "slidedown",
    "Smooth left": "smoothleft",
    "Circle open": "circleopen",
}
TRANSITIONS = {name: _XFADE.get(name) for name in TRANSITION_NAMES}


def transition_graph(durs, names, t, fps=None):
    """Build an ffmpeg ``-filter_complex`` graph joining n segments.

    ``names[k-1]`` describes the join between segment ``k-1`` and ``k``:
    a truthy value is an xfade transition name, ``None`` a hard cut
    (plain concat).  Returns ``(graph, final_v, final_a)`` where the
    finals are the mapped output labels.  Pure function — unit-tested
    without ffmpeg.

    When the graph mixes cuts with fades (``fps`` given), every xfade
    operand is normalised to a common time base + frame rate first —
    concat output would otherwise be rejected by xfade ("could not open
    encoder").  All-xfade graphs (the default) stay un-normalised.
    """
    n = len(durs)
    if n < 2:
        return "", "0:v", "0:a"
    mixed = fps is not None and any(n_ is None for n_ in names[:n - 1])
    vparts, aparts = [], []
    prev_v, prev_a = "0:v", "0:a"
    v_normed = False           # does prev_v already match AVTB/fps?
    pos = float(durs[0])       # output length after the last join
    for k in range(1, n):
        out_v, out_a = f"v{k}", f"a{k}"
        name = names[k - 1] if k - 1 < len(names) else None
        if name:
            if mixed:
                # normalise both operands so xfade accepts them
                if not v_normed:
                    vparts.append(f"[{prev_v}]settb=AVTB,fps={fps}"
                                  f"[vn{k}a]")
                    prev_v, v_normed = f"vn{k}a", True
                vparts.append(f"[{k}:v]settb=AVTB,fps={fps}[vn{k}b]")
                src_b = f"vn{k}b"
            else:
                src_b = f"{k}:v"
            offset = max(0.0, pos - t)
            vparts.append(
                f"[{prev_v}][{src_b}]xfade=transition={name}"
                f":duration={t:.3f}:offset={offset:.3f}[{out_v}]")
            aparts.append(f"[{prev_a}][{k}:a]acrossfade=d={t:.3f}[{out_a}]")
            pos = offset + float(durs[k])
        else:
            vparts.append(
                f"[{prev_v}][{k}:v]concat=n=2:v=1:a=0[{out_v}]")
            aparts.append(f"[{prev_a}][{k}:a]concat=n=2:v=0:a=1[{out_a}]")
            pos += float(durs[k])
            v_normed = False   # concat output needs normalising again
        prev_v, prev_a = out_v, out_a
    return ";".join(vparts + aparts), prev_v, prev_a


class ExportOptions:
    def __init__(self, mode: str = "mp4", resolution: str = "Full HD 1920×1080",
                 pad: float = 0.7, fps: int = 30,
                 use_music: bool = True, duck_music: bool = True,
                 audio_format: str = "mp3", out_path: str = "",
                 transition: str = "None", transition_dur: float = 0.8,
                 save_srt: bool = False, burn_subtitles: bool = False,
                 subtitle_size: int = 16, notes: bool = False):
        self.mode = mode                # mp4 | audio | html | pdf | pptx
        self.resolution = resolution
        self.pad = pad
        self.fps = fps
        self.use_music = use_music
        self.duck_music = duck_music
        self.audio_format = audio_format  # mp3 | wav (audio mode only)
        self.out_path = out_path
        self.transition = transition        # key of TRANSITIONS
        self.transition_dur = transition_dur
        self.save_srt = save_srt
        self.burn_subtitles = burn_subtitles
        self.subtitle_size = subtitle_size
        self.notes = notes              # PDF handout: interleave notes pages


class ExportWorker(QThread):
    progress = Signal(int, str)          # percent 0..100, status text
    finished_ok = Signal(str)            # output path
    failed = Signal(str)                 # error message
    cancelled = Signal()

    def __init__(self, deck: Deck, options: ExportOptions, parent=None):
        super().__init__(parent)
        self.deck = deck
        self.opts = options
        self._cancel = False
        self._procs: list[subprocess.Popen] = []

    # ------------------------------------------------------------------ #
    def cancel(self) -> None:
        self._cancel = True
        for p in list(self._procs):
            try:
                p.kill()
            except OSError:
                pass

    def _chk(self):
        if self._cancel:
            raise media.CancelledError()

    def _emit(self, pct: int, msg: str) -> None:
        self.progress.emit(max(0, min(100, pct)), msg)

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        # scratch space lives in the managed working folder (tmp/ in the
        # current directory by default) and is removed again below
        tmp = folders.new_temp_dir("export")
        try:
            if self.opts.mode == "mp4":
                out = self._run_video(tmp)
            elif self.opts.mode == "audio":
                out = self._run_audio(tmp)
            else:
                out = self._run_documents(tmp)
            self.finished_ok.emit(out)
        except media.CancelledError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self._procs.clear()

    # ------------------------------------------------------------------ #
    def _run_documents(self, tmp: str) -> str:
        """PDF handout / PowerPoint export (fast, no ffmpeg)."""
        from . import document_export
        mode = self.opts.mode
        if mode not in ("pdf", "pptx"):
            raise RuntimeError(f"Unknown export mode: {mode}")
        self._emit(20, f"Rendering slides ({mode.upper()}) …")
        out_path = self.opts.out_path
        os.makedirs(os.path.dirname(os.path.abspath(out_path)),
                    exist_ok=True)
        if mode == "pdf":
            return document_export.export_pdf(
                self.deck, out_path, notes=self.opts.notes,
                on_progress=self._doc_progress, check=self._chk)
        return document_export.export_pptx(
            self.deck, out_path,
            on_progress=self._doc_progress, check=self._chk)

    def _doc_progress(self, done: int, total: int) -> None:
        pct = 20 + int(78 * done / max(1, total))
        self._emit(pct, f"Rendering slide {min(done + 1, total)}/{total} …")

    # ------------------------------------------------------------------ #
    def _slide_durations(self, slides, audio_paths) -> list[float]:
        """Seconds per slide: narration length + pad, but never shorter
        than the slide's duration override (set in the inspector or by
        rehearse timings) — the override becomes a *minimum* when the
        slide has narration audio."""
        durs = []
        for slide, audio in zip(slides, audio_paths):
            override = slide.duration_override or 0.0
            if audio:
                d = media.media_duration(audio)
                base = d + self.opts.pad if d > 0 else 3.0
                durs.append(max(base, override))
            else:
                durs.append(override or 3.0)
        return durs

    def _synthesize_all(self, tmp: str, n: int) -> tuple[list, list[str]]:
        """TTS for every slide. Returns (slides, audio_paths)."""
        slides = list(self.deck.slides)
        audio_paths: list[str] = []
        base = 12
        span = 45
        for i, slide in enumerate(slides):
            self._chk()
            self._emit(base + int(span * i / max(1, n)),
                       f"Synthesizing narration {i + 1}/{n} …")
            text = slide.effective_narration()
            if text.strip():
                try:
                    audio_paths.append(tts.synthesize_cached(slide, self.deck))
                except RuntimeError as exc:
                    raise RuntimeError(f"Slide {i + 1}: {exc}")
            else:
                audio_paths.append("")
        return slides, audio_paths

    def _render_all(self, tmp: str, n: int) -> tuple[list[str], list[bool]]:
        """Render slides to PNG. Motion slides render at 2x for smooth
        Ken Burns zooming. Returns (png_paths, is_2x_flags)."""
        w, h = RESOLUTIONS.get(self.opts.resolution, (1920, 1080))
        pngs: list[str] = []
        big: list[bool] = []
        for i, slide in enumerate(self.deck.slides):
            self._chk()
            self._emit(int(12 * i / max(1, n)),
                       f"Rendering slide {i + 1}/{n} …")
            use_big = slide.motion != "none"
            tw, th = (w * 2, h * 2) if use_big else (w, h)
            img = render_slide(slide, self.deck.theme, tw, th,
                               overlay=overlay_info(self.deck, i))
            path = os.path.join(tmp, f"slide_{i:04d}.png")
            if not img.save(path, "PNG"):
                raise RuntimeError(f"Failed to write {path}")
            pngs.append(path)
            big.append(use_big)
        return pngs, big

    def _write_srt(self, tmp: str, slides, durs, transition_len: float) -> str:
        srt_path = os.path.join(tmp, "subs.srt")
        starts = subtitles.slide_starts(durs, transition_len)
        doc = subtitles.build_srt(slides, durs, starts, self.opts.pad)
        if not doc.strip():
            raise RuntimeError("No narration text found to build subtitles "
                               "from. Add narration or slide text first.")
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        return srt_path

    # ---------------------------- video -------------------------------- #
    def _run_video(self, tmp: str) -> str:
        n = len(self.deck.slides)
        if n == 0:
            raise RuntimeError("The deck has no slides to export.")
        if not media.ffmpeg_path():
            raise RuntimeError("ffmpeg was not found on your system.\n\n"
                               "Install ffmpeg (https://ffmpeg.org) and make "
                               "sure it is on your PATH, then try again.")

        pngs, big = self._render_all(tmp, n)
        slides, audio_paths = self._synthesize_all(tmp, n)
        durs = self._slide_durations(slides, audio_paths)

        # ---- transitions / subtitles ----------------------------------
        names = self._join_names(slides)
        use_trans = n > 1 and any(names)
        trans_len = self._transition_len(durs) if use_trans else 0.0
        srt_tmp = None
        if self.opts.save_srt or self.opts.burn_subtitles:
            self._chk()
            self._emit(56, "Building subtitles …")
            srt_tmp = self._write_srt(tmp, slides, durs, trans_len)

        # ---- per-slide segments ----------------------------------------
        seg_paths = []
        for i in range(n):
            self._chk()
            self._emit(58 + int(30 * i / n),
                       f"Encoding video segment {i + 1}/{n} …")
            seg = os.path.join(tmp, f"seg_{i:04d}.mp4")
            self._encode_segment(pngs[i], big[i], audio_paths[i], durs[i],
                                 seg, slides[i])
            seg_paths.append(seg)

        # ---- concat / transitions --------------------------------------
        if use_trans:
            self._chk()
            self._emit(90, "Applying transitions …")
            raw_out = self._xfade_concat(seg_paths, durs, tmp, names,
                                         trans_len)
        else:
            self._chk()
            self._emit(90, "Concatenating segments …")
            raw_out = self._concat_copy(seg_paths, tmp)

        # ---- music mix + optional subtitle burn ------------------------
        music = self.deck.music_path if self.opts.use_music else None
        if music and not os.path.isfile(music):
            music = None
        burn = srt_tmp if self.opts.burn_subtitles else None
        if music or burn:
            self._chk()
            self._emit(94, "Mixing background music / burning subtitles …")
            final = self._finalize_video(raw_out, tmp, music, burn)
        else:
            final = raw_out

        self._emit(99, "Writing output file …")
        out_path = self.opts.out_path
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        shutil.copyfile(final, out_path)
        if self.opts.save_srt and srt_tmp:
            shutil.copyfile(srt_tmp,
                            os.path.splitext(out_path)[0] + ".srt")
        self._emit(100, "Export complete.")
        return out_path

    def _transition_len(self, durs: list[float]) -> float:
        t = self.opts.transition_dur
        return max(0.2, min(t, 2.0, 0.4 * min(durs)))

    def _join_names(self, slides) -> list:
        """Transition per join: slide k's own transition controls how it
        enters (the join between k-1 and k); an empty override falls back
        to the deck-wide setting and "None" forces a hard cut."""
        deck_name = (TRANSITIONS[self.opts.transition]
                     if self.opts.transition in TRANSITIONS else None)
        names = []
        for k in range(1, len(slides)):
            per = (getattr(slides[k], "transition", "") or "").strip()
            names.append(TRANSITIONS[per] if per in TRANSITIONS
                         else deck_name)
        return names

    def _zoompan_filter(self, slide: Slide, dur: float, w: int, h: int) -> str:
        """Ken Burns zoompan filter for one slide (input is a 2x render)."""
        fps = self.opts.fps
        frames = max(2, int(math.ceil(dur * fps)) + 1)
        amp = 0.08 + 0.25 * max(0.0, min(1.0, slide.motion_intensity))
        cx = "iw/2-(iw/zoom/2)"
        cy = "ih/2-(ih/zoom/2)"
        left = "(iw-iw/zoom)"
        top = "(ih-ih/zoom)"
        p = f"on/{frames}"          # 0..1 progress
        motion = slide.motion
        if motion == "Zoom in":
            z, x, y = f"min(1+{amp:.4f}*{p},{1 + amp:.4f})", cx, cy
        elif motion == "Zoom out":
            z, x, y = f"max({1 + amp:.4f}-{amp:.4f}*{p},1.0)", cx, cy
        elif motion == "Pan right":
            z, x, y = f"{1 + amp:.4f}", f"{left}*{p}", "(ih-ih/zoom)/2"
        elif motion == "Pan left":
            z, x, y = f"{1 + amp:.4f}", f"{left}*(1-{p})", "(ih-ih/zoom)/2"
        elif motion == "Pan up":
            z, x, y = f"{1 + amp:.4f}", "(iw-iw/zoom)/2", f"{top}*(1-{p})"
        elif motion == "Pan down":
            z, x, y = f"{1 + amp:.4f}", "(iw-iw/zoom)/2", f"{top}*{p}"
        elif motion == "Zoom in + pan right":
            z, x, y = f"min(1+{amp:.4f}*{p},{1 + amp:.4f})", f"{left}*{p}", cy
        elif motion == "Zoom out + pan left":
            z, x, y = f"max({1 + amp:.4f}-{amp:.4f}*{p},1.0)", \
                      f"{left}*(1-{p})", cy
        else:
            z, x, y = "1", "0", "0"
        return (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}"
                f":s={w}x{h}:fps={fps}")

    def _encode_segment(self, png: str, big: bool, audio: str, dur: float,
                        out: str, slide: Slide) -> None:
        w, h = RESOLUTIONS.get(self.opts.resolution, (1920, 1080))
        cmd = [media.ffmpeg_path(), "-y"]
        # ---- inputs (must all come before output options) --------------
        if slide.motion != "none" and big:
            # single-frame input; zoompan generates the animation
            cmd += ["-i", png]
        else:
            cmd += ["-loop", "1", "-framerate", str(self.opts.fps),
                    "-i", png]
        if audio:
            cmd += ["-i", audio]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        # ---- output ------------------------------------------------------
        if slide.motion != "none" and big:
            cmd += ["-vf", self._zoompan_filter(slide, dur, w, h)]
        cmd += [
            "-t", f"{max(0.5, dur):.3f}",
            "-af", "apad",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            "-shortest",
            out,
        ]
        media.run(cmd, self._chk, self._procs)

    def _concat_copy(self, seg_paths: list[str], tmp: str) -> str:
        concat_list = os.path.join(tmp, "list.txt")
        with open(concat_list, "w", encoding="utf-8") as fh:
            for seg in seg_paths:
                fh.write("file '" + seg.replace("'", "'\\''") + "'\n")
        raw_out = os.path.join(tmp, "raw.mp4")
        if len(seg_paths) == 1:
            shutil.copyfile(seg_paths[0], raw_out)
        else:
            media.run([media.ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                       "-i", concat_list, "-c", "copy", raw_out],
                      self._chk, self._procs)
        return raw_out

    def _xfade_concat(self, seg_paths: list[str], durs: list[float],
                      tmp: str, names: list, t: float) -> str:
        """Join segments — xfade where the join has a transition name,
        hard concat cuts elsewhere (video + audio)."""
        graph, final_v, final_a = transition_graph(durs, names, t,
                                                   fps=self.opts.fps)
        cmd = [media.ffmpeg_path(), "-y"]
        for seg in seg_paths:
            cmd += ["-i", seg]
        cmd += ["-filter_complex", graph,
                "-map", f"[{final_v}]", "-map", f"[{final_a}]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                os.path.join(tmp, "raw.mp4")]
        media.run(cmd, self._chk, self._procs)
        return os.path.join(tmp, "raw.mp4")

    def _music_graph(self) -> str:
        """Background-music audio filter graph (ducked or plain)."""
        vol = max(0.0, min(0.6, self.deck.music_volume))
        if self.opts.duck_music:
            return (
                f"[0:a]asplit=2[nar1][nar2];"
                f"[1:a]volume={vol:.3f}[m];"
                f"[m][nar1]sidechaincompress=threshold=0.02:ratio=8:"
                f"attack=120:release=900[duck];"
                f"[nar2][duck]amix=inputs=2:duration=first:normalize=0[a]"
            )
        return (
            f"[1:a]volume={vol:.3f}[m];"
            f"[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        )

    def _subtitle_filter(self) -> str:
        size = max(8, int(self.opts.subtitle_size))
        style = (f"FontSize={size},Outline=1,Shadow=0,"
                 "OutlineColour=&H64000000,MarginV=25")
        return f"subtitles=subs.srt:force_style='{style}'"

    def _finalize_video(self, raw: str, tmp: str, music: str | None,
                        srt: str | None) -> str:
        """Single final pass applying subtitle burn-in and/or music mix.

        The subtitle filter reads 'subs.srt' relative to the temp working
        directory (cwd trick) to avoid path-escaping pitfalls everywhere.
        """
        if srt and not os.path.isfile(srt):
            srt = None
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart"]

        if srt and music:
            out = os.path.join(tmp, "final.mp4")
            cmd = [media.ffmpeg_path(), "-y", "-i", raw,
                   "-vf", self._subtitle_filter(),
                   "-stream_loop", "-1", "-i", music,
                   "-filter_complex", self._music_graph(),
                   "-map", "0:v", "-map", "[a]",
                   "-c:a", "aac", "-b:a", "192k"] + enc + [out]
            media.run(cmd, self._chk, self._procs, cwd=tmp)
            return out
        if srt:
            out = os.path.join(tmp, "final.mp4")
            cmd = [media.ffmpeg_path(), "-y", "-i", raw,
                   "-vf", self._subtitle_filter(),
                   "-c:a", "copy"] + enc + [out]
            media.run(cmd, self._chk, self._procs, cwd=tmp)
            return out
        return self._mix_music(raw, music, tmp, video=True)

    def _mix_music(self, src: str, music: str, tmp: str, video: bool) -> str:
        """Mix looped background music under the narration.

        With ducking enabled the music is side-chain compressed by the
        narration so speech stays intelligible.
        """
        if video:
            out = os.path.join(tmp, "mixed.mp4")
        else:
            out = os.path.join(tmp, f"mixed.{self.opts.audio_format}")

        base = [media.ffmpeg_path(), "-y", "-i", src,
                "-stream_loop", "-1", "-i", music,
                "-filter_complex", self._music_graph()]

        if video:
            cmd = base + ["-map", "0:v", "-map", "[a]",
                          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out]
        else:
            codec = (["-c:a", "pcm_s16le"] if self.opts.audio_format == "wav"
                     else ["-c:a", "libmp3lame", "-b:a", "192k"])
            cmd = base + ["-map", "[a]"] + codec + [out]
        media.run(cmd, self._chk, self._procs)
        return out

    # ---------------------------- audio -------------------------------- #
    def _run_audio(self, tmp: str) -> str:
        n = len(self.deck.slides)
        if n == 0:
            raise RuntimeError("The deck has no slides to export.")
        if not media.ffmpeg_path():
            raise RuntimeError("ffmpeg was not found on your system.\n\n"
                               "Install ffmpeg (https://ffmpeg.org) and make "
                               "sure it is on your PATH, then try again.")

        slides, audio_paths = self._synthesize_all(tmp, n)
        durs = self._slide_durations(slides, audio_paths)

        srt_tmp = None
        if self.opts.save_srt:
            self._chk()
            self._emit(56, "Building subtitles …")
            srt_tmp = self._write_srt(tmp, slides, durs, 0.0)

        # decode each narration to a padded WAV segment
        wav_segs = []
        for i in range(n):
            self._chk()
            self._emit(58 + int(25 * i / n),
                       f"Preparing audio segment {i + 1}/{n} …")
            seg = os.path.join(tmp, f"seg_{i:04d}.wav")
            if audio_paths[i]:
                media.run([media.ffmpeg_path(), "-y", "-i", audio_paths[i],
                           "-af", f"apad=whole_dur={max(0.5, durs[i]):.3f}",
                           "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
                           seg],
                          self._chk, self._procs)
            else:
                media.run([media.ffmpeg_path(), "-y",
                           "-f", "lavfi", "-i",
                           "anullsrc=r=44100:cl=stereo",
                           "-t", f"{max(0.5, durs[i]):.3f}",
                           "-c:a", "pcm_s16le", seg],
                          self._chk, self._procs)
            wav_segs.append(seg)

        self._chk()
        self._emit(86, "Concatenating audio …")
        concat_list = os.path.join(tmp, "alist.txt")
        with open(concat_list, "w", encoding="utf-8") as fh:
            for seg in wav_segs:
                fh.write("file '" + seg.replace("'", "'\\''") + "'\n")
        raw_wav = os.path.join(tmp, "raw.wav")
        media.run([media.ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                   "-i", concat_list, "-c", "copy", raw_wav],
                  self._chk, self._procs)

        music = self.deck.music_path if self.opts.use_music else None
        src = raw_wav
        if music and os.path.isfile(music):
            self._chk()
            self._emit(92, "Mixing background music …")
            src = self._mix_music(raw_wav, music, tmp, video=False)

        self._emit(97, "Writing output file …")
        out_path = self.opts.out_path
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        src_ext = os.path.splitext(src)[1].lower()
        dst_ext = os.path.splitext(out_path)[1].lower()
        if src_ext == dst_ext:
            shutil.copyfile(src, out_path)
        else:
            cmd = [media.ffmpeg_path(), "-y", "-i", src]
            if dst_ext == ".mp3":
                cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
            elif dst_ext == ".wav":
                cmd += ["-c:a", "pcm_s16le"]
            cmd += [out_path]
            media.run(cmd, self._chk, self._procs)

        if self.opts.save_srt and srt_tmp:
            shutil.copyfile(srt_tmp,
                            os.path.splitext(out_path)[0] + ".srt")
        self._emit(100, "Export complete.")
        return out_path
