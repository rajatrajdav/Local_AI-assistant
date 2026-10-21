#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. — Mini Video GUI  (jarvis_gui.py)
==============================================================================
A compact, video-driven front end for the local `jarvis.py` engine.

The given `jarvis/Loading.mp4` is decoded on a daemon thread and looped as
the full-window background. A small central "core" shows Jarvis's current
state (boot / listening / thinking / speaking / ready) and a prominent
process line tells you exactly what is happening — like a live presentation.

Voice input starts automatically (hands-free on by default) so you never
have to touch a mic button to be heard.

Run with:
    python jarvis_gui.py
"""

import os
import sys
import time
import math
import queue
import asyncio
import threading
import webbrowser
import datetime as _dt
from collections import deque

# --------------------------------------------------------------------------
# Stable working directory (voices/, generated_files/, .env all resolve here)
# --------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

import tkinter as tk
from tkinter import font as tkfont

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _ensure(module_name, pip_name=None):
    try:
        return __import__(module_name)
    except Exception:
        try:
            import subprocess as _sp
            _sp.check_call([sys.executable, "-m", "pip", "install",
                            pip_name or module_name, "--quiet"])
            return __import__(module_name)
        except Exception as exc:
            print("FATAL: could not import %s (%s)\n       pip install %s"
                  % (module_name, exc, pip_name or module_name))
            sys.exit(2)


ctk = _ensure("customtkinter")

try:
    from PIL import Image, ImageDraw, ImageTk
    PIL_OK = True
except Exception:
    PIL_OK = False

if PIL_OK:
    _resampling = getattr(Image, "Resampling", Image)
    RESAMPLE_LANCZOS = getattr(_resampling, "LANCZOS", 1)
else:
    RESAMPLE_LANCZOS = 1

# ==========================================================================
# THEME — dark glass over the video background
# ==========================================================================
BG          = "#000000"
PANEL       = "#0B1016"
PANEL_2     = "#121922"
HAIRLINE    = "#1C2E3B"
HAIRLINE_2  = "#265066"
CYAN        = "#37E9FF"
CYAN_DIM    = "#12657A"
GOLD        = "#F4C453"
GREEN       = "#39F5A6"
AMBER       = "#F3A73B"
RED         = "#FF5567"
TEXT        = "#E7FBFF"
TEXT_DIM    = "#7FB9C9"
TEXT_MUTE   = "#3E6272"

DISPLAY = "Bahnschrift"
UI      = "Segoe UI"
MONO    = "Cascadia Mono"

STATES = {
    "BOOT":      (CYAN,  "Initialising systems",        2.2),
    "READY":     (CYAN,  "Standing by",                 0.30),
    "LISTENING": (GREEN, "Listening — speak now",       2.4),
    "THINKING":  (AMBER, "Processing your request",     3.6),
    "BUSY":      (AMBER, "Executing tool",               3.2),
    "SPEAKING":  (CYAN,  "Speaking",                     1.5),
    "OFFLINE":   (RED,   "Engine offline",               0.2),
    "ERROR":     (RED,   "Error",                        0.2),
}

EXIT_WORDS = {"exit", "quit", "bye", "goodbye", "shutdown", "stop"}
PERSONA_LABEL = {"en_male": "JARVIS — EN", "hi_male": "JARVIS — HI",
                 "en_female": "SIMMI — EN"}
REPO_URL = "https://github.com/rajatrajdav/Local_AI-assistant"
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_files")

# ---------------------------------------------------------------- video
VIDEO_CANDIDATES = (
    os.path.join(BASE_DIR, "jarvis", "Loading.mp4"),
    os.path.join(BASE_DIR, "Loading.mp4"),
)
VIDEO_FRAME_TIME = 40  # ms per frame (~25 fps)


def _find_video():
    """Return the first existing Loading.mp4 candidate, else None."""
    for path in VIDEO_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def _extract_frames(video_path, target_w=720, max_frames=240):
    """Sample + downscale video frames to PhotoImages (best effort)."""
    frames = []
    try:
        import imageio.v2 as imageio  # type: ignore
        reader = imageio.get_reader(video_path, "ffmpeg")
        for i, frame in enumerate(reader):
            if i >= max_frames:
                break
            img = Image.fromarray(frame)
            img.thumbnail((target_w, target_w), RESAMPLE_LANCZOS)
            frames.append(ImageTk.PhotoImage(img))
        reader.close()
    except Exception:
        frames = []
    return frames
