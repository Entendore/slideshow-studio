#!/usr/bin/env python3
"""Run the Slideshow Studio pytest suite headlessly.

Usage:
    python scripts/run_tests.py                 # everything (incl. slow)
    python scripts/run_tests.py -m "not slow"   # skip ffmpeg exports
    python scripts/run_tests.py tests/test_models.py -v
Extra arguments are forwarded to pytest. Qt runs off-screen; no display
is needed.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

env = dict(os.environ)
env.setdefault("QT_QPA_PLATFORM", "offscreen")

cmd = [sys.executable, "-m", "pytest", ROOT] + sys.argv[1:]
print("$", " ".join(cmd))
raise SystemExit(subprocess.call(cmd, env=env))
