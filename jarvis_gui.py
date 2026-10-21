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
# ==========================================================================
# ENGINE API — heavy jarvis.py engine loaded on a background thread
# ==========================================================================
_engine = None
ENGINE_OK = False
ENGINE_ERR = "Engine has not been loaded yet."
ENGINE_LOAD_MS = 0
VOICES = {
    "en_male":   {"name": "English Male (Medium)",   "language": "en"},
    "hi_male":   {"name": "Hindi Male (Pratham)",    "language": "hi"},
    "en_female": {"name": "English Female (LibriTTS)", "language": "en"},
}
PERSONALITIES = {}
FUNCTION_MAP = {}
process_user_input = None
execute_function = None
get_system_info = None
detect_target_personality = None
detect_lang = None
detect_wake_word = None
strip_wake_word = None
listen_natural_fn = None
VOICE_INPUT = False
SR_ERROR = ""
ENGLISH_ONLY_NOTE = "Voice input needs SpeechRecognition + sounddevice + a working microphone."


def engine_get(name, default=None):
    if _engine is None:
        return default
    return getattr(_engine, name, default)


def _load_engine():
    """Import the heavy jarvis.py engine. Called from a background thread."""
    global _engine, ENGINE_OK, ENGINE_ERR, ENGINE_LOAD_MS
    global VOICES, PERSONALITIES, FUNCTION_MAP, OUTPUT_DIR
    global process_user_input, execute_function, get_system_info
    global detect_target_personality, detect_lang
    global detect_wake_word, strip_wake_word, listen_natural_fn
    global VOICE_INPUT, SR_ERROR

    t0 = time.time()
    try:
        import jarvis as _mod
        _engine = _mod
        VOICES = getattr(_mod, "VOICES", VOICES)
        PERSONALITIES = getattr(_mod, "PERSONALITIES", {})
        FUNCTION_MAP = getattr(_mod, "FUNCTION_MAP", {})
        OUTPUT_DIR = getattr(_mod, "OUTPUT_DIR", OUTPUT_DIR)
        process_user_input = getattr(_mod, "process_user_input", None)
        execute_function = getattr(_mod, "execute_function", None)
        get_system_info = getattr(_mod, "get_system_info", None)
        detect_target_personality = getattr(_mod, "detect_target_personality", None)
        detect_lang = getattr(_mod, "detect_lang", None)
        detect_wake_word = getattr(_mod, "detect_wake_word", None)
        strip_wake_word = getattr(_mod, "strip_wake_word", None)
        listen_natural_fn = getattr(_mod, "listen_natural", None)
        ENGINE_OK = True
    except BaseException as exc:
        ENGINE_OK = False
        ENGINE_ERR = "%s: %s" % (type(exc).__name__, exc)

    try:
        import speech_recognition  # noqa: F401
        VOICE_INPUT = bool(getattr(_engine, "SoundDeviceMicrophone", None)) \
            and listen_natural_fn is not None
        if not VOICE_INPUT:
            SR_ERROR = "Microphone backend unavailable inside jarvis.py."
    except Exception as exc:
        VOICE_INPUT = False
        SR_ERROR = str(exc)

    ENGINE_LOAD_MS = int((time.time() - t0) * 1000)
    return ENGINE_OK


def speak_blocking(text, voice, stop_event=None):
    if not (ENGINE_OK and _engine and text):
        return
    try:
        _engine.play_piper_tts(text, voice, stop_event=stop_event)
        return
    except Exception:
        pass
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_engine.speak_handler(text, voice))
        finally:
            loop.close()
    except Exception:
        pass

# ==========================================================================
# Colour / text helpers
# ==========================================================================
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % (max(0, min(255, int(rgb[0]))),
                              max(0, min(255, int(rgb[1]))),
                              max(0, min(255, int(rgb[2]))))


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ca, cb = _rgb(a), _rgb(b)
    return _hex(tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3)))


def fade(colour, t):
    return mix(BG, colour, t)


def hms(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            return ("%d B" % n) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def shorten(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"
# ==========================================================================
# ICON DRAWING — small vector icons rendered with PIL (no external assets)
# ==========================================================================
_ICON_CACHE = {}


def _draw_icon(draw, kind, S, colour, stroke):
    """Draw a kind-of icon onto a PIL ImageDraw canvas of size SxS."""
    cx = cy = S / 2.0
    def line(pts, width=None):
        w = width if width is not None else stroke
        draw.line(pts, fill=colour, width=int(w))
    def box(x0, y0, x1, y1, radius=0, fill=False):
        if radius:
            r = radius
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r,
                                   fill=colour if fill else None,
                                   outline=None if fill else colour,
                                   width=int(stroke))
        else:
            if fill:
                draw.rectangle([x0, y0, x1, y1], fill=colour)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=colour,
                               width=int(stroke))
    def circ(x, y, r, fill=False):
        if fill:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)
        else:
            draw.ellipse([x - r, y - r, x + r, y + r], outline=colour,
                         width=int(stroke))
    def arc(x, y, r, start, end):
        draw.arc([x - r, y - r, x + r, y + r], start=start, end=end,
                 fill=colour, width=int(stroke))
    def pts(*pairs):
        return [(cx + dx * S / 100.0, cy + dy * S / 100.0) for dx, dy in pairs]

    if kind == "core":
        circ(cx, cy, S * 0.36); circ(cx, cy, S * 0.23); circ(cx, cy, S * 0.11, fill=True)
        for i in range(8):
            ang = math.radians(i * 45)
            line([(cx + S * 0.27 * math.cos(ang), cy + S * 0.27 * math.sin(ang)),
                  (cx + S * 0.34 * math.cos(ang), cy + S * 0.34 * math.sin(ang))])
    elif kind == "mic":
        box(S * 0.36, S * 0.10, S * 0.64, S * 0.56, radius=S * 0.14)
        arc(cx, S * 0.44, S * 0.27, 6, 174)
        line([(cx, S * 0.71), (cx, S * 0.86)])
        line([(S * 0.35, S * 0.86), (S * 0.65, S * 0.86)])
    elif kind == "stop":
        box(S * 0.27, S * 0.27, S * 0.73, S * 0.73, radius=S * 0.07, fill=True)
    elif kind == "send":
        draw.polygon(pts((10, 50), (90, 12), (58, 90), (46, 58)), fill=colour)
    elif kind == "speaker":
        draw.polygon(pts((16, 38), (34, 38), (56, 18), (56, 82), (34, 62), (16, 62)),
                     fill=colour)
        arc(cx, S * 0.50, S * 0.20, 300, 60)
    elif kind == "mute":
        draw.polygon(pts((14, 38), (32, 38), (54, 18), (54, 82), (32, 62), (14, 62)),
                     fill=colour)
        line([(S * 0.68, S * 0.38), (S * 0.90, S * 0.62)])
        line([(S * 0.90, S * 0.38), (S * 0.68, S * 0.62)])
    elif kind == "broadcast":
        circ(cx, S * 0.66, S * 0.07, fill=True)
        arc(cx, S * 0.66, S * 0.24, 195, 345)
        arc(cx, S * 0.66, S * 0.40, 205, 335)
    elif kind == "export":
        line([(S * 0.50, S * 0.74), (S * 0.50, S * 0.16)])
        line([(S * 0.33, S * 0.33), (S * 0.50, S * 0.16), (S * 0.67, S * 0.33)])
        line([(S * 0.20, S * 0.58), (S * 0.20, S * 0.86),
              (S * 0.80, S * 0.86), (S * 0.80, S * 0.58)])
    elif kind == "refresh":
        arc(cx, cy, S * 0.33, 34, 326)
        draw.polygon(pts((82, 30), (66, 30), (78, 46)), fill=colour)
    elif kind == "trash":
        line([(S * 0.20, S * 0.28), (S * 0.80, S * 0.28)])
        line([(S * 0.39, S * 0.28), (S * 0.39, S * 0.14),
              (S * 0.61, S * 0.14), (S * 0.61, S * 0.28)])
        line([(S * 0.29, S * 0.28), (S * 0.36, S * 0.88),
              (S * 0.64, S * 0.88), (S * 0.71, S * 0.28)])
        line([(S * 0.43, S * 0.40), (S * 0.46, S * 0.76)])
        line([(S * 0.57, S * 0.40), (S * 0.54, S * 0.76)])
    elif kind == "chip":
        box(S * 0.26, S * 0.26, S * 0.74, S * 0.74, radius=S * 0.06)
        box(S * 0.41, S * 0.41, S * 0.59, S * 0.59, radius=S * 0.03)
        for c in (0.34, 0.50, 0.66):
            line([(S * c, S * 0.12), (S * c, S * 0.26)])
            line([(S * c, S * 0.74), (S * c, S * 0.88)])
            line([(S * 0.12, S * c), (S * 0.26, S * c)])
            line([(S * 0.74, S * c), (S * 0.88, S * c)])
    elif kind == "eye":
        draw.polygon(pts((10, 50), (32, 30), (68, 30), (90, 50),
                         (68, 70), (32, 70)), outline=colour)
        circ(cx, cy, S * 0.09)
    elif kind == "terminal":
        box(S * 0.08, S * 0.16, S * 0.92, S * 0.84, radius=S * 0.08)
        line([(S * 0.24, S * 0.34), (S * 0.40, S * 0.50), (S * 0.24, S * 0.66)])
        line([(S * 0.50, S * 0.66), (S * 0.74, S * 0.66)])
    elif kind == "close":
        line([(S * 0.26, S * 0.26), (S * 0.74, S * 0.74)])
        line([(S * 0.74, S * 0.26), (S * 0.26, S * 0.74)])
    elif kind == "power":
        arc(cx, cy, S * 0.30, 300, 60)
        line([(cx, S * 0.14), (cx, S * 0.52)])
    elif kind == "folder":
        box(S * 0.08, S * 0.26, S * 0.92, S * 0.86, radius=S * 0.09)
        line([(S * 0.08, S * 0.26), (S * 0.08, S * 0.18),
              (S * 0.36, S * 0.18), (S * 0.46, S * 0.26)])
    elif kind == "gauge":
        arc(cx, S * 0.62, S * 0.33, 160, 380)
        line([(cx, S * 0.62), (S * 0.74, S * 0.36)])
        circ(cx, S * 0.62, S * 0.03, fill=True)
    elif kind == "info":
        circ(cx, cy, S * 0.37); circ(cx, S * 0.32, S * 0.036, fill=True)
        line([(cx, S * 0.44), (cx, S * 0.70)])
    elif kind == "pulse":
        line([(S * 0.08, S * 0.58), (S * 0.28, S * 0.58),
              (S * 0.38, S * 0.24), (S * 0.50, S * 0.80),
              (S * 0.62, S * 0.38), (S * 0.72, S * 0.58),
              (S * 0.92, S * 0.58)])
    elif kind == "unknown":
        circ(cx, cy, S * 0.30)
def make_icon(kind, colour, size=20, stroke=1.9):
    if not PIL_OK:
        return None
    key = (kind, colour, size, stroke)
    hit = _ICON_CACHE.get(key)
    if hit is not None:
        return hit
    scale = 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        _draw_icon(draw, kind, S, _rgb(colour),
                   max(1, int(round(stroke * scale))))
    except Exception:
        pass
    img = img.resize((size, size), RESAMPLE_LANCZOS)
    icon = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = icon
    return icon
# ==========================================================================
# WIDGET — central state core (targeting-reticle style, state + amplitude reactive)
# ==========================================================================
class HUDReactor(tk.Canvas):
    def __init__(self, master, size=220, **kwargs):
        super().__init__(master, width=size, height=size, bg=BG,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.size = size
        self.state = "BOOT"
        self.hue = CYAN
        self.amp = 0.0
        self.spin = 0.0
        self.spin_speed = 0.35
        self.levels = deque([0.0] * 90, maxlen=90)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.size = max(120, min(event.width, event.height))

    def set_state(self, state):
        info = STATES.get(state, STATES["READY"])
        self.hue = info[0]
        self.spin_speed = info[2]
        self.state = state

    def tick(self, dt, amp):
        self.amp += (amp - self.amp) * 0.45
        self.spin = (self.spin + self.spin_speed * dt * 60.0) % 360.0
        self.levels.append(amp)
        self._redraw()

    def _redraw(self):
        try:
            self.delete("fx")
        except tk.TclError:
            return
        S = self.size
        if S < 80:
            return
        cx = cy = S / 2.0
        R = S * 0.46
        hue = self.hue
        spin = self.spin

        # outer degree ring with tick marks (targeting reticle)
        self.create_oval(cx - R, cy - R, cx + R, cy + R, outline=HAIRLINE_2,
                         width=1, tags="fx")
        for i in range(72):
            ang = math.radians(i * 5)
            major = (i % 9 == 0)
            r0 = R - (20 if major else 11)
            r1 = R
            bright = 0.55 if major else 0.22
            self.create_line(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang),
                             cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                             fill=mix(HAIRLINE_2, hue, bright), width=1, tags="fx")

        # rotating broken arcs (segmented bezel)
        r1 = R - 26
        for i in range(6):
            start = (spin * 0.6 + i * 60) % 360
            self.create_arc(cx - r1, cy - r1, cx + r1, cy + r1,
                            start=start, extent=34, style="arc",
                            outline=mix(HAIRLINE_2, hue, 0.85), width=2, tags="fx")

        # dense tick collar (inner)
        r2 = R - 46
        n_ticks = 64
        for i in range(n_ticks):
            ang = math.radians(i * (360.0 / n_ticks) + spin * 1.4)
            bright = 0.25 + 0.4 * (0.5 + 0.5 * math.cos(ang - math.radians(spin)))
            rr0, rr1 = r2 - 9, r2
            self.create_line(cx + rr0 * math.cos(ang), cy + rr0 * math.sin(ang),
                             cx + rr1 * math.cos(ang), cy + rr1 * math.sin(ang),
                             fill=mix(HAIRLINE, hue, bright), width=2, tags="fx")

        # counter-rotating segmented ring (bright)
        r3 = R - 66
        for i in range(3):
            start = (-spin * 1.3 + i * 120) % 360
            self.create_arc(cx - r3, cy - r3, cx + r3, cy + r3,
                            start=start, extent=70, style="arc",
                            outline=fade(hue, 0.85), width=3, tags="fx")

        # inner solid ring
        r4 = R - 92
        self.create_oval(cx - r4, cy - r4, cx + r4, cy + r4,
                         outline=mix(HAIRLINE_2, hue, 0.6), width=2, tags="fx")

        # speaking waveform ring (real TTS amplitude)
        if self.state == "SPEAKING":
            base_r = r4 - 16
            vals = list(self.levels)
            n = max(1, len(vals))
            for i in range(0, n, 2):
                ang = math.radians(i * (360.0 / n) - spin * 0.5)
                level = vals[i]
                length = 5 + level * 34
                self.create_line(cx + base_r * math.cos(ang), cy + base_r * math.sin(ang),
                                 cx + (base_r + length) * math.cos(ang),
                                 cy + (base_r + length) * math.sin(ang),
                                 fill=mix(CYAN_DIM, hue, min(1.0, 0.3 + level)),
                                 width=2, tags="fx")

        # scanning sweep (radar look)
        sweep_ang = math.radians(spin * 2.0)
        r5 = r4 - 14
        self.create_line(cx, cy, cx + r5 * math.cos(sweep_ang), cy + r5 * math.sin(sweep_ang),
                         fill=fade(hue, 0.5), width=1, tags="fx")

        # cross hairs
        for ang in (0, 90, 180, 270):
            a = math.radians(ang)
            self.create_line(cx + (r4 - 20) * math.cos(a), cy + (r4 - 20) * math.sin(a),
                             cx + (r4 + 6) * math.cos(a), cy + (r4 + 6) * math.sin(a),
                             fill=mix(HAIRLINE_2, hue, 0.7), width=1, tags="fx")

        # centre glow + core
        core_r = 30 + self.amp * 14
        for i, gr in enumerate((core_r + 26, core_r + 18, core_r + 10)):
            bright = 0.08 + 0.22 * (i / 3.0) + self.amp * 0.25
            self.create_oval(cx - gr, cy - gr, cx + gr, cy + gr,
                             outline=fade(hue, bright), width=1, tags="fx")
        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r,
                         fill=mix(BG, hue, 0.14), outline=mix(hue, GOLD, 0.35),
                         width=2, tags="fx")
        inner = core_r * 0.5
        self.create_oval(cx - inner, cy - inner, cx + inner, cy + inner,
                         outline=hue, width=1, tags="fx")
# ==========================================================================
# THE APPLICATION
# ==========================================================================
class JarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("J.A.R.V.I.S")
        # Mini screen — compact and accurate for a demo / presentation look.
        self.geometry("720x520")
        self.minsize(620, 440)
        self.configure(fg_color=BG)

        # ---- session state ----
        self.conversation = []
        self.current_voice = "en_male"
        self.tts_enabled = True
        self.handsfree = True          # <-- auto-listen: no manual mic touch needed
        self.status = "BOOT"
        self.started = time.time()
        self.msg_count = 0
        self.tool_count = 0
        self.sys_info = {}
        self.process_step = ""         # prominent process line text

        self._busy = False
        self._speaking = False
        self._capturing = False
        self._closing = False
        self._engine_ready = False
        self._boot_t0 = time.time()
        self._last_frame = time.time()
        self._capture_token = 0
        self._handsfree_job = None
        self._loading_job = None
        self._loading_anim_started = False
        self._bg_job = None
        self._boot_poll_job = None
        self._wrap_labels = []
        self._toast_widget = None

        self._tts_stop = threading.Event()
        self._amp_hist = deque([0.0] * 90, maxlen=90)
        self._cpu_hist = deque(maxlen=120)
        self._mem_hist = deque(maxlen=120)

        self.to_engine = queue.Queue()
        self.from_engine = queue.Queue()

        self._build_layout()
        threading.Thread(target=self._boot_engine, daemon=True).start()
        threading.Thread(target=self._engine_loop, daemon=True).start()
        threading.Thread(target=self._sysinfo_loop, daemon=True).start()

        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick_clock()
        self._poll_engine()
        self._animate()

        # Boot sequence: looping Loading.mp4 loading screen covers the window
        # while the heavy engine loads. On engine-ready we tear it down and
        # reveal the video-background mini interface.
        self._build_loading_screen()
        threading.Thread(target=self._decode_loading_video, daemon=True).start()
        self._boot_poll_job = self.after(250, self._boot_poll)
    # ------------------------------------------------------------- layout
    def _build_layout(self):
        # Full-window backdrop canvas: the Loading.mp4 background is drawn
        # here and is NOT covered by any full-screen opaque frame.
        self.backdrop = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ---- central core (small reactor) ----
        self.core_holder = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.core_holder.place(relx=0.5, rely=0.42, anchor="center")
        self.core = HUDReactor(self.core_holder, size=220)
        self.core.pack()

        # brand
        self.brand = ctk.CTkLabel(self, text="J.A.R.V.I.S.",
                                  font=(DISPLAY, 20, "bold"), text_color=CYAN,
                                  fg_color=BG)
        self.brand.place(relx=0.5, rely=0.60, anchor="center")

        # ---- prominent process line (what Jarvis is doing right now) ----
        self.process_lbl = ctk.CTkLabel(
            self, text="Initialising …", font=(UI, 13, "bold"),
            text_color=TEXT, fg_color=BG)
        self.process_lbl.place(relx=0.5, rely=0.66, anchor="center")

        # state chip (small, under the process line)
        self.state_chip = ctk.CTkLabel(
            self, text="\u25cf BOOT", font=(MONO, 10, "bold"),
            text_color=CYAN, fg_color=PANEL, corner_radius=10, padx=10, pady=4)
        self.state_chip.place(relx=0.5, rely=0.715, anchor="center")

        # ---- mini transcript (bottom) ----
        self.tr_frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.tr_frame.place(relx=0.5, rely=0.855, anchor="center",
                            relwidth=0.94, relheight=0.22)
        self.tr_frame.grid_rowconfigure(0, weight=1)
        self.tr_frame.grid_columnconfigure(0, weight=1)

        self.tr_canvas = tk.Canvas(self.tr_frame, bg=PANEL, highlightthickness=0,
                                   bd=0, takefocus=0)
        self.tr_scroll = ctk.CTkScrollbar(self.tr_frame, command=self.tr_canvas.yview,
                                          width=10, corner_radius=6,
                                          fg_color=PANEL_2, button_color=HAIRLINE_2,
                                          button_hover_color=CYAN_DIM)
        self.tr_canvas.configure(yscrollcommand=self.tr_scroll.set)
        self.tr_canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 2), pady=6)
        self.tr_scroll.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 6))

        self.tr_inner = ctk.CTkFrame(self.tr_canvas, fg_color=PANEL, corner_radius=0)
        self.tr_window = self.tr_canvas.create_window((0, 0), window=self.tr_inner,
                                                      anchor="nw")
        self.tr_inner.bind("<Configure>",
                           lambda e: self.tr_canvas.configure(
                               scrollregion=self.tr_canvas.bbox("all")))
        self.tr_canvas.bind("<Configure>",
                            lambda e: self.tr_canvas.itemconfigure(
                                self.tr_window, width=e.width))
        self.tr_row = 0

        # ---- bottom mic / handsfree bar ----
        self.bar = tk.Frame(self, bg=PANEL)
        self.bar.place(relx=0.5, rely=0.955, anchor="center",
                       relwidth=0.94, height=44)
        self.bar.grid_columnconfigure(0, weight=1)
        self.bar.grid_columnconfigure(1, weight=1)
        self.bar.grid_columnconfigure(2, weight=1)

        self.mic_ind = ctk.CTkLabel(
            self.bar, text="\u25cf MIC OFF", font=(MONO, 10, "bold"),
            text_color=TEXT_MUTE, fg_color=PANEL_2, corner_radius=8, padx=10, pady=6)
        self.mic_ind.grid(row=0, column=0, sticky="w", padx=10, pady=6)

        self.hf_btn = ctk.CTkButton(
            self.bar, text="", image=make_icon("broadcast", CYAN, 15, 1.8),
            width=34, height=30, corner_radius=10, fg_color=PANEL_2,
            hover_color=HAIRLINE_2, command=self.toggle_handsfree)
        self.hf_btn.grid(row=0, column=1)

        self.close_btn = ctk.CTkButton(
            self.bar, text="", image=make_icon("close", TEXT_DIM, 13, 1.8),
            width=34, height=30, corner_radius=10, fg_color=PANEL_2,
            hover_color=HAIRLINE_2, command=self._on_close)
        self.close_btn.grid(row=0, column=2, sticky="e", padx=10, pady=6)
    # ---------------------------------------------------------------- boot video
    def _build_loading_screen(self):
        """Mini loading screen: Loading.mp4 viewport + title while engine loads."""
        self.loading = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.loading.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.loading.lift()

        self.loading_vid = tk.Label(self.loading, bg=BG, bd=0,
                                    highlightthickness=0)
        self.loading_vid.place(relx=0.5, rely=0.42, anchor="center")

        self.loading_title = ctk.CTkLabel(
            self.loading, text="J.A.R.V.I.S.", font=(DISPLAY, 19, "bold"),
            text_color=CYAN, fg_color=BG)
        self.loading_title.place(relx=0.5, rely=0.60, anchor="center")

        self.loading_sub = ctk.CTkLabel(
            self.loading, text="Initialising systems …",
            font=(UI, 12), text_color=TEXT_DIM, fg_color=BG)
        self.loading_sub.place(relx=0.5, rely=0.66, anchor="center")

        self.loading_detail = ctk.CTkLabel(
            self.loading, text="Loading interface assets",
            font=(MONO, 9), text_color=TEXT_MUTE, fg_color=BG)
        self.loading_detail.place(relx=0.5, rely=0.70, anchor="center")

    def _boot_poll(self):
        if self._closing:
            return
        if getattr(self, "loading", None) is not None:
            frames = getattr(self, "_loading_frames", None)
            if frames and not getattr(self, "_loading_anim_started", False):
                self._loading_anim_started = True
                self._start_loading_animation()
        if self._engine_ready and getattr(self, "loading", None) is not None:
            self._finish_boot()
            return
        if not self._closing:
            self._boot_poll_job = self.after(250, self._boot_poll)

    def _decode_loading_video(self):
        """Decode Loading.mp4 frames on a background thread so boot stays fluid."""
        path = _find_video()
        frames = _extract_frames(path, target_w=640, max_frames=140) if path else []
        self._loading_frames = frames

    def _start_loading_animation(self):
        if self._closing or not getattr(self, "loading", None):
            return
        self._animate_loading()

    def _animate_loading(self, idx=0):
        if self._closing or not getattr(self, "loading", None):
            return
        frames = getattr(self, "_loading_frames", []) or []
        try:
            if frames:
                self.loading_vid.configure(image=frames[idx])
                self.loading_vid.image = frames[idx]
        except Exception:
            pass
        self._loading_job = self.after(VIDEO_FRAME_TIME,
                                       lambda: self._animate_loading(
                                           (idx + 1) % len(frames) if frames else idx))

    def _finish_boot(self):
        """Tear down the loading screen, start the video background, show HUD."""
        if self._closing:
            return
        try:
            if self._loading_job:
                self.after_cancel(self._loading_job)
            self._loading_job = None
            if getattr(self, "loading", None) is not None:
                self.loading.destroy()
                self.loading = None
        except Exception:
            pass
        self._start_background_video()
        self.after(80, self._show_transcript_intro)

    def _show_transcript_intro(self):
        self._add_message("notice", "System online. Say something — Jarvis is listening.")

    def _start_background_video(self):
        """Loop Loading.mp4 on the full-window backdrop behind the HUD."""
        path = _find_video()
        self.backdrop.configure(bg=BG)
        if not path:
            return
        self._bg_idx = 0
        size = (max(self.winfo_width(), 720), max(self.winfo_height(), 520))
        threading.Thread(target=self._decode_background_video,
                         args=(path, size), daemon=True).start()

    def _decode_background_video(self, path, size):
        frames = _extract_frames(path, target_w=max(size), max_frames=240)
        self._bg_frames = frames
        self.after(0, self._animate_background)

    def _animate_background(self):
        if self._closing or not getattr(self, "_bg_frames", None):
            return
        frames = self._bg_frames
        frame = frames[self._bg_idx]
        try:
            self.backdrop.delete("bg_frame")
            cx = max(self.winfo_width() // 2, 1)
            cy = max(self.winfo_height() // 2, 1)
            self.backdrop.create_image(cx, cy, image=frame, anchor="center",
                                       tags="bg_frame")
            self.backdrop.tag_lower("bg_frame")
        except Exception:
            pass
        self._bg_idx = (self._bg_idx + 1) % len(frames)
        self._bg_job = self.after(VIDEO_FRAME_TIME, self._animate_background)
    # ======================================================= ENGINE WORKERS
    def _boot_engine(self):
        _load_engine()
        self._engine_ready = True
        self.from_engine.put({"_kind": "engine_ready"})

    def _engine_loop(self):
        while not self._closing:
            try:
                job = self.to_engine.get(timeout=0.4)
            except queue.Empty:
                continue
            if job is None:
                break
            kind = job.get("_kind")
            try:
                if kind == "chat":
                    self._run_chat(job.get("text", ""))
                elif kind == "voice_capture":
                    self._run_capture(job.get("token"))
                elif kind == "shutdown":
                    break
            except Exception as exc:
                self.from_engine.put({"_kind": "error", "text": str(exc)})

    def _sysinfo_loop(self):
        while not self._closing:
            info = {}
            try:
                if ENGINE_OK and get_system_info:
                    info = get_system_info() or {}
            except Exception:
                info = {}
            info["_ts"] = time.time()
            self.sys_info = info
            self.from_engine.put({"_kind": "sysinfo", "info": info})
            time.sleep(2.0)

    def _run_capture(self, token):
        text = ""
        if VOICE_INPUT and listen_natural_fn:
            try:
                text = (listen_natural_fn() or "").strip()
            except Exception:
                text = ""
        self.from_engine.put({"_kind": "voice_result", "text": text, "token": token})
    def _run_chat(self, user_text):
        user_text = (user_text or "").strip()
        if not user_text:
            self.from_engine.put({"_kind": "status", "state": "READY"})
            return
        self.from_engine.put({"_kind": "user", "text": user_text})
        self.from_engine.put({"_kind": "status", "state": "THINKING"})

        if not ENGINE_OK or process_user_input is None:
            self.from_engine.put({"_kind": "error",
                                  "text": "The jarvis engine is unavailable. %s" % ENGINE_ERR})
            self.from_engine.put({"_kind": "status", "state": "READY"})
            return

        clean = user_text
        try:
            if detect_wake_word and detect_wake_word(clean):
                stripped = (strip_wake_word(clean) if strip_wake_word else "") or ""
                if not stripped.strip():
                    self.conversation.append({"role": "user", "content": clean})
                    self.conversation.append({"role": "assistant",
                                              "content": "Yes sir? How can I help you?"})
                    self._deliver("Yes sir? How can I help you?", None)
                    return
                clean = stripped.strip()
        except Exception:
            pass

        if clean.lower() in EXIT_WORDS:
            farewell = "Goodbye. Have a wonderful day."
            self.conversation.append({"role": "user", "content": clean})
            self.conversation.append({"role": "assistant", "content": farewell})
            self._deliver(farewell, None)
            return

        personality, language, reason = None, "en", None
        try:
            personality = detect_target_personality(clean) if detect_target_personality else None
            language = detect_lang(clean) if detect_lang else "en"
        except Exception:
            personality, language = None, "en"

        new_voice = None
        if personality == "jarvis":
            new_voice = "hi_male" if language == "hi" else "en_male"
            reason = "you addressed Jarvis"
        elif personality == "simmi":
            new_voice = "en_female"
            reason = "you addressed Simmi"
        elif language == "hi" and self.current_voice != "hi_male":
            new_voice = "hi_male"
            reason = "Hindi input detected"
        if new_voice and new_voice in VOICES and new_voice != self.current_voice:
            self.current_voice = new_voice
            self.from_engine.put({"_kind": "voice_switch", "voice": new_voice,
                                  "reason": reason})
        self.from_engine.put({"_kind": "intent", "text": "%s \u2192 %s" % (
            shorten(clean, 70), reason or "conversational turn")})

        t0 = time.time()
        try:
            result = process_user_input(clean, self.conversation, self.current_voice) or {}
        except Exception as exc:
            result = {}
            self.from_engine.put({"_kind": "error", "text": "Model call failed: %s" % exc})
        elapsed = int((time.time() - t0) * 1000)

        out = (result.get("response") or "").strip() or "I am on it."
        voice_out = self.current_voice
        preference = result.get("voice_preference")
        if preference and preference in VOICES and preference != self.current_voice:
            self.current_voice = preference
            voice_out = preference
            self.from_engine.put({"_kind": "voice_switch", "voice": preference,
                                  "reason": result.get("reason") or "model preference"})

        tool_info = None
        tool_call = result.get("tool_call")
        if tool_call:
            name = tool_call.get("name") or "unknown_tool"
            args = tool_call.get("arguments") or {}
            self.from_engine.put({"_kind": "tool_start", "name": name, "args": args})
            try:
                tool_result = execute_function(name, args)
                ok = str(tool_result).startswith("Success")
            except Exception as exc:
                tool_result, ok = "Error: %s" % exc, False
            tool_info = {"name": name.replace("_", " "), "ok": ok,
                         "detail": shorten(tool_result, 160)}
            self.from_engine.put({"_kind": "tool_done", "name": name, "ok": ok,
                                  "text": str(tool_result)})
            if "Permission denied" not in str(tool_result):
                if ok:
                    out = "%s Done! %s" % (out, str(tool_result).replace("Success: ", ""))
                else:
                    out = "%s %s" % (out, tool_result)

        self.conversation.append({"role": "user", "content": clean})
        self.conversation.append({"role": "assistant", "content": out})
        if len(self.conversation) > 60:
            self.conversation = self.conversation[-60:]

        self.from_engine.put({"_kind": "ai", "text": out, "tool": tool_info,
                              "voice": voice_out, "ms": elapsed, "user": clean})
        if self.tts_enabled:
            self._speak(out, voice_out)
        else:
            self.from_engine.put({"_kind": "status", "state": "READY"})

    def _deliver(self, text, tool):
        self.from_engine.put({"_kind": "ai", "text": text, "tool": tool,
                              "voice": self.current_voice, "ms": 0, "user": ""})
        if self.tts_enabled:
            self._speak(text, self.current_voice)
        else:
            self.from_engine.put({"_kind": "status", "state": "READY"})
    def _speak(self, text, voice):
        self._tts_stop.clear()
        threading.Thread(target=self._tts_worker, args=(text, voice),
                         daemon=True).start()

    def _piper_play(self, text, voice, stop_event):
        engines = engine_get("voice_engines") or {}
        piper_voice = engines.get(voice)
        np_mod = engine_get("np")
        sd_mod = engine_get("sd")
        if piper_voice is None or np_mod is None or sd_mod is None:
            return False
        language = (VOICES.get(voice) or {}).get("language", "en")
        normaliser = engine_get("normalize_hindi_text" if language == "hi"
                                else "normalize_english_text")
        if callable(normaliser):
            try:
                text = normaliser(text)
            except Exception:
                pass
        if not text.strip():
            return True
        rate = getattr(getattr(piper_voice, "config", None), "sample_rate", 22050)
        with sd_mod.OutputStream(samplerate=rate, channels=1, dtype="int16") as stream:
            for chunk in piper_voice.synthesize(text):
                if stop_event.is_set():
                    break
                data = np_mod.frombuffer(chunk.audio_int16_bytes, dtype=np_mod.int16)
                if data.size:
                    level = float(np_mod.abs(data).mean()) / 6000.0
                    self._amp_hist.append(max(0.0, min(1.0, level)))
                    stream.write(data)
        return True

    def _tts_worker(self, text, voice):
        stop_event = self._tts_stop
        self.from_engine.put({"_kind": "speech_start"})
        handled = False
        try:
            handled = self._piper_play(text, voice, stop_event)
        except Exception:
            handled = False
        if not handled:
            speak_blocking(text, voice, stop_event=stop_event)
        self._amp_hist.append(-1.0)
        self.from_engine.put({"_kind": "speech_end"})
    # =============================================================== UI LOOP
    def _poll_engine(self):
        if self._closing:
            return
        try:
            while True:
                self._handle_message(self.from_engine.get_nowait())
        except queue.Empty:
            pass
        if not self._closing:
            self.after(55, self._poll_engine)

    def _handle_message(self, msg):
        kind = msg.get("_kind")
        try:
            if kind == "engine_ready":
                self._on_engine_ready()
            elif kind == "user":
                self._add_message("user", msg.get("text", ""))
                self.process_lbl.configure(text="Heard: %s" %
                                           shorten(msg.get("text", ""), 70))
            elif kind == "ai":
                self._on_ai_message(msg)
            elif kind == "status":
                self.set_state(msg.get("state", "READY"))
            elif kind == "intent":
                self.process_lbl.configure(text=msg.get("text", ""))
            elif kind == "tool_start":
                self._on_tool_start(msg)
            elif kind == "tool_done":
                self.process_lbl.configure(text="Tool: %s \u2192 %s" % (
                    msg.get("name", "tool"),
                    shorten(msg.get("text", ""), 60)))
            elif kind == "voice_switch":
                self.current_voice = msg.get("voice", self.current_voice)
            elif kind == "speech_start":
                self._speaking = True
                self.set_state("SPEAKING")
            elif kind == "speech_end":
                self._on_speech_end()
            elif kind == "voice_result":
                self._on_voice_result(msg)
            elif kind == "sysinfo":
                self._on_sysinfo(msg.get("info") or {})
            elif kind == "error":
                self.process_lbl.configure(text="Error: %s" %
                                           shorten(msg.get("text", ""), 70))
                self.set_state("ERROR")
        except Exception as exc:
            try:
                self.process_lbl.configure(text="UI error: %s" % exc)
            except Exception:
                pass

    def _on_ai_message(self, msg):
        self._busy = False
        text = msg.get("text", "")
        self.msg_count += 1
        self._add_message("ai", text, tool=msg.get("tool"), voice=msg.get("voice"))
        self.process_lbl.configure(text="Spoke reply (%d ms)" % msg.get("ms", 0))
        if not self.tts_enabled:
            self.set_state("READY")

    def _on_tool_start(self, msg):
        name = msg.get("name", "tool")
        args = msg.get("args") or {}
        detail = ", ".join("%s=%s" % (k, shorten(v, 24))
                           for k, v in list(args.items())[:4]) \
            if isinstance(args, dict) else shorten(args, 50)
        self.set_state("BUSY", "Executing %s" % name.replace("_", " "))
        self.process_lbl.configure(text="Running %s(%s)" % (name, detail))

    def _on_speech_end(self):
        self._speaking = False
        self.set_state("READY")
        if self.handsfree and not self._busy and not self._capturing:
            self._schedule_handsfree(900)

    def _on_voice_result(self, msg):
        self._capturing = False
        self.mic_ind.configure(text="\u25cf MIC OFF", text_color=TEXT_MUTE)
        if msg.get("token") != self._capture_token:
            return
        text = (msg.get("text") or "").strip()
        if text:
            self.process_lbl.configure(text="Heard: %s" % shorten(text, 70))
            self.dispatch(text)
        else:
            self.set_state("READY", "No speech detected — try again")
            if self.handsfree:
                self._schedule_handsfree(1400)

    def _on_sysinfo(self, info):
        def as_pct(v):
            try:
                return float(str(v).replace("%", "").strip().split()[0])
            except Exception:
                return 0.0
        cpu, mem, disk = as_pct(info.get("cpu_usage")), as_pct(info.get("memory")), \
            as_pct(info.get("disk_usage"))
        self._cpu_hist.append(cpu)
        self._mem_hist.append(mem)
    def set_state(self, state, note=None):
        if state not in STATES:
            state = "READY"
        self.status = state
        colour, caption, _speed = STATES[state]
        try:
            self.state_chip.configure(text="\u25cf %s" % state, text_color=colour)
            self.process_lbl.configure(text=note or caption, text_color=TEXT)
            self.core.set_state(state)
        except Exception:
            pass
        try:
            if state == "LISTENING":
                self.mic_ind.configure(text="\u25cf LISTENING", text_color=GREEN)
            elif state == "SPEAKING":
                self.mic_ind.configure(text="\u25cf SPEAKING", text_color=CYAN)
            elif state == "THINKING" or state == "BUSY":
                self.mic_ind.configure(text="\u25cf PROCESSING", text_color=AMBER)
            else:
                self.mic_ind.configure(text="\u25cf MIC OFF", text_color=TEXT_MUTE)
        except Exception:
            pass
        if state == "THINKING":
            self._busy = True
        if state in ("READY", "ERROR", "OFFLINE"):
            self._busy = False

    def _sync_voice_ui(self, reason=None):
        label = PERSONA_LABEL.get(self.current_voice, "JARVIS")

    def _schedule_handsfree(self, delay=900):
        if self._handsfree_job:
            try:
                self.after_cancel(self._handsfree_job)
            except Exception:
                pass
        self._handsfree_job = self.after(delay, self._handsfree_tick)

    def _handsfree_tick(self):
        self._handsfree_job = None
        if self._closing or not self.handsfree:
            return
        if self._busy or self._speaking or self._capturing:
            return
        self.start_voice()

    def _tick_clock(self):
        if self._closing:
            return
        self.after(1000, self._tick_clock)

    # ------------------------------------------------------------- animation
    def _animate(self):
        if self._closing:
            return
        now = time.time()
        dt = min(0.12, max(0.001, now - self._last_frame))
        self._last_frame = now
        try:
            self.core.tick(dt, self._current_amp())
        except Exception:
            pass
        self.after(33, self._animate)

    def _current_amp(self):
        if self.status == "SPEAKING":
            recent = [v for v in list(self._amp_hist)[-8:] if v >= 0]
            base = max(recent) if recent else 0.14
            return min(1.0, 0.24 + base * 0.9)
        return 0.05 + 0.03 * (0.5 + 0.5 * math.sin(time.time() * 1.4))
    # ============================================================== ACTIONS
    def dispatch(self, text):
        text = (text or "").strip()
        if not text:
            return
        self._busy = True
        self.set_state("THINKING")
        self.to_engine.put({"_kind": "chat", "text": text})

    def send_input(self):
        # Kept for compatibility; typed input uses the same dispatch path.
        pass

    def start_voice(self):
        if not VOICE_INPUT:
            self.process_lbl.configure(text="Microphone unavailable")
            self.set_state("ERROR")
            return
        if self._capturing:
            return
        if self._speaking:
            self.stop_speaking()
        self._capture_token += 1
        self._capturing = True
        self.set_state("LISTENING", "Listening — speak now")
        self.mic_ind.configure(text="\u25cf LISTENING", text_color=GREEN)
        self.to_engine.put({"_kind": "voice_capture", "token": self._capture_token})

    def stop_speaking(self):
        if self._speaking or self.status == "SPEAKING":
            self._tts_stop.set()
        elif self._capturing:
            self._capture_token += 1
            self._capturing = False
            self.set_state("READY", "Capture cancelled")

    def toggle_mute(self):
        self.tts_enabled = not self.tts_enabled
        if not self.tts_enabled and self._speaking:
            self._tts_stop.set()

    def toggle_handsfree(self):
        self.handsfree = not self.handsfree
        try:
            self.hf_btn.configure(image=make_icon("broadcast",
                                CYAN if self.handsfree else TEXT_MUTE, 15, 1.8))
        except Exception:
            pass
        if self.handsfree and not (self._busy or self._speaking or self._capturing):
            self._schedule_handsfree(600)
        elif not self.handsfree and self._handsfree_job:
            try:
                self.after_cancel(self._handsfree_job)
            except Exception:
                pass
            self._handsfree_job = None
    def _add_message(self, role, text, tool=None, voice=None):
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        accent = {"user": GOLD, "ai": CYAN, "notice": HAIRLINE_2}.get(role, HAIRLINE_2)
        card = ctk.CTkFrame(self.tr_inner, fg_color=PANEL_2, corner_radius=8,
                            border_width=1, border_color=HAIRLINE)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(card, fg_color=accent, width=3, corner_radius=2).grid(
            row=0, column=0, rowspan=2, sticky="ns")
        head = ctk.CTkFrame(card, fg_color=PANEL_2, corner_radius=0)
        head.grid(row=0, column=1, sticky="ew", padx=(10, 10), pady=(7, 0))
        head.grid_columnconfigure(1, weight=1)
        name = "YOU" if role == "user" else ("JARVIS" if role == "ai" else "EVENT")
        ctk.CTkLabel(head, text=name, font=(MONO, 9, "bold"),
                     text_color=accent).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text=stamp, font=(MONO, 8),
                     text_color=TEXT_MUTE).grid(row=0, column=1, sticky="e")
        body = ctk.CTkLabel(card, text=text, font=(UI, 10),
                            text_color=TEXT_DIM if role == "notice" else TEXT,
                            wraplength=520, justify="left", anchor="w")
        body.grid(row=1, column=1, sticky="w", padx=(10, 12), pady=(4, 7))
        self.tr_row += 1
        card.grid(row=self.tr_row, column=0, sticky="ew", pady=3)
        self._wrap_labels.append(body)
        self.after(40, lambda: self.tr_canvas.yview_moveto(1.0))
        if self.tr_row > 14:
            try:
                oldest = self.tr_inner.winfo_children()[0]
                oldest.destroy()
            except Exception:
                pass
        return card

    def _toast(self, text):
        if self._closing:
            return
        try:
            if self._toast_widget is not None:
                self._toast_widget.destroy()
        except Exception:
            pass
        try:
            w = ctk.CTkLabel(self, text=text, font=(MONO, 9, "bold"),
                             text_color=BG, fg_color=CYAN, corner_radius=10,
                             padx=14, pady=6)
            w.place(relx=0.5, rely=0.05, anchor="n")
            self._toast_widget = w
            self.after(2000, lambda: self._clear_toast(w))
        except Exception:
            pass

    def _clear_toast(self, widget):
        try:
            widget.destroy()
        except Exception:
            pass
        if self._toast_widget is widget:
            self._toast_widget = None

    def _bind_keys(self):
        def consume(action):
            def handler(event=None):
                try:
                    action()
                except Exception:
                    pass
                return "break"
            return handler
        bindings = {"<Escape>": self.stop_speaking,
                    "<Control-m>": self.toggle_mute, "<Control-M>": self.toggle_mute,
                    "<Control-Shift-V>": self.start_voice,
                    "<Control-Shift-v>": self.start_voice}
        for seq, action in bindings.items():
            try:
                self.bind(seq, consume(action), add="+")
            except Exception:
                pass

    def _on_close(self):
        self._closing = True
        self.handsfree = False
        try:
            if self._loading_job:
                self.after_cancel(self._loading_job)
            if self._boot_poll_job:
                self.after_cancel(self._boot_poll_job)
            if self._bg_job:
                self.after_cancel(self._bg_job)
            if self._handsfree_job:
                self.after_cancel(self._handsfree_job)
        except Exception:
            pass
        try:
            self._tts_stop.set()
        except Exception:
            pass
        try:
            self.to_engine.put({"_kind": "shutdown"})
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _on_engine_ready(self):
        self._engine_ready = True
        try:
            self.set_state("READY", "Standing by")
            self.process_lbl.configure(text="System online — Jarvis is listening")
            self.brand.configure(text="J.A.R.V.I.S. \u00b7 Online")
            self._toast("J.A.R.V.I.S. ready")
        except Exception:
            pass
        # Auto-start hands-free listening once the engine is ready.
        if self.handsfree and VOICE_INPUT and not self._capturing:
            self._schedule_handsfree(600)
        # Boot -> main interface: tear down loading screen, start video background.
        self._finish_boot()


def main():
    try:
        app = JarvisHUD()
    except Exception as exc:
        print("FATAL: the interface could not start: %s" % exc)
        import traceback
        traceback.print_exc()
        return
    try:
        app.mainloop()
    except KeyboardInterrupt:
        try:
            app._on_close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
