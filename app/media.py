"""ffmpeg / ffprobe helpers. All blocking; use from worker threads."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def is_available() -> tuple[bool, str]:
    """(available, message) for the status bar / dialogs."""
    if ffmpeg_path() and ffprobe_path():
        return True, "ffmpeg: ready"
    if ffmpeg_path():
        return True, "ffmpeg: ready (no ffprobe, using fallback probing)"
    return False, ("ffmpeg NOT found — install it and make sure 'ffmpeg' is "
                   "on your PATH to export MP4/audio")


def run(args: list[str], cancel_check=None, kill_proc=None,
        cwd: str | None = None) -> subprocess.Popen:
    """Run ffmpeg/ffprobe with cancellation support. Raises RuntimeError.

    stderr is captured to a temp buffer; on failure its tail is included in
    the error message so filter/option problems are diagnosable.
    """
    errf = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=errf,
            stdin=subprocess.DEVNULL,  # ffmpeg must never read stdin
            creationflags=_CREATE_NO_WINDOW, cwd=cwd)
    except OSError as exc:
        errf.close()
        raise RuntimeError(f"Could not launch {args[0]}: {exc}") from exc
    if kill_proc is not None:
        kill_proc.append(proc)
    cancelled = False
    try:
        while True:
            if cancel_check is not None and cancel_check():
                cancelled = True
                proc.kill()
                raise CancelledError()
            if proc.poll() is not None:
                break
            try:
                proc.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
    except CancelledError:
        raise
    finally:
        rc = proc.poll()
        errf.seek(0)
        err_tail = b""
        try:
            err_tail = errf.read()[-1200:]
        except OSError:
            pass
        errf.close()
    if rc != 0 and not (cancelled or (cancel_check is not None
                                      and cancel_check())):
        detail = err_tail.decode("utf-8", "replace").strip()
        msg = (f"{os.path.basename(args[0])} failed (exit code {rc}).")
        if detail:
            # keep the last lines — ffmpeg reports the actual problem last
            lines = [ln for ln in detail.splitlines() if ln.strip()]
            msg += "\n" + "\n".join(lines[-6:])
        raise RuntimeError(msg)
    return proc


class CancelledError(RuntimeError):
    pass


def media_duration(path: str) -> float:
    """Duration of an audio/video file in seconds (ffprobe, ffmpeg fallback)."""
    if ffprobe_path():
        try:
            out = subprocess.run(
                [ffprobe_path(), "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                 path],
                capture_output=True, text=True, timeout=30,
                creationflags=_CREATE_NO_WINDOW)
            val = out.stdout.strip()
            if val:
                return float(val)
        except (ValueError, subprocess.SubprocessError):
            pass
    # fallback: parse `ffmpeg -i` banner
    try:
        out = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=30,
                             creationflags=_CREATE_NO_WINDOW)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", out.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except (subprocess.SubprocessError, ValueError):
        pass
    return 0.0
