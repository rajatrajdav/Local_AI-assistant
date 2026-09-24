#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. — ARC INTERFACE
================================================================================
An immersive, single-surface desktop interface for the J.A.R.V.I.S. local AI
assistant (`jarvis.py`). It is deliberately **not** a metrics dashboard: the
assistant itself is the interface. Everything the engine can do is reachable
from one composed screen built around a live Arc-Reactor presence object.

    ┌─────────────────────────────────────────────────────────────────────────┐
    │  ◉ J.A.R.V.I.S      session readout          ● ENGINE  21:09:52  Monday │
    ├────┬──────────────────────────┬─────────────────────────────────────────┤
    │ ▣  │                          │   CONVERSATION                          │
    │ ◈  │      ARC REACTOR         │   ── message cards w/ inline tool chips │
    │ ∿  │   (state-reactive)       │   ── typing indicator, timestamps       │
    │ ⌸  │   ◢ live waveform ◣      │                                         │
    │ ◎  │   caption / utterance    │                                         │
    │ ⓘ  │   ⏺ mic   ⏹ stop  ⇄ HF  │                                         │
    │    │   quick intents          │                                         │
    │    │   telemetry hairline     │                                         │
    ├────┴──────────────────────────┴─────────────────────────────────────────┤
    │  ▸  compose a command …                              ⏺ mic   ➤ dispatch  │
    ├─────────────────────────────────────────────────────────────────────────┤
    │  ● ENGINE ONLINE · executing create_presentation · 12 msgs · 3 tools     │
    └─────────────────────────────────────────────────────────────────────────┘

Behaviour mirrors `jarvis.py` → `chat_with_voice_assistant()` exactly:
  wake-word strip → exit words → detect_target_personality / detect_lang voice
  routing → process_user_input → LLM voice_preference switch → execute_function
  → history append → Piper TTS (`play_piper_tts`, interruption-aware).

Highlights
  • Hand-drawn vector icon set (PIL supersampled) — no emoji fonts required.
  • Real-time Arc-Reactor animation that reacts to state and to actual TTS
    amplitude measured per audio chunk.
  • True speech interruption: the Stop control sets the Piper stop-event.
  • Hands-free mode: after J.A.R.V.I.S. finishes speaking it re-arms the mic.
  • Conversation export, generated-file browser, live activity timeline,
    full capability catalogue and system/provider diagnostics.
  • Boot shutter with optional `jarvis/Loading.mp4` viewport while the heavy
    engine (Piper voices + LLM clients) loads on a background thread.

Run with:
    python jarvis_interface.py        (or double-click run_interface.bat)
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --------------------------------------------------------------------------
# Dependency self-heal (customtkinter + Pillow) — mirrors jarvis_gui.py
# --------------------------------------------------------------------------
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
except Exception as _pil_exc:                                     # pragma: no cover
    PIL_OK = False
    print("  ! Pillow unavailable (%s) — falling back to text glyphs." % _pil_exc)

if PIL_OK:
    _resampling = getattr(Image, "Resampling", Image)
    RESAMPLE_LANCZOS = getattr(_resampling, "LANCZOS", 1)
    RESAMPLE_BILINEAR = getattr(_resampling, "BILINEAR", 2)
else:
    RESAMPLE_LANCZOS = 1
    RESAMPLE_BILINEAR = 2



# ==========================================================================
# THEME — deep-space navy with arc-reactor cyan + gold core
# ==========================================================================
BG          = "#04060B"   # app backdrop
BG_1        = "#070A12"
SURFACE     = "#0A0F1A"   # primary panels
SURFACE_2   = "#0D1421"   # raised panels / cards
SURFACE_3   = "#121B2C"   # hover / chips
HAIRLINE    = "#16203A"   # 1px dividers
HAIRLINE_2  = "#1E2B49"
CYAN        = "#35E4F5"   # primary accent
CYAN_DIM    = "#1D8CA3"
BLUE        = "#4B8DF8"
GOLD        = "#F5C24B"   # arc-reactor core
GREEN       = "#3EE0A1"
AMBER       = "#F2A33C"
RED         = "#FF5D73"
TEXT        = "#E8F2FF"
TEXT_DIM    = "#95A8C4"
TEXT_MUTE   = "#5C6D8B"

DISPLAY = "Bahnschrift"        # wordmark / section headers (HUD character)
UI      = "Segoe UI"           # body copy
MONO    = "Cascadia Mono"      # telemetry / code / timestamps

# status -> (dot colour, reactor hue, caption, spin speed)
STATES = {
    "BOOT":      (CYAN,  CYAN,  "Initialising systems",            2.6),
    "READY":     (GREEN, CYAN,  "Standing by for your command",    0.35),
    "LISTENING": (GREEN, GREEN, "Listening \u2014 speak now",       1.9),
    "THINKING":  (AMBER, AMBER, "Reasoning over your request",     3.4),
    "BUSY":      (AMBER, AMBER, "Executing a tool",                3.0),
    "SPEAKING":  (CYAN,  GOLD,  "Speaking",                        1.3),
    "OFFLINE":   (RED,   RED,   "Engine offline \u2014 demo mode",  0.2),
    "ERROR":     (RED,   RED,   "Recovered from an error",         0.2),
}

EXIT_WORDS = {"exit", "quit", "bye", "goodbye", "shutdown", "stop"}

PERSONA_LABEL = {
    "en_male":   "JARVIS \u2014 ENGLISH",
    "hi_male":   "JARVIS \u2014 HINDI",
    "en_female": "SIMMI \u2014 ENGLISH",
}

REPO_URL = "https://github.com/rajatrajdav/Local_AI-assistant"
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_files")


# ---------------------------------------------------------------- engine API
_engine = None
ENGINE_OK = False
ENGINE_ERR = "Engine has not been loaded yet."
ENGINE_LOAD_MS = 0
VOICES = {
    "en_male":   {"name": "English Male (Medium)",             "language": "en"},
    "hi_male":   {"name": "Hindi Male (Pratham \u2014 hi_IN)", "language": "hi"},
    "en_female": {"name": "English Female (LibriTTS)",         "language": "en"},
}
PERSONALITIES = {}
FUNCTION_MAP = {}
process_user_input = None
execute_function = None
get_system_info = None
detect_target_personality = None
detect_lang = None
get_personality = None
detect_wake_word = None
strip_wake_word = None
listen_natural_fn = None
VOICE_INPUT = False
SR_ERROR = ""

ENGLISH_ONLY_NOTE = ("Voice input needs SpeechRecognition + sounddevice "
                     "and a working microphone.")


def engine_get(name, default=None):
    """Defensive attribute read from the loaded jarvis module."""
    if _engine is None:
        return default
    return getattr(_engine, name, default)


def _load_engine():
    """Import the heavy jarvis.py engine. Called from a background thread."""
    global _engine, ENGINE_OK, ENGINE_ERR, ENGINE_LOAD_MS
    global VOICES, PERSONALITIES, FUNCTION_MAP, OUTPUT_DIR
    global process_user_input, execute_function, get_system_info
    global detect_target_personality, detect_lang, get_personality
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
        get_personality = getattr(_mod, "get_personality", None)
        detect_wake_word = getattr(_mod, "detect_wake_word", None)
        strip_wake_word = getattr(_mod, "strip_wake_word", None)
        listen_natural_fn = getattr(_mod, "listen_natural", None)
        ENGINE_OK = True
        ENGINE_ERR = ""
    except BaseException as exc:                     # jarvis.py may sys.exit()
        ENGINE_OK = False
        ENGINE_ERR = "%s: %s" % (type(exc).__name__, exc)

    try:
        import speech_recognition          # noqa: F401  (availability probe)
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
    """Last-resort TTS path: reuse the engine's own Piper player."""
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
# Colour + text helpers
# ==========================================================================
def _rgb(hex_colour):
    hex_colour = hex_colour.lstrip("#")
    return tuple(int(hex_colour[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % (max(0, min(255, int(rgb[0]))),
                              max(0, min(255, int(rgb[1]))),
                              max(0, min(255, int(rgb[2]))))


def mix(colour_a, colour_b, t):
    """Blend two hex colours. t=0 -> a, t=1 -> b."""
    t = max(0.0, min(1.0, t))
    a, b = _rgb(colour_a), _rgb(colour_b)
    return _hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def fade(colour, t):
    """Fade a colour towards the app backdrop (used for glows / ripples)."""
    return mix(BG, colour, t)


def hms(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def human_size(num_bytes):
    step = 1024.0
    num_bytes = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < step or unit == "TB":
            return ("%d B" % num_bytes) if unit == "B" else \
                ("%.1f %s" % (num_bytes, unit))
        num_bytes /= step


def shorten(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


# ==========================================================================
# ICON ENGINE — bespoke stroked vector icons, supersampled for smoothness
# ==========================================================================
_ICON_CACHE = {}


def _draw_icon(d, kind, S, colour, w):
    """Draw a stroked icon on a 0..100 design grid scaled to S pixels."""

    def pts(*coords):
        return [(S * x / 100.0, S * y / 100.0) for x, y in coords]

    def line(*coords, width=None):
        d.line(pts(*coords), fill=colour, width=width or w, joint="curve")

    def box(x0, y0, x1, y1, radius=0, width=None, fill=False):
        rect = [S * x0 / 100.0, S * y0 / 100.0, S * x1 / 100.0, S * y1 / 100.0]
        r = S * radius / 100.0
        if fill:
            d.rounded_rectangle(rect, radius=r, fill=colour)
        else:
            d.rounded_rectangle(rect, radius=r, outline=colour,
                                width=width or w)

    def circ(cx, cy, r, width=None, fill=False):
        rect = [S * (cx - r) / 100.0, S * (cy - r) / 100.0,
                S * (cx + r) / 100.0, S * (cy + r) / 100.0]
        if fill:
            d.ellipse(rect, fill=colour)
        else:
            d.ellipse(rect, outline=colour, width=width or w)

    def arc(cx, cy, r, start, end, width=None):
        rect = [S * (cx - r) / 100.0, S * (cy - r) / 100.0,
                S * (cx + r) / 100.0, S * (cy + r) / 100.0]
        d.arc(rect, start=start, end=end, fill=colour, width=width or w)

    def poly(*coords, fill=False):
        if fill:
            d.polygon(pts(*coords), fill=colour)
        else:
            d.polygon(pts(*coords), outline=colour)

    if kind == "chat":
        box(12, 16, 88, 66, radius=15)
        line((30, 66), (30, 86), (50, 66))
        for cx in (36, 50, 64):
            circ(cx, 41, 4, fill=True)

    elif kind == "layers":
        box(12, 12, 46, 46, radius=7)
        box(54, 12, 88, 46, radius=7)
        box(12, 54, 46, 88, radius=7)
        box(54, 54, 88, 88, radius=7)

    elif kind == "pulse":
        line((8, 58), (28, 58), (38, 24), (50, 80), (62, 38), (72, 58), (92, 58))

    elif kind == "folder":
        box(8, 26, 92, 86, radius=9)
        line((8, 26), (8, 18), (36, 18), (46, 26))

    elif kind == "gauge":
        arc(50, 62, 33, 160, 380)
        line((50, 62), (74, 36))
        circ(50, 62, 3, fill=True)

    elif kind == "info":
        circ(50, 50, 37)
        circ(50, 32, 3.6, fill=True)
        line((50, 44), (50, 70))

    elif kind == "mic":
        box(36, 10, 64, 56, radius=14)
        arc(50, 44, 27, 6, 174)
        line((50, 71), (50, 86))
        line((35, 86), (65, 86))

    elif kind == "stop":
        box(27, 27, 73, 73, radius=7, fill=True)

    elif kind == "send":
        poly((10, 50), (90, 12), (58, 90), (46, 58))
        line((46, 58), (90, 12), width=max(1, w - 1))

    elif kind == "broadcast":
        circ(50, 66, 7, fill=True)
        arc(50, 66, 24, 195, 345)
        arc(50, 66, 40, 205, 335)

    elif kind == "speaker":
        poly((16, 38), (34, 38), (56, 18), (56, 82), (34, 62), (16, 62))
        arc(50, 50, 20, 300, 60)

    elif kind == "mute":
        poly((14, 38), (32, 38), (54, 18), (54, 82), (32, 62), (14, 62))
        line((68, 38), (90, 62))
        line((90, 38), (68, 62))

    elif kind == "export":
        line((50, 74), (50, 16))
        line((33, 33), (50, 16), (67, 33))
        line((20, 58), (20, 86), (80, 86), (80, 58))

    elif kind == "refresh":
        arc(50, 50, 33, 34, 326)
        poly((82, 30), (66, 30), (78, 46), fill=True)

    elif kind == "trash":
        line((20, 28), (80, 28))
        line((39, 28), (39, 14), (61, 14), (61, 28))
        line((29, 28), (36, 88), (64, 88), (71, 28))
        line((43, 40), (46, 76))
        line((57, 40), (54, 76))

    elif kind == "clock":
        circ(50, 50, 36)
        line((50, 50), (50, 27))
        line((50, 50), (68, 60))

    elif kind == "chip":
        box(26, 26, 74, 74, radius=6)
        box(41, 41, 59, 59, radius=3)
        for c in (34, 50, 66):
            line((c, 12), (c, 26))
            line((c, 74), (c, 88))
            line((12, c), (26, c))
            line((74, c), (88, c))

    elif kind == "power":
        arc(50, 50, 30, 300, 60)
        line((50, 14), (50, 52))

    elif kind == "terminal":
        box(8, 16, 92, 84, radius=8)
        line((24, 34), (40, 50), (24, 66))
        line((50, 66), (74, 66))

    elif kind == "close":
        line((26, 26), (74, 74))
        line((74, 26), (26, 74))

    elif kind == "core":                      # wordmark glyph / arc reactor
        circ(50, 50, 36)
        circ(50, 50, 23)
        circ(50, 50, 11, fill=True)
        for i in range(8):
            ang = math.radians(i * 45)
            line((50 + 27 * math.cos(ang), 50 + 27 * math.sin(ang)),
                 (50 + 34 * math.cos(ang), 50 + 34 * math.sin(ang)))

    elif kind == "eye":
        poly((10, 50), (32, 30), (68, 30), (90, 50), (68, 70), (32, 70))
        circ(50, 50, 9)


def make_icon(kind, colour, size=22, stroke=1.9):
    """Cached CTkImage for the given icon. None when Pillow is missing."""
    if not PIL_OK:
        return None
    key = (kind, colour, size, stroke)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    scale = 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        _draw_icon(draw, kind, S, _rgb(colour), max(1, int(round(stroke * scale))))
    except Exception:
        pass
    img = img.resize((size, size), RESAMPLE_LANCZOS)
    icon = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = icon
    return icon


def text_colour(hue):
    """Readable foreground derived from a hue."""
    return mix(hue, TEXT, 0.45)


# ==========================================================================
# WIDGET — Arc Reactor (state-reactive, amplitude-reactive)
# ==========================================================================
class ReactorCanvas(tk.Canvas):
    """The visual centre of the interface: a live Arc Reactor.

    Reacts to interface state (idle / listening / thinking / speaking) and to
    the real TTS amplitude measured per audio chunk by the speech worker.
    """

    def __init__(self, master, size=380, **kwargs):
        super().__init__(master, width=size, height=size, bg=SURFACE,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.size = size
        self.state = "BOOT"
        self.hue = CYAN
        self.amp = 0.0
        self.spin = 0.0
        self.spin_speed = 0.35
        self.phase = 0.0
        self.ripples = []
        self.levels = deque([0.0] * 72, maxlen=72)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.size = max(150, min(event.width, event.height))

    def set_state(self, state):
        info = STATES.get(state, STATES["READY"])
        self.hue = info[1]
        self.spin_speed = info[3]
        self.state = state
        for i in range(len(self.ripples)):
            self.ripples[i] += 0.0

    def push_ripple(self):
        if len(self.ripples) < 4:
            self.ripples.append(0.0)

    def tick(self, dt, amp):
        self.amp += (amp - self.amp) * 0.45
        self.spin = (self.spin + self.spin_speed * dt * 60.0) % 360.0
        self.phase += dt
        for i in range(len(self.ripples)):
            self.ripples[i] += dt * 1.05
        self.ripples = [r for r in self.ripples if r < 1.0]
        self.levels.append(amp)
        self._redraw(amp)

    # ------------------------------------------------------------------
    def _redraw(self, amp):
        try:
            self.delete("fx")
        except tk.TclError:
            return
        S = self.size
        if S < 60:
            return
        cx = cy = S / 2.0
        R = S * 0.43
        hue = self.hue
        state = self.state
        spin = self.spin
        self._frame(cx, cy, R * 1.04)              # HUD corner brackets

        # outer hairline ring + rotating bracket arcs
        self.create_oval(cx - R, cy - R, cx + R, cy + R,
                         outline=HAIRLINE_2, width=1, tags="fx")
        for i in range(4):
            start = (spin * 0.25 + i * 90) % 360
            self.create_arc(cx - R, cy - R, cx + R, cy + R,
                            start=start, extent=26, style="arc",
                            outline=mix(HAIRLINE_2, hue, 0.8), width=2, tags="fx")

        # rotating tick ring — a brightness sweep travels around the ring
        for i in range(72):
            ang = math.radians(i * 5 + spin * 1.1)
            bright = 0.10 + 0.90 * max(0.0, math.cos(ang - math.radians(spin)))
            r0, r1 = R - 26, R - 14
            self.create_line(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang),
                             cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                             fill=mix(HAIRLINE, hue, bright), width=1, tags="fx")

        # segmented arc ring
        r_seg = R - 40
        for i in range(3):
            start = (spin * 1.6 + i * 120) % 360
            self.create_arc(cx - r_seg, cy - r_seg, cx + r_seg, cy + r_seg,
                            start=start, extent=64, style="arc",
                            outline=mix(SURFACE_2, hue, 0.9), width=3, tags="fx")

        # expanding ripples while listening
        for t in self.ripples:
            r = r_seg * (0.55 + t * 0.45)
            self.create_oval(cx - r, cy - r, cx + r, cy + r,
                             outline=mix(BG, hue, 1.0 - t), width=1, tags="fx")

        # rotor blades (counter-rotating)
        r_in, r_out = R - 92, R - 68
        for i in range(12):
            ang = math.radians(i * 30 - spin * 0.9)
            self.create_line(cx + r_in * math.cos(ang), cy + r_in * math.sin(ang),
                             cx + r_out * math.cos(ang), cy + r_out * math.sin(ang),
                             fill=mix(SURFACE_2, hue, 0.42), width=2, tags="fx")

        # inner ring + gate marks
        r_in2 = R - 96
        self.create_oval(cx - r_in2, cy - r_in2, cx + r_in2, cy + r_in2,
                         outline=HAIRLINE, width=1, tags="fx")
        for i in range(6):
            ang = math.radians(i * 60 + spin * 1.6)
            gx = cx + (r_in2 + 7) * math.cos(ang)
            gy = cy + (r_in2 + 7) * math.sin(ang)
            self.create_rectangle(gx - 2, gy - 2, gx + 2, gy + 2,
                                  fill=mix(HAIRLINE_2, hue, 0.6),
                                  outline="", tags="fx")

        # speaking: radial waveform ring driven by real TTS amplitude
        if state == "SPEAKING":
            base_r = R - 62
            vals = list(self.levels)
            n = max(1, len(vals))
            for i in range(0, n, 2):
                ang = math.radians(i * (360.0 / n) - spin * 0.6)
                level = vals[i]
                length = 6 + level * 48
                self.create_line(cx + base_r * math.cos(ang),
                                 cy + base_r * math.sin(ang),
                                 cx + (base_r + length) * math.cos(ang),
                                 cy + (base_r + length) * math.sin(ang),
                                 fill=mix(CYAN_DIM, hue, min(1.0, 0.3 + level)),
                                 width=2, tags="fx")

        # glow stack + reactor core
        core_r = 13 + amp * 12
        for i, gr in enumerate((52, 44, 37, 31, 26, 22)):
            bright = 0.10 + 0.30 * (i / 5.0) + amp * 0.30
            self.create_oval(cx - gr, cy - gr, cx + gr, cy + gr,
                             outline=fade(hue, bright), width=1, tags="fx")
        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r,
                         outline=mix(hue, GOLD, 0.5), width=2, tags="fx")
        inner = core_r * 0.55
        self.create_oval(cx - inner, cy - inner, cx + inner, cy + inner,
                         fill=mix(GOLD, hue, 0.25), outline="", tags="fx")
        dot = max(2.0, inner * 0.45)
        self.create_oval(cx - dot, cy - dot, cx + dot, cy + dot,
                         fill="#FFF7E4", outline="", tags="fx")

    def _frame(self, cx, cy, r):
        """Four HUD corner brackets."""
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x, y = cx + sx * r, cy + sy * r
            self.create_line(x, y, x - sx * 18, y,
                             fill=HAIRLINE_2, width=1, tags="fx")
            self.create_line(x, y, x, y - sy * 18,
                             fill=HAIRLINE_2, width=1, tags="fx")


# ==========================================================================
# WIDGET — Live audio ribbon
# ==========================================================================
class WaveCanvas(tk.Canvas):
    """Real TTS amplitude while speaking, breathing motion while idle."""

    def __init__(self, master, height=58, bars=64, **kwargs):
        super().__init__(master, height=height, bg=SURFACE,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.bars = bars
        self.levels = [0.0] * bars
        self.hue = CYAN
        self.state = "READY"
        self.phase = 0.0
        self.w = 10
        self.h = height
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.w, self.h = max(10, event.width), max(10, event.height)

    def set_state(self, state):
        self.hue = STATES.get(state, STATES["READY"])[1]
        self.state = state

    def tick(self, dt, levels=None):
        self.phase += dt
        n = self.bars
        hist = list(levels) if levels else []
        for i in range(n):
            if self.state == "SPEAKING":
                if hist:
                    v = hist[int(i * len(hist) / float(n)) % len(hist)]
                else:
                    v = 0.28 + 0.22 * math.sin(self.phase * 9.0 + i * 0.6)
                env = 0.5 + 0.5 * math.sin(math.pi * i / float(n))
                target = min(1.0, v * (0.55 + 0.75 * env))
            elif self.state == "LISTENING":
                target = 0.08 + 0.34 * abs(math.sin(self.phase * 2.2 - i * 0.28))
            else:
                target = 0.045 + 0.05 * (0.5 + 0.5 * math.sin(
                    self.phase * 1.3 + i * 0.22))
            self.levels[i] += (target - self.levels[i]) * 0.4
        self._redraw()

    def _redraw(self):
        try:
            self.delete("fx")
        except tk.TclError:
            return
        w, h = self.w, self.h
        if w < 20 or h < 10:
            return
        cy = h / 2.0
        bw = w / float(self.bars)
        self.create_line(0, cy, w, cy, fill=HAIRLINE, width=1, tags="fx")
        for i, lv in enumerate(self.levels):
            x = i * bw + bw * 0.2
            half = max(1.0, lv * h * 0.46)
            colour = mix(HAIRLINE_2, self.hue, min(1.0, 0.18 + lv * 1.7))
            self.create_rectangle(x, cy - half, x + bw * 0.62, cy + half,
                                  fill=colour, outline="", tags="fx")


# ==========================================================================
# WIDGET — Sparkline (CPU / memory history)
# ==========================================================================
class Sparkline(tk.Canvas):
    """Two thin traces with a soft stipple fill — instrument, not dashboard."""

    def __init__(self, master, height=94, **kwargs):
        super().__init__(master, height=height, bg=SURFACE_2,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.w, self.h = 10, height
        self.cpu = []
        self.mem = []
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.w, self.h = max(10, event.width), max(10, event.height)
        self._redraw()

    def set_data(self, cpu, mem):
        self.cpu = list(cpu)[-120:]
        self.mem = list(mem)[-120:]
        self._redraw()

    def _redraw(self):
        try:
            self.delete("all")
        except tk.TclError:
            return
        w, h = self.w, self.h
        if w < 40 or h < 30:
            return
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = 6 + (h - 14) * frac
            self.create_line(0, y, w, y, fill=HAIRLINE, width=1)
        for series, colour in ((self.mem, BLUE), (self.cpu, CYAN)):
            if len(series) < 2:
                continue
            step = w / float(max(1, len(series) - 1))
            pts = []
            for i, value in enumerate(series):
                y = 6 + (h - 14) * (1.0 - max(0.0, min(1.0, value / 100.0)))
                pts.extend((i * step, y))
            self.create_polygon(pts + [w, h - 8, 0, h - 8],
                                fill=mix(SURFACE_2, colour, 0.35),
                                outline="", stipple="gray25")
            self.create_line(*pts, fill=colour, width=2, smooth=True)
            self.create_oval(pts[-2] - 3, pts[-1] - 3, pts[-2] + 3, pts[-1] + 3,
                             fill=colour, outline="")


# ==========================================================================
# WIDGET — Hairline percentage bar (slim telemetry)
# ==========================================================================
class HairlineBar(tk.Canvas):
    def __init__(self, master, width=118, height=6, **kwargs):
        super().__init__(master, width=width, height=height, bg=SURFACE,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.bw, self.bh = width, height
        self.pct = 0.0
        self.colour = CYAN
        self.bind("<Configure>", self._on_resize)
        self._redraw()

    def _on_resize(self, event):
        self.bw, self.bh = max(4, event.width), max(3, event.height)
        self._redraw()

    def set_value(self, pct, colour=None):
        self.pct = max(0.0, min(100.0, float(pct or 0.0)))
        if colour:
            self.colour = colour
        self._redraw()

    def _redraw(self):
        try:
            self.delete("all")
        except tk.TclError:
            return
        self.create_rectangle(0, 1, self.bw, self.bh - 1,
                              fill=HAIRLINE, outline="")
        fill_w = self.bw * self.pct / 100.0
        if fill_w > 0.5:
            self.create_rectangle(0, 1, fill_w, self.bh - 1,
                                  fill=self.colour, outline="")


# ==========================================================================
# CAPABILITY CATALOGUE — mirrors FUNCTION_MAP in jarvis.py
# ==========================================================================
CAPABILITY_GROUPS = (
    ("DOCUMENTS & CREATION", "writes real files into generated_files/", (
        ("tool", "create_word_document",
         "Builds a formatted .docx from a title and body content, with "
         "professional heading structure."),
        ("tool", "create_presentation",
         "Generates a .pptx slide deck \u2014 4-step professional engine, or the "
         "Pexels background-first creative engine when imagery is requested."),
        ("tool", "create_resume",
         "Produces a structured r\u00e9sum\u00e9 with contact details, experience, "
         "education and skills sections."),
        ("tool", "create_file",
         "Writes plain-text notes or any text payload straight into "
         "generated_files/."),
    )),
    ("SYSTEM CONTROL", "acts on this machine", (
        ("tool", "open_application",
         "Launches desktop applications and websites by name \u2014 Chrome, "
         "Notepad, Explorer, YouTube, and more."),
        ("tool", "execute_system_command",
         "Runs a CLI command and returns stdout; destructive commands such as "
         "format or shutdown are blocked."),
        ("tool", "list_running_processes",
         "Lists live processes, optionally filtered by name."),
        ("tool", "take_screenshot",
         "Captures the screen and stores a PNG inside generated_files/."),
        ("tool", "write_to_clipboard",
         "Copies arbitrary text to the system clipboard."),
    )),
    ("INTELLIGENCE & RESEARCH", "gathers and computes", (
        ("tool", "search_web",
         "DuckDuckGo search returning summarised top results for any topic."),
        ("tool", "search_files_on_computer",
         "Finds files by name or pattern anywhere beneath a directory."),
        ("tool", "read_file_content",
         "Reads a text file and returns its contents for analysis."),
        ("tool", "get_system_info",
         "Reports CPU, memory, disk, battery and GPU telemetry as structured "
         "data."),
        ("tool", "get_current_time",
         "Returns the current date and time."),
        ("tool", "calculate",
         "Evaluates mathematical expressions safely."),
    )),
    ("VOICE & PRESENCE", "how J.A.R.V.I.S. answers", (
        ("feature", "Piper neural speech",
         "Three offline voices \u2014 English male, English female (Simmi) and "
         "Hindi male \u2014 synthesised locally with no cloud audio."),
        ("feature", "Dual personality inference",
         "The engine detects whether you addressed JARVIS or Simmi and routes "
         "voice, tone and language automatically."),
        ("feature", "Bilingual routing",
         "Devanagari input switches the reply to the Hindi voice without any "
         "switch command."),
        ("feature", "Wake words & hands-free",
         "\u201cJarvis\u201d / \u201cSimmi\u201d activation plus a hands-free mode that re-arms "
         "the microphone after every reply."),
        ("feature", "Interruptible playback",
         "Speech stops between audio chunks the moment you interrupt."),
    )),
)


# ==========================================================================
# NAVIGATION MODEL
# ==========================================================================
RAIL_ITEMS = (
    ("conversation", "chat", "Conversation"),
    ("capabilities", "layers", "Capabilities"),
    ("activity", "pulse", "Activity"),
    ("deliverables", "folder", "Deliverables"),
    ("diagnostics", "gauge", "Diagnostics"),
    ("about", "info", "About"),
)

VIEW_TITLES = {
    "conversation": ("CONVERSATION", "Live transcript of this session"),
    "capabilities": ("CAPABILITIES", "Every function the assistant can call"),
    "activity": ("ACTIVITY", "Engine timeline \u2014 intents, tools, voice"),
    "deliverables": ("DELIVERABLES", "Files J.A.R.V.I.S. has produced"),
    "diagnostics": ("DIAGNOSTICS", "System, language models and voice stack"),
    "about": ("ABOUT", "Project overview and controls"),
}


# ==========================================================================
# THE APPLICATION
# ==========================================================================
class JarvisInterface(ctk.CTk):
    """ARC Interface — one composed surface: presence column + live workspace."""

    # -------------------------------------------------------------- bootstrap
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("J.A.R.V.I.S \u2014 Arc Interface")
        self.geometry("1380x880")
        self.minsize(1180, 748)
        self.configure(fg_color=BG)

        # ---- session state -------------------------------------------------
        self.conversation = []          # engine history: [{"role","content"}]
        self.current_voice = "en_male"
        self.tts_enabled = True
        self.handsfree = False
        self.status = "BOOT"
        self.activity = "Initialising"
        self.started = time.time()
        self.msg_count = 0
        self.tool_count = 0
        self.export_count = 0
        self.last_user_text = ""
        self.last_ai_text = ""
        self.sys_info = {}
        self.view = "conversation"

        self._busy = False
        self._speaking = False
        self._capturing = False
        self._typing = False
        self._closing = False
        self._engine_ready = False
        self._boot_t0 = time.time()
        self._last_frame = time.time()
        self._last_ripple = 0.0
        self._typing_phase = 0
        self._first_message_done = False

        self._tts_stop = threading.Event()
        self._amp_hist = deque([0.0] * 72, maxlen=72)
        self._cpu_hist = deque(maxlen=120)
        self._mem_hist = deque(maxlen=120)
        self._wrap_labels = []
        self._toast_widget = None
        self._boot_frames = []
        self._boot_fade = 1.0
        self._boot_pump_id = None
        self._boot_logs = []
        self._boot_steps_done = set()
        self._boot_closing = False
        self._boot_video_shown = False
        self._boot_video_index = 0
        self._boot_video_photo = None
        self._capture_token = 0
        self._thinking_since = 0.0
        self._handsfree_job = None
        self._poll_job = None
        self._anim_job = None
        self._clock_job = None
        self._boot_poll_job = None
        self._shutter_job = None
        self._toast_job = None
        self._voice_canvas = None

        self.to_engine = queue.Queue()
        self.from_engine = queue.Queue()

        # ---- typography ----------------------------------------------------
        self.f_word = (DISPLAY, 23, "bold")
        self.f_head = (DISPLAY, 13, "bold")
        self.f_small = (UI, 10)
        self.f_micro = (MONO, 8)
        self.f_mono = (MONO, 10)
        self.f_body = (UI, 12)
        self.f_body_dim = (UI, 11)
        self.f_chip = (MONO, 9, "bold")

        self._build_layout()
        threading.Thread(target=self._boot_engine, daemon=True).start()
        threading.Thread(target=self._engine_loop, daemon=True).start()
        threading.Thread(target=self._sysinfo_loop, daemon=True).start()

        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick_clock()
        self._poll_engine()
        self._animate()
        self._boot_poll_job = self.after(200, self._boot_poll)

    # ---------------------------------------------------------------- layout
    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_topbar().grid(row=0, column=0, sticky="ew")

        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=430)
        body.grid_columnconfigure(3, weight=1)

        self.rail = self._build_rail(body)
        self.rail.grid(row=0, column=0, sticky="nsw")

        self.presence = self._build_presence(body)
        self.presence.grid(row=0, column=1, sticky="nsw")

        ctk.CTkFrame(body, fg_color=HAIRLINE, width=1, corner_radius=0).grid(
            row=0, column=2, sticky="ns")

        self._build_workspace(body).grid(row=0, column=3, sticky="nsew")

        self._build_composer().grid(row=2, column=0, sticky="ew")
        self._build_ribbon().grid(row=3, column=0, sticky="ew")
        self._build_boot_overlay()

    # ---------------------------------------------------------------- top bar
    def _build_topbar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_1, corner_radius=0, height=68)
        bar.grid_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(bar, fg_color=BG_1, corner_radius=0)
        brand.grid(row=0, column=0, sticky="w", padx=(18, 8), pady=8)
        ctk.CTkLabel(brand, text="", image=make_icon("core", CYAN, 30, 1.8)).grid(
            row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(brand, text="J.A.R.V.I.S", font=self.f_word,
                     text_color=TEXT).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(brand, text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                     font=(MONO, 7), text_color=TEXT_MUTE).grid(
            row=1, column=1, sticky="w")

        readout = ctk.CTkFrame(bar, fg_color=BG_1, corner_radius=0)
        readout.grid(row=0, column=2, sticky="e", padx=10)
        self.session_labels = {}
        cells = (("session", "SESSION"), ("messages", "MESSAGES"),
                 ("tools", "TOOLS"), ("voice", "VOICE"))
        for i, (key, label) in enumerate(cells):
            cell = ctk.CTkFrame(readout, fg_color=BG_1, corner_radius=0)
            cell.grid(row=0, column=i, padx=11)
            value = ctk.CTkLabel(cell, text="\u2014", font=(MONO, 11, "bold"),
                                 text_color=TEXT)
            value.grid(row=0, column=0, sticky="e")
            ctk.CTkLabel(cell, text=label, font=(MONO, 7),
                         text_color=TEXT_MUTE).grid(row=0, column=1, sticky="w",
                                                    padx=(5, 0))
            self.session_labels[key] = value

        self.state_chip = ctk.CTkLabel(
            bar, text="\u25cf  BOOT", font=self.f_chip, text_color=CYAN,
            fg_color=SURFACE_2, corner_radius=999, padx=13, pady=6)
        self.state_chip.grid(row=0, column=3, sticky="e", padx=8)

        clock_box = ctk.CTkFrame(bar, fg_color=BG_1, corner_radius=0)
        clock_box.grid(row=0, column=4, sticky="e", padx=(4, 20))
        self.clock_label = ctk.CTkLabel(clock_box, text="--:--:--",
                                        font=(DISPLAY, 20, "bold"),
                                        text_color=TEXT)
        self.clock_label.grid(row=0, column=0, sticky="e")
        self.date_label = ctk.CTkLabel(clock_box, text="", font=(MONO, 8),
                                       text_color=TEXT_MUTE)
        self.date_label.grid(row=1, column=0, sticky="e")

        ctk.CTkFrame(bar, fg_color=HAIRLINE, height=1, corner_radius=0).place(
            in_=bar, relx=0, rely=1.0, relwidth=1.0, anchor="sw")
        return bar

    # --------------------------------------------------------------- icon rail
    def _build_rail(self, parent):
        rail = ctk.CTkFrame(parent, fg_color=BG_1, corner_radius=0, width=86)
        rail.grid_propagate(False)
        rail.grid_columnconfigure(0, weight=1)
        rail.grid_rowconfigure(len(RAIL_ITEMS) + 1, weight=1)

        ctk.CTkLabel(rail, text="", image=make_icon("terminal", CYAN_DIM, 17, 1.6)).grid(
            row=0, column=0, pady=(18, 14))

        self.rail_buttons = {}
        for i, (key, kind, label) in enumerate(RAIL_ITEMS):
            icon_off = make_icon(kind, TEXT_MUTE, 22, 1.9)
            icon_on = make_icon(kind, CYAN, 22, 2.1)
            button = ctk.CTkButton(rail, text="", image=icon_off, width=56,
                                   height=52, corner_radius=16,
                                   fg_color="transparent", hover_color=SURFACE_2,
                                   command=lambda k=key: self.show_view(k))
            button.grid(row=i + 1, column=0, pady=5)
            button.bind("<Enter>", lambda e, l=label: self.set_activity(
                "%s view" % l))
            self.rail_buttons[key] = (button, icon_off, icon_on)

        footer = ctk.CTkFrame(rail, fg_color=BG_1, corner_radius=0)
        footer.grid(row=len(RAIL_ITEMS) + 2, column=0, pady=(0, 18))
        self.mute_btn = ctk.CTkButton(
            footer, text="", image=make_icon("speaker", CYAN_DIM, 19, 1.8),
            width=52, height=44, corner_radius=14, fg_color="transparent",
            hover_color=SURFACE_2, command=self.toggle_mute)
        self.mute_btn.pack()
        self.handsfree_btn = ctk.CTkButton(
            footer, text="", image=make_icon("broadcast", TEXT_MUTE, 19, 1.8),
            width=52, height=44, corner_radius=14, fg_color="transparent",
            hover_color=SURFACE_2, command=self.toggle_handsfree)
        self.handsfree_btn.pack(pady=(6, 0))
        self.mute_btn.bind("<Enter>", lambda e: self.set_activity(
            "Toggle spoken replies (Ctrl+M)"))
        self.handsfree_btn.bind("<Enter>", lambda e: self.set_activity(
            "Hands-free listening \u2014 re-arms the mic after every reply"))
        return rail

    # ----------------------------------------------------------- presence col
    def _build_presence(self, parent):
        p = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=0, width=430)
        p.grid_propagate(False)
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(p, fg_color=SURFACE, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="PRESENCE", font=(MONO, 8),
                     text_color=TEXT_MUTE).grid(row=0, column=0, sticky="w")
        self.presence_state = ctk.CTkLabel(
            header, text="BOOT", font=self.f_chip, text_color=CYAN,
            fg_color=SURFACE_2, corner_radius=999, padx=12, pady=4)
        self.presence_state.grid(row=0, column=1, sticky="e")

        self.reactor = ReactorCanvas(p, size=300)
        self.reactor.grid(row=1, column=0, sticky="nsew", padx=8, pady=2)

        self.wave = WaveCanvas(p, height=54, bars=64)
        self.wave.grid(row=2, column=0, sticky="ew", padx=24)

        caption = ctk.CTkFrame(p, fg_color=SURFACE_2, corner_radius=10)
        caption.grid(row=3, column=0, sticky="ew", padx=18, pady=(12, 4))
        caption.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(caption, fg_color=CYAN_DIM, width=2, corner_radius=1).grid(
            row=0, column=0, rowspan=2, sticky="ns", padx=(11, 9), pady=11)
        self.caption_you = ctk.CTkLabel(
            caption, text="YOU \u2014 \u2026", font=(MONO, 8), text_color=TEXT_MUTE,
            anchor="w", justify="left", wraplength=330)
        self.caption_you.grid(row=0, column=1, sticky="w", pady=(10, 0))
        self.caption_ai = ctk.CTkLabel(
            caption, text=STATES["BOOT"][2], font=(UI, 11), text_color=TEXT,
            anchor="w", justify="left", wraplength=330)
        self.caption_ai.grid(row=1, column=1, sticky="w", pady=(1, 10),
                             padx=(0, 12))

        # ---- transport: interrupt · speak · hands-free ---------------------
        transport = ctk.CTkFrame(p, fg_color=SURFACE, corner_radius=0)
        transport.grid(row=4, column=0, sticky="ew", padx=18, pady=(14, 0))

        self.stop_btn = ctk.CTkButton(
            transport, text="", image=make_icon("stop", TEXT_DIM, 17, 2.0),
            width=50, height=50, corner_radius=25, fg_color=SURFACE_2,
            hover_color="#3A1E27", command=self.stop_speaking)
        self.stop_btn.pack(side="left", padx=(52, 12))
        self.stop_btn.bind("<Enter>", lambda e: self.set_activity(
            "Interrupt speech (Esc)"))

        mic_wrap = ctk.CTkFrame(transport, fg_color=SURFACE, corner_radius=0)
        mic_wrap.pack(side="left")
        self.mic_btn = ctk.CTkButton(
            mic_wrap, text="", image=make_icon("mic", BG, 25, 2.1), width=70,
            height=70, corner_radius=35, fg_color=CYAN,
            hover_color=mix(CYAN, "#FFFFFF", 0.28), command=self.start_voice)
        self.mic_btn.pack()
        self.mic_hint = ctk.CTkLabel(mic_wrap, text="TAP TO SPEAK",
                                     font=(MONO, 7), text_color=TEXT_MUTE)
        self.mic_hint.pack(pady=(5, 0))

        hf_wrap = ctk.CTkFrame(transport, fg_color=SURFACE, corner_radius=0)
        hf_wrap.pack(side="left", padx=(12, 52))
        self.hf_big_btn = ctk.CTkButton(
            hf_wrap, text="", image=make_icon("broadcast", TEXT_DIM, 17, 2.0),
            width=50, height=50, corner_radius=25, fg_color=SURFACE_2,
            hover_color=SURFACE_3, command=self.toggle_handsfree)
        self.hf_big_btn.pack()
        self.hf_hint = ctk.CTkLabel(hf_wrap, text="HANDS-FREE", font=(MONO, 7),
                                    text_color=TEXT_MUTE)
        self.hf_hint.pack(pady=(5, 0))

        # ---- quick intents -------------------------------------------------
        intents = ctk.CTkFrame(p, fg_color=SURFACE, corner_radius=0)
        intents.grid(row=5, column=0, sticky="ew", padx=18, pady=(16, 0))
        intents.grid_columnconfigure(0, weight=1)
        intents.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(intents, text="QUICK INTENTS", font=(MONO, 7),
                     text_color=TEXT_MUTE).grid(row=0, column=0, columnspan=2,
                                                sticky="w", pady=(0, 7))
        chip_rows = (
            (("Run diagnostics",
              "Run a full system diagnostics check and report CPU, memory, "
              "disk, battery and GPU status."),
             ("Create slides",
              "Create a professional presentation about renewable energy "
              "in India.")),
            (("Write a document",
              "Create a Word document titled 'Weekly Progress Report' with a "
              "short professional summary."),
             ("Web research",
              "Search the web for the latest developments in local AI "
              "assistants and summarise the top results.")),
        )
        for r, pair in enumerate(chip_rows):
            for c, (chip_text, prompt) in enumerate(pair):
                padx = (0, 6) if c == 0 else (6, 0)
                ctk.CTkButton(
                    intents, text=chip_text, font=(UI, 10), height=33,
                    corner_radius=9, fg_color=SURFACE_2, hover_color=SURFACE_3,
                    border_width=1, border_color=HAIRLINE_2,
                    text_color=TEXT_DIM, anchor="w",
                    command=lambda t=prompt: self.dispatch(t)).grid(
                    row=r + 1, column=c, sticky="ew", padx=padx, pady=3)

        # ---- slim telemetry ribbon ----------------------------------------
        ctk.CTkFrame(p, fg_color=HAIRLINE, height=1, corner_radius=0).grid(
            row=6, column=0, sticky="ew", padx=18, pady=(16, 0))
        ribbon = ctk.CTkFrame(p, fg_color=SURFACE, corner_radius=0)
        ribbon.grid(row=7, column=0, sticky="ew", padx=18, pady=(10, 16))
        ribbon.grid_columnconfigure(0, weight=1)
        ribbon.grid_columnconfigure(1, weight=1)
        self.telemetry = {}
        readouts = (("cpu", "PROCESSOR", CYAN), ("mem", "MEMORY", BLUE),
                    ("disk", "DISK C:", CYAN_DIM), ("battery", "POWER", GREEN))
        for i, (key, label, colour) in enumerate(readouts):
            padx = (0, 14) if i % 2 == 0 else (14, 0)
            cell = ctk.CTkFrame(ribbon, fg_color=SURFACE, corner_radius=0)
            cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=padx, pady=4)
            cell.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(cell, text=label, font=(MONO, 7),
                         text_color=TEXT_MUTE).grid(row=0, column=0, sticky="w")
            value = ctk.CTkLabel(cell, text="\u2014", font=(MONO, 9, "bold"),
                                 text_color=TEXT)
            value.grid(row=0, column=1, sticky="e")
            bar = HairlineBar(cell, width=160, height=5)
            bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            self.telemetry[key] = (value, bar, colour)
        return p

    # ------------------------------------------------------------- workspace
    def _build_workspace(self, parent):
        ws = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=0)
        ws.grid_rowconfigure(2, weight=1)
        ws.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(ws, fg_color=SURFACE, corner_radius=0, height=60)
        head.grid(row=0, column=0, sticky="ew", padx=22, pady=(16, 8))
        head.grid_propagate(False)
        head.grid_columnconfigure(1, weight=1)
        self.view_title = ctk.CTkLabel(head, text="CONVERSATION",
                                       font=(DISPLAY, 15, "bold"), text_color=TEXT)
        self.view_title.grid(row=0, column=0, sticky="w")
        self.view_sub = ctk.CTkLabel(head, text="", font=(MONO, 8),
                                     text_color=TEXT_MUTE)
        self.view_sub.grid(row=1, column=0, sticky="w")
        self.view_actions = ctk.CTkFrame(head, fg_color=SURFACE, corner_radius=0)
        self.view_actions.grid(row=0, column=2, rowspan=2, sticky="e")

        ctk.CTkFrame(ws, fg_color=HAIRLINE, height=1, corner_radius=0).grid(
            row=1, column=0, sticky="ew")

        stack = ctk.CTkFrame(ws, fg_color=SURFACE, corner_radius=0)
        stack.grid(row=2, column=0, sticky="nsew")
        stack.grid_rowconfigure(0, weight=1)
        stack.grid_columnconfigure(0, weight=1)

        self.views = {
            "conversation": self._view_conversation(stack),
            "capabilities": self._view_capabilities(stack),
            "activity": self._view_activity(stack),
            "deliverables": self._view_deliverables(stack),
            "diagnostics": self._view_diagnostics(stack),
            "about": self._view_about(stack),
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew")
        self.show_view("conversation")
        return ws

    # ------------------------------------------------------------ view helpers
    def _scroll_area(self, parent, bg=SURFACE):
        """Scrollable region: returns (holder, canvas, inner frame)."""
        holder = ctk.CTkFrame(parent, fg_color=bg, corner_radius=0)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(holder, bg=bg, highlightthickness=0, bd=0,
                           takefocus=0)
        scroll = ctk.CTkScrollbar(holder, command=canvas.yview, width=10,
                                  corner_radius=5, fg_color=bg,
                                  button_color=HAIRLINE_2,
                                  button_hover_color=CYAN_DIM)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew", padx=(20, 6), pady=(4, 14))
        scroll.grid(row=0, column=1, sticky="ns", pady=(4, 14), padx=(0, 10))
        inner = ctk.CTkFrame(canvas, fg_color=bg, corner_radius=0)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            window, width=e.width))
        self._bind_wheel(canvas, canvas)
        self._bind_wheel(inner, canvas)
        return holder, canvas, inner

    def _bind_wheel(self, widget, canvas):
        """Route mouse-wheel events (widget + descendants) to a canvas."""
        def _on_wheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)) * 2, "units")
            except Exception:
                pass

        stack = [widget]
        while stack:
            current = stack.pop()
            try:
                current.bind("<MouseWheel>", _on_wheel, add="+")
            except Exception:
                pass
            try:
                stack.extend(current.winfo_children())
            except Exception:
                pass

    def _scroll_bottom(self, canvas):
        try:
            canvas.update_idletasks()
            canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _sub_header(self, parent, text, note=""):
        row = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=0)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=text, font=(MONO, 8, "bold"),
                     text_color=CYAN_DIM).grid(row=0, column=0, sticky="w")
        if note:
            ctk.CTkLabel(row, text=note, font=(MONO, 8),
                         text_color=TEXT_MUTE).grid(row=0, column=1, sticky="e")
        return row

    def _action_button(self, parent, kind, text, command, accent=False):
        button = ctk.CTkButton(
            parent, text="  " + text,
            image=make_icon(kind, BG if accent else TEXT_DIM, 15, 1.9),
            compound="left", font=(MONO, 9, "bold"), height=32,
            corner_radius=9,
            fg_color=CYAN if accent else SURFACE_2,
            hover_color=mix(CYAN, "#FFFFFF", 0.22) if accent else SURFACE_3,
            text_color=BG if accent else TEXT_DIM,
            border_width=0 if accent else 1, border_color=HAIRLINE_2,
            command=command)
        button.pack(side="left", padx=6)
        return button

    def show_view(self, key):
        if key not in self.views:
            return
        self.view = key
        self.views[key].tkraise()
        title, subtitle = VIEW_TITLES.get(key, ("", ""))
        self.view_title.configure(text=title)
        self.view_sub.configure(text=subtitle)
        for child in self.view_actions.winfo_children():
            child.destroy()
        builders = {
            "conversation": self._actions_conversation,
            "activity": self._actions_activity,
            "deliverables": self._actions_deliverables,
            "diagnostics": self._actions_diagnostics,
            "about": self._actions_about,
        }
        builder = builders.get(key)
        if builder:
            builder()
        for name, (button, icon_off, icon_on) in self.rail_buttons.items():
            active = (name == key)
            button.configure(image=icon_on if active else icon_off,
                             fg_color=SURFACE_2 if active else "transparent")
        if key == "deliverables":
            self.refresh_deliverables()
        elif key == "diagnostics":
            self.refresh_diagnostics()
        self.set_activity("%s view" % title.title())

    # ======================================================== CONVERSATION
    def _view_conversation(self, parent):
        page = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=0)
        holder, canvas, inner = self._scroll_area(page)
        holder.pack(fill="both", expand=True)
        self.chat_canvas = canvas
        self.chat_inner = inner
        self.chat_row = 0
        inner.grid_columnconfigure(0, weight=1)

        # ---- intro / empty state ------------------------------------------
        self.intro_card = self._conv_intro(inner)

        # ---- typing indicator (hidden until the engine is thinking) --------
        typing = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=12,
                              border_width=1, border_color=HAIRLINE)
        typing.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(typing, fg_color=CYAN, width=3, corner_radius=2).grid(
            row=0, column=0, rowspan=2, sticky="ns")
        head = ctk.CTkFrame(typing, fg_color=SURFACE_2, corner_radius=0)
        head.grid(row=0, column=1, sticky="ew", padx=(14, 14), pady=(11, 0))
        ctk.CTkLabel(head, text="J", width=26, height=26, corner_radius=13,
                     fg_color=CYAN, text_color=BG,
                     font=(MONO, 10, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(head, text="JARVIS", font=(MONO, 9, "bold"),
                     text_color=CYAN).grid(row=0, column=1, padx=(9, 0))
        self.typing_label = ctk.CTkLabel(typing, text="thinking.",
                                        font=(MONO, 9), text_color=TEXT_DIM,
                                        anchor="w")
        self.typing_label.grid(row=1, column=1, sticky="w", padx=(14, 16),
                               pady=(4, 13))
        typing.grid_remove()
        self.typing_card = typing
        self._bind_wheel(typing, canvas)

        canvas.bind("<Configure>", self._resize_wraps, add="+")
        return page

    def _resize_wraps(self, event):
        width = max(300, event.width - 150)
        for label in list(self._wrap_labels):
            try:
                label.configure(wraplength=width)
            except Exception:
                pass

    def _conv_intro(self, inner):
        """Empty-state card shown when the transcript has no messages."""
        intro = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=14,
                             border_width=1, border_color=HAIRLINE_2)
        intro.grid(row=0, column=0, sticky="ew", pady=(8, 8))
        intro.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(intro, text="",
                     image=make_icon("core", CYAN, 34, 1.7)).grid(
            row=0, column=0, rowspan=3, padx=(20, 16), pady=20)
        ctk.CTkLabel(intro, text="Standing by, sir",
                     font=(DISPLAY, 15, "bold"), text_color=TEXT).grid(
            row=0, column=1, sticky="w", pady=(18, 0))
        ctk.CTkLabel(
            intro,
            text="Type a command below or tap the microphone. J.A.R.V.I.S. "
                 "answers aloud with the local Piper voice and can create "
                 "documents, slide decks and r\u00e9sum\u00e9s, control this machine, "
                 "run web research and report system telemetry.",
            font=self.f_body_dim, text_color=TEXT_DIM, wraplength=560,
            justify="left").grid(row=1, column=1, sticky="w", pady=(3, 0))
        ctk.CTkLabel(
            intro,
            text="TRY  \u201ccreate a presentation on quantum computing\u201d   "
                 "\u00b7   \u201cwhat is my CPU usage?\u201d   \u00b7   "
                 "\u201csearch the web for ISRO news\u201d",
            font=(MONO, 8), text_color=TEXT_MUTE, wraplength=560,
            justify="left").grid(row=2, column=1, sticky="w", pady=(8, 18))
        self._bind_wheel(intro, self.chat_canvas)
        return intro

    # ------------------------------------------------------- message cards
    def _add_message(self, role, text, tool=None, voice=None):
        if role != "notice" and not self._first_message_done:
            self._first_message_done = True
            try:
                self.intro_card.destroy()
            except Exception:
                pass

        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        accent = {"user": BLUE, "ai": CYAN, "notice": HAIRLINE_2}.get(
            role, HAIRLINE_2)
        background = SURFACE_2 if role != "notice" else SURFACE
        card = ctk.CTkFrame(self.chat_inner, fg_color=background,
                            corner_radius=12, border_width=1,
                            border_color=HAIRLINE)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(card, fg_color=accent, width=3, corner_radius=2).grid(
            row=0, column=0, rowspan=3, sticky="ns")

        head = ctk.CTkFrame(card, fg_color=background, corner_radius=0)
        head.grid(row=0, column=1, sticky="ew", padx=(14, 14), pady=(11, 0))
        head.grid_columnconfigure(2, weight=1)
        if role == "user":
            initials, name = "Y", "YOU"
        elif role == "ai":
            initials = "S" if voice == "en_female" else "J"
            name = "SIMMI" if voice == "en_female" else "JARVIS"
        else:
            initials, name = "\u00b7", "EVENT"
        ctk.CTkLabel(head, text=initials, width=26, height=26,
                     corner_radius=13, fg_color=accent, text_color=BG,
                     font=(MONO, 10, "bold")).grid(row=0, column=0)
        ctk.CTkLabel(head, text=name, font=(MONO, 9, "bold"),
                     text_color=accent).grid(row=0, column=1, padx=(9, 8))
        ctk.CTkLabel(head, text=stamp, font=(MONO, 8),
                     text_color=TEXT_MUTE).grid(row=0, column=3, sticky="e")

        body_colour = TEXT_DIM if role == "notice" else TEXT
        body = ctk.CTkLabel(
            card, text=text,
            font=(UI, 11) if role == "notice" else (UI, 12),
            text_color=body_colour,
            wraplength=max(300, self.chat_canvas.winfo_width() - 150),
            justify="left", anchor="w")
        body.grid(row=1, column=1, sticky="w", padx=(14, 18),
                  pady=(7, 8 if tool else 13))
        self._wrap_labels.append(body)

        if tool:
            chip = ctk.CTkFrame(card, fg_color=SURFACE, corner_radius=8,
                                border_width=1, border_color=HAIRLINE_2)
            chip.grid(row=2, column=1, sticky="ew", padx=(14, 18), pady=(0, 13))
            chip.grid_columnconfigure(2, weight=1)
            ok = tool.get("ok", True)
            ctk.CTkLabel(chip, text="", image=make_icon(
                "chip", GREEN if ok else RED, 14, 1.8)).grid(
                row=0, column=0, padx=(10, 7), pady=7)
            ctk.CTkLabel(chip, text=tool.get("name", ""), font=(MONO, 9, "bold"),
                         text_color=CYAN).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(chip, text=tool.get("detail", ""), font=(MONO, 8),
                         text_color=TEXT_MUTE, anchor="w", justify="left",
                         wraplength=max(200, self.chat_canvas.winfo_width() - 340)
                         ).grid(row=0, column=2, sticky="w", padx=10)

        self.chat_row += 1
        card.grid(row=self.chat_row, column=0, sticky="ew", pady=6)
        self._bind_wheel(card, self.chat_canvas)
        self._restack_typing()
        if self.view == "conversation":
            self._scroll_bottom(self.chat_canvas)
        return card

    def _add_notice(self, text):
        return self._add_message("notice", text)

    def _restack_typing(self):
        try:
            self.typing_card.grid(row=self.chat_row + 1, column=0, sticky="ew",
                                  pady=6)
        except Exception:
            pass

    def _set_typing(self, active):
        self._typing = bool(active)
        try:
            if self._typing:
                self._restack_typing()
                self.typing_card.grid()
                if self.view == "conversation":
                    self._scroll_bottom(self.chat_canvas)
            else:
                self.typing_card.grid_remove()
        except Exception:
            pass

    def _actions_conversation(self):
        self._action_button(self.view_actions, "export", "EXPORT",
                            self.export_conversation)
        self._action_button(self.view_actions, "trash", "CLEAR",
                            self.clear_conversation)

    # ======================================================== CAPABILITIES
    def _bind_deep(self, widget, sequence, handler):
        stack = [widget]
        while stack:
            current = stack.pop()
            try:
                current.bind(sequence, handler, add="+")
            except Exception:
                pass
            try:
                stack.extend(current.winfo_children())
            except Exception:
                pass

    def _view_capabilities(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)

        summary = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=12,
                               border_width=1, border_color=HAIRLINE_2)
        summary.grid(row=0, column=0, sticky="ew", pady=(8, 4))
        summary.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            summary,
            text="%d callable functions \u00b7 2 personalities \u00b7 "
                 "3 offline voices \u00b7 1 JSON tool-call contract"
                 % len(FUNCTION_MAP),
            font=(DISPLAY, 13, "bold"), text_color=TEXT).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            summary,
            text="Every capability below is exposed to the language model as a "
                 "structured tool. Ask naturally \u2014 J.A.R.V.I.S. selects the "
                 "tool, executes it and speaks the outcome.",
            font=self.f_body_dim, text_color=TEXT_DIM, wraplength=620,
            justify="left").grid(row=1, column=0, sticky="w", padx=16,
                                 pady=(0, 14))

        row = 1
        for group, note, entries in CAPABILITY_GROUPS:
            header = self._sub_header(inner, group, note)
            header.grid(row=row, column=0, sticky="ew", pady=(18, 8))
            row += 1
            for kind, name, description in entries:
                card = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=10,
                                    border_width=1, border_color=HAIRLINE)
                card.grid(row=row, column=0, sticky="ew", pady=3)
                card.grid_columnconfigure(1, weight=1)
                row += 1
                ctk.CTkLabel(card, text="", image=make_icon(
                    "chip" if kind == "tool" else "core",
                    CYAN if kind == "tool" else GOLD, 16, 1.7)).grid(
                    row=0, column=0, rowspan=2, padx=(13, 11), pady=11)
                ctk.CTkLabel(card, text=name, font=(MONO, 10, "bold"),
                             text_color=TEXT).grid(row=0, column=1, sticky="w",
                                                   pady=(10, 0))
                ctk.CTkLabel(card, text=description, font=(UI, 11),
                             text_color=TEXT_DIM, wraplength=520,
                             justify="left", anchor="w").grid(
                    row=1, column=1, sticky="w", pady=(1, 11))
                ctk.CTkLabel(card, text="CALLABLE" if kind == "tool" else "BUILT-IN",
                             font=(MONO, 7, "bold"),
                             text_color=GREEN if kind == "tool" else GOLD,
                             fg_color=SURFACE, corner_radius=6, padx=8,
                             pady=4).grid(row=0, column=2, rowspan=2,
                                          padx=(10, 13))
                self._bind_wheel(card, canvas)

        ctk.CTkLabel(inner,
                     text="See the ACTIVITY view for a live tool-call timeline.",
                     font=(MONO, 8), text_color=TEXT_MUTE).grid(
            row=row, column=0, sticky="w", pady=(16, 20))
        return holder

    # ============================================================ ACTIVITY
    def _view_activity(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        self.activity_canvas = canvas
        self.activity_inner = inner
        self.activity_row = 0
        self._activity_rows = []
        self.log_activity("SYSTEM", "Timeline online \u2014 intents, tool calls "
                                    "and voice events are recorded here.")
        return holder

    def log_activity(self, kind, text, colour=None):
        palette = {"INTENT": BLUE, "TOOL": CYAN, "VOICE": GREEN, "ERROR": RED,
                   "SYSTEM": TEXT_MUTE, "MODEL": GOLD}
        colour = colour or palette.get(kind, TEXT_DIM)
        self.activity_row += 1
        strip = ctk.CTkFrame(self.activity_inner, fg_color=SURFACE,
                             corner_radius=0)
        strip.grid(row=self.activity_row, column=0, sticky="ew", pady=1)
        strip.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(strip, text=_dt.datetime.now().strftime("%H:%M:%S"),
                     font=(MONO, 8), text_color=TEXT_MUTE).grid(
            row=0, column=0, padx=(2, 12), pady=3)
        ctk.CTkLabel(strip, text="%-7s" % kind, font=(MONO, 8, "bold"),
                     text_color=colour).grid(row=0, column=1, sticky="w",
                                             padx=(0, 12))
        label = ctk.CTkLabel(
            strip, text=text, font=(MONO, 9), text_color=TEXT_DIM, anchor="w",
            justify="left",
            wraplength=max(280, self.activity_canvas.winfo_width() - 240))
        label.grid(row=0, column=2, sticky="w", pady=3)
        self._wrap_labels.append(label)
        self._activity_rows.append(strip)
        while len(self._activity_rows) > 240:
            try:
                self._activity_rows.pop(0).destroy()
            except Exception:
                break
        self._bind_wheel(strip, self.activity_canvas)
        if self.view == "activity":
            self._scroll_bottom(self.activity_canvas)

    def _actions_activity(self):
        self._action_button(self.view_actions, "trash", "CLEAR LOG",
                            self.clear_activity_log)

    def clear_activity_log(self):
        for row in self._activity_rows:
            try:
                row.destroy()
            except Exception:
                pass
        self._activity_rows = []
        self.activity_row = 0
        self.log_activity("SYSTEM", "Timeline cleared.")

    # ======================================================== DELIVERABLES
    def _view_deliverables(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        self.deliverable_canvas = canvas
        self.deliverable_inner = inner
        return holder

    def _scan_deliverables(self):
        items = []
        if not os.path.isdir(OUTPUT_DIR):
            return items
        for root, dirs, names in os.walk(OUTPUT_DIR):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in names:
                path = os.path.join(root, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                items.append((stat.st_mtime, path, stat.st_size))
        items.sort(key=lambda entry: entry[0], reverse=True)
        return items[:150]

    def refresh_deliverables(self):
        inner = self.deliverable_inner
        for child in inner.winfo_children():
            child.destroy()
        items = self._scan_deliverables()
        self._sub_header(inner, "GENERATED FILES",
                         "%d item(s)" % len(items)).grid(
            row=0, column=0, sticky="ew", pady=(8, 8))
        if not items:
            ctk.CTkLabel(
                inner,
                text="Nothing generated yet. Ask J.A.R.V.I.S. for a document, "
                     "a slide deck, a r\u00e9sum\u00e9 or a screenshot and the artefact "
                     "will appear here.",
                font=self.f_body_dim, text_color=TEXT_DIM, wraplength=520,
                justify="left").grid(row=1, column=0, sticky="w", pady=10)
            return

        row = 1
        for mtime, path, size in items:
            card = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=9,
                                border_width=1, border_color=HAIRLINE)
            card.grid(row=row, column=0, sticky="ew", pady=2)
            row += 1
            card.grid_columnconfigure(1, weight=1)
            ext = os.path.splitext(path)[1].lower().lstrip(".") or "file"
            if ext in ("pptx", "ppt"):
                icon_kind = "layers"
            elif ext in ("docx", "doc", "md", "txt"):
                icon_kind = "chat"
            elif ext in ("png", "jpg", "jpeg", "webp"):
                icon_kind = "eye"
            else:
                icon_kind = "folder"
            ctk.CTkLabel(card, text="", image=make_icon(icon_kind, CYAN, 16,
                                                        1.7)).grid(
                row=0, column=0, rowspan=2, padx=(12, 11), pady=10)
            ctk.CTkLabel(card, text=shorten(os.path.basename(path), 48),
                         font=(MONO, 10, "bold"), text_color=TEXT,
                         anchor="w").grid(row=0, column=1, sticky="w",
                                          pady=(9, 0))
            folder = os.path.relpath(os.path.dirname(path), OUTPUT_DIR)
            detail = "%s \u00b7 %s \u00b7 %s" % (
                ext.upper(), human_size(size),
                time.strftime("%d %b %H:%M", time.localtime(mtime)))
            if folder not in (".", ""):
                detail = folder.replace("\\", "/") + "  \u00b7  " + detail
            ctk.CTkLabel(card, text=shorten(detail, 74), font=(MONO, 8),
                         text_color=TEXT_MUTE, anchor="w").grid(
                row=1, column=1, sticky="w", pady=(1, 9))
            ctk.CTkButton(card, text="", image=make_icon("eye", TEXT_DIM, 14, 1.8),
                          width=36, height=30, corner_radius=8, fg_color=SURFACE,
                          hover_color=SURFACE_3,
                          command=lambda p=path: self.open_path(p)).grid(
                row=0, column=2, rowspan=2, padx=(8, 12))
            self._bind_wheel(card, self.deliverable_canvas)
            self._bind_deep(card, "<Double-Button-1>",
                            lambda e, p=path: self.open_path(p))

    def _actions_deliverables(self):
        self._action_button(self.view_actions, "refresh", "REFRESH",
                            self.refresh_deliverables)
        self._action_button(self.view_actions, "folder", "OPEN FOLDER",
                            lambda: self.open_path(OUTPUT_DIR))

    def _actions_diagnostics(self):
        self._action_button(self.view_actions, "refresh", "REFRESH",
                            self.refresh_diagnostics)

    # ========================================================= DIAGNOSTICS
    def _view_diagnostics(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        self.diag_canvas = canvas
        self.diag_inner = inner
        self.diag_labels = {}
        self.diag_row = -1

        self._diag_section(inner, "COMPUTE", "live telemetry")
        for key, label, bar in (("cpu", "PROCESSOR LOAD", True),
                                ("mem", "MEMORY LOAD", True),
                                ("disk", "SYSTEM DISK LOAD", True),
                                ("gpu", "GRAPHICS ADAPTER", False),
                                ("cores", "LOGICAL CORES", False),
                                ("battery", "POWER SOURCE", False),
                                ("uptime", "MACHINE UPTIME", False)):
            self._diag_item(inner, key, label, bar)

        self._diag_section(inner, "LOAD HISTORY", "rolling window")
        self.diag_row += 1
        chart = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=10,
                             border_width=1, border_color=HAIRLINE)
        chart.grid(row=self.diag_row, column=0, sticky="ew", pady=3)
        chart.grid_columnconfigure(0, weight=1)
        self.sparkline = Sparkline(chart, height=96)
        self.sparkline.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        legend = ctk.CTkFrame(chart, fg_color=SURFACE_2, corner_radius=0)
        legend.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))
        for i, (text, colour) in enumerate((("CPU", CYAN), ("MEMORY", BLUE))):
            ctk.CTkLabel(legend, text="\u25ac", font=(MONO, 10),
                         text_color=colour).grid(row=0, column=i * 2,
                                                 padx=(0, 5) if i else 0)
            ctk.CTkLabel(legend, text=text, font=(MONO, 8),
                         text_color=TEXT_MUTE).grid(row=0, column=i * 2 + 1,
                                                    padx=(0, 20))
        self._bind_wheel(chart, canvas)

        self._diag_section(inner, "LANGUAGE MODELS",
                           "provider chain with automatic fallback")
        for key, label in (("provider_groq", "GROQ CLOUD \u2014 PRIMARY"),
                           ("provider_cerebras", "CEREBRAS \u2014 SECONDARY"),
                           ("provider_gemini", "GOOGLE GEMINI \u2014 ROTATING KEYS"),
                           ("tools", "TOOL-CALL CONTRACT")):
            self._diag_item(inner, key, label)

        self._diag_section(inner, "VOICE STACK",
                           "Piper neural TTS \u00b7 fully offline")
        for key, label in (("voice_en_male", "JARVIS \u2014 ENGLISH VOICE"),
                           ("voice_hi_male", "JARVIS \u2014 HINDI VOICE"),
                           ("voice_en_female", "SIMMI \u2014 ENGLISH VOICE"),
                           ("voice_input", "SPEECH INPUT"),
                           ("wake", "WAKE WORDS")):
            self._diag_item(inner, key, label)

        self._diag_section(inner, "RUNTIME", "this session")
        for key, label in (("engine", "ENGINE STATUS"),
                           ("engine_load", "ENGINE LOAD TIME"),
                           ("python", "PYTHON RUNTIME"),
                           ("path", "PROJECT ROOT"),
                           ("session", "SESSION AGE"),
                           ("counts", "MESSAGES \u00b7 TOOLS \u00b7 EXPORTS")):
            self._diag_item(inner, key, label)
        self.refresh_diagnostics()
        return holder

    def _diag_section(self, parent, title, note=""):
        self.diag_row += 1
        header = self._sub_header(parent, title, note)
        header.grid(row=self.diag_row, column=0, sticky="ew", pady=(18, 8))

    def _diag_item(self, parent, key, label, bar=False):
        self.diag_row += 1
        pad = (9, 10) if bar else (11, 11)
        card = ctk.CTkFrame(parent, fg_color=SURFACE_2, corner_radius=8,
                            border_width=1, border_color=HAIRLINE)
        card.grid(row=self.diag_row, column=0, sticky="ew", pady=2)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=label, font=(MONO, 8),
                     text_color=TEXT_MUTE).grid(row=0, column=0, sticky="w",
                                                padx=(12, 10), pady=pad)
        value = ctk.CTkLabel(card, text="\u2014", font=(MONO, 10, "bold"),
                             text_color=TEXT, anchor="e", justify="right")
        value.grid(row=0, column=1, sticky="e", padx=(0, 12), pady=pad)
        bar_widget = None
        if bar:
            bar_widget = HairlineBar(card, width=220, height=5)
            bar_widget.grid(row=1, column=0, columnspan=2, sticky="ew",
                            padx=12, pady=(0, 10))
        self.diag_labels[key] = (value, bar_widget)
        self._bind_wheel(card, self.diag_canvas)

    def _diag_set(self, key, text, pct=None, colour=None):
        entry = self.diag_labels.get(key)
        if not entry:
            return
        value, bar = entry
        try:
            value.configure(text=str(text), text_color=colour or TEXT)
            if bar is not None and pct is not None:
                bar.set_value(pct, colour or CYAN)
        except Exception:
            pass

    def refresh_diagnostics(self):
        if not getattr(self, "diag_labels", None):
            return
        info = self.sys_info or {}

        def as_pct(value):
            try:
                return float(str(value).replace("%", "").strip().split()[0])
            except Exception:
                return 0.0

        def tone(value):
            return GREEN if value < 60 else (AMBER if value < 85 else RED)

        cpu = as_pct(info.get("cpu_usage"))
        mem = as_pct(info.get("memory"))
        disk = as_pct(info.get("disk_usage"))
        self._diag_set("cpu", info.get("cpu_usage", "collecting \u2026"),
                       cpu, tone(cpu))
        self._diag_set("mem", "%s of %s" % (info.get("memory", "\u2014"),
                                            info.get("memory_total", "\u2014")),
                       mem, tone(mem))
        self._diag_set("disk", "%s used \u00b7 %s free"
                       % (info.get("disk_usage", "\u2014"),
                          info.get("disk_free", "\u2014")), disk, tone(disk))
        gpu = info.get("gpu") or []
        self._diag_set("gpu", shorten(gpu[0].get("name", "N/A"), 40)
                       if gpu else "N/A")
        self._diag_set("cores", info.get("cpu_count", "\u2014"))
        self._diag_set("battery", info.get("battery", "\u2014"))

        psutil_mod = engine_get("psutil")
        uptime = "N/A"
        if psutil_mod is not None:
            try:
                uptime = hms(time.time() - psutil_mod.boot_time())
            except Exception:
                uptime = "N/A"
        self._diag_set("uptime", uptime)

        brain = engine_get("jarvis_brain")
        google_keys = len(getattr(brain, "google_keys", []) or []) if brain else 0
        providers = (
            ("provider_groq", "USE_GROQ", "GROQ_MODEL_NAME"),
            ("provider_cerebras", "USE_CEREBRAS", "CEREBRAS_MODEL_NAME"),
            ("provider_gemini", "USE_GEMINI", "GEMINI_MODEL_NAME"),
        )
        for key, flag, model_attr in providers:
            online = bool(engine_get(flag, False))
            model = shorten(str(engine_get(model_attr, "") or "auto"), 26)
            suffix = ""
            if key == "provider_gemini" and google_keys:
                suffix = "  \u00b7  %d key%s" % (google_keys,
                                               "s" if google_keys > 1 else "")
            text = ("ONLINE   \u00b7   " + model + suffix) if online else \
                "OFFLINE   \u00b7   key not configured"
            self._diag_set(key, text, None, GREEN if online else RED)

        self._diag_set("tools", "%d functions registered" % len(FUNCTION_MAP),
                       None, CYAN if FUNCTION_MAP else RED)

        loaded = engine_get("voice_engines", {}) or {}
        for key, voice_key in (("voice_en_male", "en_male"),
                               ("voice_hi_male", "hi_male"),
                               ("voice_en_female", "en_female")):
            ready = voice_key in loaded
            name = (VOICES.get(voice_key) or {}).get("name", voice_key)
            self._diag_set(key, ("READY   \u00b7   " if ready else "MISSING   \u00b7   ")
                           + shorten(name, 32), None, GREEN if ready else RED)
        self._diag_set("voice_input",
                       "READY   \u00b7   SpeechRecognition + sounddevice"
                       if VOICE_INPUT else
                       "UNAVAILABLE   \u00b7   " + shorten(SR_ERROR or ENGLISH_ONLY_NOTE, 30),
                       None, GREEN if VOICE_INPUT else AMBER)
        self._diag_set("wake", "\u201cJarvis\u201d   \u00b7   \u201cSimmi\u201d",
                       None, CYAN)

        self._diag_set("engine", "ONLINE   \u00b7   jarvis.py" if ENGINE_OK
                       else "OFFLINE   \u00b7   " + shorten(ENGINE_ERR, 30),
                       None, GREEN if ENGINE_OK else RED)
        self._diag_set("engine_load", ("%.2f s" % (ENGINE_LOAD_MS / 1000.0))
                       if ENGINE_LOAD_MS else "\u2014")
        self._diag_set("python", "Python %s" % sys.version.split()[0])
        self._diag_set("path", shorten(BASE_DIR, 46))
        self._diag_set("session", hms(time.time() - self.started))
        self._diag_set("counts", "%d  \u00b7  %d  \u00b7  %d"
                       % (self.msg_count, self.tool_count, self.export_count))

    # ================================================================= ABOUT
    def _view_about(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=14,
                            border_width=1, border_color=CYAN_DIM)
        hero.grid(row=0, column=0, sticky="ew", pady=(8, 6))
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hero, text="",
                     image=make_icon("core", CYAN, 46, 1.6)).grid(
            row=0, column=0, pady=(22, 8))
        ctk.CTkLabel(hero, text="J.A.R.V.I.S", font=(DISPLAY, 28, "bold"),
                     text_color=TEXT).grid(row=1, column=0)
        ctk.CTkLabel(hero, text="JUST A RATHER VERY INTELLIGENT SYSTEM   \u00b7   v3.0",
                     font=(MONO, 8), text_color=TEXT_MUTE).grid(
            row=2, column=0, pady=(3, 10))
        ctk.CTkLabel(
            hero,
            text="A context-aware desktop assistant that infers who you are "
                 "addressing \u2014 JARVIS or Simmi \u2014 without switch commands, "
                 "replies with offline neural voices in English and Hindi, and "
                 "turns conversation into finished documents, slide decks and "
                 "r\u00e9sum\u00e9s through structured tool calls.",
            font=self.f_body_dim, text_color=TEXT_DIM, wraplength=640,
            justify="center").grid(row=3, column=0, padx=28)
        ctk.CTkButton(
            hero, text="  github.com/rajatrajdav/Local_AI-assistant",
            image=make_icon("export", CYAN, 14, 1.8), compound="left",
            font=(MONO, 9), fg_color=SURFACE, hover_color=SURFACE_3,
            text_color=CYAN, corner_radius=9, height=34,
            command=lambda: webbrowser.open(REPO_URL)).grid(
            row=4, column=0, pady=(16, 22))
        self._bind_wheel(hero, canvas)

        row = 1
        blocks = (
            ("PIPELINE", (
                ("Intent routing",
                 "Wake-word strip \u2192 personality and language detection \u2192 "
                 "voice selection, all resolved before the model is called."),
                ("Adaptive brain",
                 "One structured JSON contract per turn: reply text, response "
                 "language, voice preference and an optional tool call."),
                ("Local execution",
                 "Tools run on this machine \u2014 documents, slides, r\u00e9sum\u00e9s, "
                 "screenshots, shell commands and web research."),
                ("Spoken answer",
                 "The final response is synthesised by Piper and streamed to "
                 "the speakers chunk by chunk."),
            )),
            ("SHOWCASE HIGHLIGHTS", (
                ("Arc-reactor presence",
                 "The reactor responds to interface state and to the real "
                 "amplitude of J.A.R.V.I.S.'s voice."),
                ("Hands-free conversation",
                 "Enable it and the microphone re-arms automatically after "
                 "every reply."),
                ("Interruptible speech",
                 "The stop control ends playback between audio chunks \u2014 no "
                 "waiting for a sentence to finish."),
                ("Deliverables browser",
                 "Everything the assistant produced is listed, timestamped and "
                 "one click away."),
            )),
        )
        for title, items in blocks:
            self._sub_header(inner, title).grid(row=row, column=0, sticky="ew",
                                                pady=(18, 8))
            row += 1
            for name, description in items:
                card = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=10,
                                    border_width=1, border_color=HAIRLINE)
                card.grid(row=row, column=0, sticky="ew", pady=3)
                row += 1
                card.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(card, text=name, font=(MONO, 10, "bold"),
                             text_color=CYAN).grid(row=0, column=0, sticky="w",
                                                   padx=14, pady=(10, 0))
                ctk.CTkLabel(card, text=description, font=(UI, 11),
                             text_color=TEXT_DIM, wraplength=600, justify="left",
                             anchor="w").grid(row=1, column=0, sticky="w",
                                              padx=14, pady=(2, 11))
                self._bind_wheel(card, canvas)

        self._sub_header(inner, "CONTROLS", "keyboard").grid(
            row=row, column=0, sticky="ew", pady=(18, 8))
        row += 1
        for keys, action in SHORTCUTS:
            card = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=8,
                                border_width=1, border_color=HAIRLINE)
            card.grid(row=row, column=0, sticky="ew", pady=2)
            row += 1
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=keys, font=(MONO, 9, "bold"),
                         text_color=GOLD, fg_color=SURFACE, corner_radius=6,
                         padx=9, pady=4).grid(row=0, column=0, padx=12, pady=8)
            ctk.CTkLabel(card, text=action, font=(UI, 11), text_color=TEXT_DIM,
                         anchor="w").grid(row=0, column=1, sticky="w",
                                          padx=(0, 12))
            self._bind_wheel(card, canvas)

        self._sub_header(inner, "STACK").grid(row=row, column=0, sticky="ew",
                                              pady=(18, 8))
        row += 1
        stack_card = ctk.CTkFrame(inner, fg_color=SURFACE_2, corner_radius=10,
                                  border_width=1, border_color=HAIRLINE)
        stack_card.grid(row=row, column=0, sticky="ew", pady=(3, 22))
        stack_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(stack_card, text="   \u00b7   ".join(STACK),
                     font=(MONO, 9), text_color=TEXT_DIM, wraplength=640,
                     justify="left", anchor="w").grid(row=0, column=0,
                                                      sticky="w", padx=14,
                                                      pady=12)
        self._bind_wheel(stack_card, canvas)
        return holder

    def _actions_about(self):
        self._action_button(self.view_actions, "terminal", "SHORTCUTS",
                            self._show_shortcuts)

    # ============================================================ COMPOSER
    def _build_composer(self):
        wrap = ctk.CTkFrame(self, fg_color=BG_1, corner_radius=0, height=94)
        wrap.grid_propagate(False)
        ctk.CTkFrame(wrap, fg_color=HAIRLINE, height=1, corner_radius=0).place(
            in_=wrap, relx=0, rely=0, relwidth=1)

        box = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=14,
                           border_width=1, border_color=HAIRLINE_2)
        box.pack(fill="both", expand=True, padx=22, pady=(14, 12))
        box.grid_columnconfigure(1, weight=1)
        box.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(box, text="\u25b8", font=(MONO, 14, "bold"),
                     text_color=CYAN).grid(row=0, column=0, padx=(16, 10))

        self.input = ctk.CTkTextbox(box, height=52, corner_radius=10,
                                    fg_color=SURFACE, border_width=0,
                                    text_color=TEXT, font=(UI, 13), wrap="word",
                                    activate_scrollbars=False)
        self.input.grid(row=0, column=1, sticky="ew", pady=8)
        try:
            self.input._textbox.configure(padx=12, pady=10)
        except Exception:
            pass
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Shift-Return>", self._on_shift_return)
        self.input.bind("<FocusIn>", lambda e: self._sync_placeholder())
        self.input.bind("<FocusOut>", lambda e: self._sync_placeholder())
        self.input.bind("<KeyRelease>", lambda e: self._sync_placeholder(),
                        add="+")

        # placeholder sits above the textbox (created afterwards on purpose)
        self.composer_phrase = ctk.CTkLabel(
            box, text="Ask J.A.R.V.I.S. \u2026      Enter to dispatch  \u00b7  "
                      "Shift+Enter for a new line",
            font=(UI, 12), text_color=TEXT_MUTE, anchor="w")
        self.composer_phrase.grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.composer_phrase.bind("<Button-1>", lambda e: self._focus_composer())

        self.composer_mic = ctk.CTkButton(
            box, text="", image=make_icon("mic", CYAN, 18, 1.9), width=42,
            height=42, corner_radius=13, fg_color=SURFACE_2,
            hover_color=SURFACE_3, command=self.start_voice)
        self.composer_mic.grid(row=0, column=2, padx=(10, 6))
        self.send_btn = ctk.CTkButton(
            box, text="", image=make_icon("send", BG, 18, 1.9), width=42,
            height=42, corner_radius=13, fg_color=CYAN,
            hover_color=mix(CYAN, "#FFFFFF", 0.25), command=self.send_input)
        self.send_btn.grid(row=0, column=3, padx=(0, 12))
        self.composer_mic.bind("<Enter>", lambda e: self.set_activity(
            "Capture a spoken command (Ctrl+Shift+V)"))
        self.send_btn.bind("<Enter>", lambda e: self.set_activity(
            "Dispatch the composed prompt (Enter)"))
        return wrap

    def _sync_placeholder(self):
        try:
            empty = not self.input.get("1.0", "end").strip()
        except Exception:
            empty = True
        try:
            if empty:
                self.composer_phrase.grid()
            else:
                self.composer_phrase.grid_remove()
        except Exception:
            pass

    def _focus_composer(self):
        try:
            self.input.focus_set()
        except Exception:
            pass
        self._sync_placeholder()

    def _on_return(self, event):
        self.send_input()
        return "break"

    def _on_shift_return(self, event):
        return None                       # let the text widget insert \n

    # ============================================================== RIBBON
    def _build_ribbon(self):
        bar = ctk.CTkFrame(self, fg_color=BG_1, corner_radius=0, height=30)
        bar.grid_propagate(False)
        ctk.CTkFrame(bar, fg_color=HAIRLINE, height=1, corner_radius=0).place(
            in_=bar, relx=0, rely=0, relwidth=1)

        row = ctk.CTkFrame(bar, fg_color=BG_1, corner_radius=0)
        row.pack(fill="both", expand=True, padx=18, pady=(1, 0))
        self.ribbon_dot = ctk.CTkLabel(row, text="\u25cf", font=(MONO, 9),
                                       text_color=CYAN)
        self.ribbon_dot.pack(side="left", padx=(0, 7))
        self.ribbon_engine = ctk.CTkLabel(row, text="ENGINE \u2014",
                                          font=(MONO, 8, "bold"),
                                          text_color=TEXT_DIM)
        self.ribbon_engine.pack(side="left")
        ctk.CTkLabel(row, text="|", font=(MONO, 9),
                     text_color=HAIRLINE_2).pack(side="left", padx=10)
        self.ribbon_activity = ctk.CTkLabel(row, text="Initialising",
                                            font=(MONO, 8), text_color=CYAN_DIM)
        self.ribbon_activity.pack(side="left")
        ctk.CTkLabel(
            row,
            text="Enter dispatch   \u00b7   Esc interrupt   \u00b7   Ctrl+M mute   "
                 "\u00b7   Ctrl+Shift+V voice   \u00b7   Ctrl+1..6 views   \u00b7   "
                 "Ctrl+E export   \u00b7   F1 about",
            font=(MONO, 8), text_color=TEXT_MUTE).pack(side="right")
        self.ribbon_stats = ctk.CTkLabel(row, text="", font=(MONO, 8),
                                         text_color=TEXT_MUTE)
        self.ribbon_stats.pack(side="right", padx=(0, 24))
        return bar

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

    # --------------------------------------------------------------- turn
    def _run_chat(self, user_text):
        user_text = (user_text or "").strip()
        if not user_text:
            self.from_engine.put({"_kind": "status", "state": "READY"})
            return

        self.from_engine.put({"_kind": "user", "text": user_text})
        self.from_engine.put({"_kind": "status", "state": "THINKING"})

        if not ENGINE_OK or process_user_input is None:
            self.from_engine.put({
                "_kind": "error",
                "text": "The jarvis engine is unavailable, so the language "
                        "model cannot be reached. %s" % ENGINE_ERR})
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

        # ---- personality + language routing (before the model call) --------
        personality, language, reason = None, "en", None
        try:
            personality = (detect_target_personality(clean)
                           if detect_target_personality else None)
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
        self.from_engine.put({"_kind": "intent", "text": "%s   \u2192   %s"
                              % (shorten(clean, 80),
                                 reason or "conversational turn")})

        # ---- model call ----------------------------------------------------
        t0 = time.time()
        try:
            result = process_user_input(clean, self.conversation,
                                        self.current_voice) or {}
        except Exception as exc:
            result = {}
            self.from_engine.put({"_kind": "error",
                                  "text": "Model call failed: %s" % exc})
        elapsed = int((time.time() - t0) * 1000)

        out = (result.get("response") or "").strip() or "I am on it."
        voice_out = self.current_voice
        preference = result.get("voice_preference")
        if preference and preference in VOICES and preference != self.current_voice:
            self.current_voice = preference
            voice_out = preference
            self.from_engine.put({"_kind": "voice_switch", "voice": preference,
                                  "reason": result.get("reason")
                                  or "model preference"})

        # ---- tool execution ------------------------------------------------
        tool_info = None
        tool_call = result.get("tool_call")
        if tool_call:
            name = tool_call.get("name") or "unknown_tool"
            args = tool_call.get("arguments") or {}
            self.from_engine.put({"_kind": "tool_start", "name": name,
                                  "args": args})
            try:
                tool_result = execute_function(name, args)
                ok = str(tool_result).startswith("Success")
            except Exception as exc:
                tool_result, ok = "Error: %s" % exc, False
            tool_info = {"name": name.replace("_", " "), "ok": ok,
                         "detail": shorten(tool_result, 180)}
            self.from_engine.put({"_kind": "tool_done", "name": name, "ok": ok,
                                  "text": str(tool_result)})
            if "Permission denied" not in str(tool_result):
                if ok:
                    out = "%s  Done! %s" % (
                        out, str(tool_result).replace("Success: ", ""))
                else:
                    out = "%s  %s" % (out, tool_result)

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

    def _run_capture(self, token):
        text = ""
        if VOICE_INPUT and listen_natural_fn:
            try:
                text = (listen_natural_fn() or "").strip()
            except Exception:
                text = ""
        self.from_engine.put({"_kind": "voice_result", "text": text,
                              "token": token})

    # ------------------------------------------------------------ speech
    def _speak(self, text, voice):
        self._tts_stop.clear()
        threading.Thread(target=self._tts_worker, args=(text, voice),
                         daemon=True).start()

    def _piper_play(self, text, voice, stop_event):
        """Synthesise with Piper, play it, and meter real audio amplitude."""
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
        with sd_mod.OutputStream(samplerate=rate, channels=1,
                                 dtype="int16") as stream:
            for chunk in piper_voice.synthesize(text):
                if stop_event.is_set():
                    break
                data = np_mod.frombuffer(chunk.audio_int16_bytes,
                                         dtype=np_mod.int16)
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
            self._poll_job = self.after(55, self._poll_engine)

    def _handle_message(self, msg):
        kind = msg.get("_kind")
        try:
            if kind == "engine_ready":
                self._on_engine_ready()
            elif kind == "user":
                self.last_user_text = msg.get("text", "")
                self.caption_you.configure(
                    text="YOU \u2014 " + shorten(self.last_user_text, 160))
                self._add_message("user", self.last_user_text)
            elif kind == "ai":
                self._on_ai_message(msg)
            elif kind == "status":
                self.set_state(msg.get("state", "READY"))
            elif kind == "intent":
                self.log_activity("INTENT", msg.get("text", ""))
            elif kind == "tool_start":
                self._on_tool_start(msg)
            elif kind == "tool_done":
                self.log_activity(
                    "TOOL", "%s  \u2192  %s" % (msg.get("name", "tool"),
                                               shorten(msg.get("text", ""), 140)),
                    CYAN if msg.get("ok") else RED)
            elif kind == "voice_switch":
                self.current_voice = msg.get("voice", self.current_voice)
                self._sync_voice_ui(msg.get("reason"))
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
                self.log_activity("ERROR", msg.get("text", ""))
                self._add_notice(msg.get("text", "Unknown error"))
                self.set_state("ERROR")
                self._set_typing(False)
            elif kind == "notice":
                self._add_notice(msg.get("text", ""))
        except Exception as exc:
            try:
                self.log_activity("ERROR", "UI handler failed: %s" % exc)
            except Exception:
                pass

    # ------------------------------------------------------------ handlers
    def _on_ai_message(self, msg):
        self._set_typing(False)
        self._busy = False
        text = msg.get("text", "")
        voice = msg.get("voice", self.current_voice)
        self.last_ai_text = text
        self.msg_count += 1
        try:
            self.caption_ai.configure(text=shorten(text, 230))
        except Exception:
            pass
        self._add_message("ai", text, tool=msg.get("tool"), voice=voice)
        if msg.get("user"):
            self.log_activity("MODEL", "reply composed in %.2f s"
                              % (msg.get("ms", 0) / 1000.0), GOLD)
        self._refresh_session_labels()
        if not self.tts_enabled:
            self.set_state("READY", "Standing by")

    def _on_tool_start(self, msg):
        name = msg.get("name", "tool")
        args = msg.get("args") or {}
        if isinstance(args, dict):
            detail = ", ".join("%s=%s" % (key, shorten(value, 26))
                               for key, value in list(args.items())[:4])
        else:
            detail = shorten(args, 60)
        pretty = name.replace("_", " ")
        self.set_state("BUSY", "Executing %s" % pretty)
        self._toast("Executing %s" % pretty)
        self.log_activity("TOOL", "%s(%s)" % (name, detail))

    def _on_speech_end(self):
        self._speaking = False
        self.set_state("READY", "Standing by")
        if self.handsfree and not self._busy and not self._capturing:
            self._schedule_handsfree(900)

    def _on_voice_result(self, msg):
        self._capturing = False
        if msg.get("token") != self._capture_token:
            return
        text = (msg.get("text") or "").strip()
        if text:
            self.last_user_text = text
            try:
                self.caption_you.configure(text="YOU \u2014 " + shorten(text, 160))
            except Exception:
                pass
            self.log_activity("VOICE", "Heard: %s" % shorten(text, 110))
            self.dispatch(text)
        else:
            self.set_state("READY", "No speech detected")
            self.log_activity("VOICE", "Capture finished with no transcript.")
            if self.handsfree:
                self._schedule_handsfree(1400)

    def _on_sysinfo(self, info):
        def as_pct(value):
            try:
                return float(str(value).replace("%", "").strip().split()[0])
            except Exception:
                return 0.0

        def tone(value):
            return GREEN if value < 60 else (AMBER if value < 85 else RED)

        cpu = as_pct(info.get("cpu_usage"))
        mem = as_pct(info.get("memory"))
        disk = as_pct(info.get("disk_usage"))
        self._cpu_hist.append(cpu)
        self._mem_hist.append(mem)
        try:
            for key, value in (("cpu", cpu), ("mem", mem), ("disk", disk)):
                label, bar, _colour = self.telemetry[key]
                label.configure(text="%.0f%%" % value)
                bar.set_value(value, tone(value))
            battery = str(info.get("battery", "\u2014")).replace(
                "No battery detected (desktop system)", "AC \u00b7 no cell")
            label, bar, _colour = self.telemetry["battery"]
            label.configure(text=shorten(battery, 13))
            level = as_pct(battery)
            bar.set_value(level, GREEN if level > 30 else AMBER)
        except Exception:
            pass
        try:
            self.sparkline.set_data(list(self._cpu_hist), list(self._mem_hist))
        except Exception:
            pass
        if self.view == "diagnostics":
            self.refresh_diagnostics()

    # -------------------------------------------------------- state + chrome
    def set_state(self, state, activity=None):
        if state not in STATES:
            state = "READY"
        self.status = state
        colour, _hue, caption, _speed = STATES[state]
        try:
            self.state_chip.configure(text="\u25cf  " + state, text_color=colour)
            self.presence_state.configure(text=state, text_color=colour)
            self.ribbon_dot.configure(text_color=colour)
        except Exception:
            pass
        for widget in (self.reactor, self.wave):
            try:
                widget.set_state(state)
            except Exception:
                pass
        if state == "THINKING":
            self._thinking_since = time.time()
            self._set_typing(True)
        self.set_activity(activity if activity is not None else caption)
        if state in ("READY", "ERROR", "OFFLINE"):
            self._busy = False

    def set_activity(self, text):
        self.activity = text
        try:
            self.ribbon_activity.configure(text=text)
        except Exception:
            pass

    def _sync_voice_ui(self, reason=None):
        label = PERSONA_LABEL.get(self.current_voice, "JARVIS")
        note = "Voice \u2192 %s" % label
        if reason:
            note += "   (%s)" % reason
        try:
            self.session_labels["voice"].configure(text=label.split(" \u2014")[0])
        except Exception:
            pass
        self.set_activity(note)
        self.log_activity("VOICE", note)

    def _refresh_session_labels(self):
        try:
            self.session_labels["session"].configure(
                text=hms(time.time() - self.started))
            self.session_labels["messages"].configure(text=str(self.msg_count))
            self.session_labels["tools"].configure(text=str(self.tool_count))
            self.ribbon_stats.configure(
                text="%d msgs   \u00b7   %d tools   \u00b7   %d exports   \u00b7   %s"
                     % (self.msg_count, self.tool_count, self.export_count,
                        hms(time.time() - self.started)))
        except Exception:
            pass

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
        now = _dt.datetime.now()
        try:
            self.clock_label.configure(text=now.strftime("%H:%M:%S"))
            self.date_label.configure(text=now.strftime("%A  \u00b7  %d %B %Y"))
        except Exception:
            pass
        self._refresh_session_labels()
        if not self._closing:
            self._clock_job = self.after(1000, self._tick_clock)

    # ------------------------------------------------------------- animation
    def _animate(self):
        if self._closing:
            return
        now = time.time()
        dt = min(0.12, max(0.001, now - self._last_frame))
        self._last_frame = now
        try:
            self.reactor.tick(dt, self._current_amp(now))
            self.wave.tick(dt, self._amp_hist if self.status == "SPEAKING"
                           else None)
        except Exception:
            pass

        if self.status == "LISTENING" and now - self._last_ripple > 1.15:
            self._last_ripple = now
            try:
                self.reactor.push_ripple()
            except Exception:
                pass

        if self._typing:
            self._typing_phase += 1
            dots = "." * (1 + (self._typing_phase // 6) % 3)
            elapsed = now - (self._thinking_since or now)
            try:
                self.typing_label.configure(
                    text="thinking%s   %.1f s" % (dots, max(0.0, elapsed)))
            except Exception:
                pass

        if not self._closing:
            self._anim_job = self.after(33, self._animate)

    def _current_amp(self, now):
        if self.status == "SPEAKING":
            recent = [value for value in list(self._amp_hist)[-8:] if value >= 0]
            base = max(recent) if recent else 0.16
            return min(1.0, 0.28 + base * 0.9)
        return 0.05 + 0.03 * (0.5 + 0.5 * math.sin(now * 1.6))

    # ============================================================== ACTIONS
    def dispatch(self, text):
        text = (text or "").strip()
        if not text:
            return
        self._busy = True
        self.set_state("THINKING", "Reasoning over your request")
        self.to_engine.put({"_kind": "chat", "text": text})

    def send_input(self):
        try:
            text = self.input.get("1.0", "end").strip()
        except Exception:
            text = ""
        if not text:
            self._toast("Compose a command first")
            return
        try:
            self.input.delete("1.0", "end")
        except Exception:
            pass
        self._sync_placeholder()
        self.dispatch(text)

    def start_voice(self):
        if not VOICE_INPUT:
            self._add_notice("Voice input is unavailable \u2014 %s"
                             % (SR_ERROR or ENGLISH_ONLY_NOTE))
            self._toast("Microphone unavailable")
            return
        if self._capturing:
            self._toast("Already listening")
            return
        if self._speaking:
            self.stop_speaking()
        self._capture_token += 1
        self._capturing = True
        self.set_state("LISTENING", "Listening \u2014 speak now")
        try:
            self.reactor.push_ripple()
        except Exception:
            pass
        self.log_activity("VOICE", "Microphone armed \u2014 natural VAD capture.")
        self.to_engine.put({"_kind": "voice_capture",
                            "token": self._capture_token})

    def stop_speaking(self):
        if self._speaking or self.status == "SPEAKING":
            self._tts_stop.set()
            self.set_activity("Playback interrupted")
            self._toast("Speech interrupted")
            self.log_activity("VOICE", "Playback interrupted by the user.")
        elif self._capturing:
            self._capture_token += 1
            self._capturing = False
            self.set_state("READY", "Capture cancelled")
            self.log_activity("VOICE", "Voice capture cancelled.")
        else:
            self.set_activity("Nothing to interrupt")

    def toggle_mute(self):
        self.tts_enabled = not self.tts_enabled
        if not self.tts_enabled and self._speaking:
            self._tts_stop.set()
        try:
            self.mute_btn.configure(image=make_icon(
                "speaker" if self.tts_enabled else "mute",
                CYAN_DIM if self.tts_enabled else TEXT_MUTE, 19, 1.8))
        except Exception:
            pass
        self._toast("Voice " + ("enabled" if self.tts_enabled else "muted"))
        self.set_activity("Spoken replies %s"
                          % ("enabled" if self.tts_enabled else "muted"))
        self.log_activity("VOICE", "Voice output %s."
                          % ("enabled" if self.tts_enabled else "muted"))

    def toggle_handsfree(self):
        if not VOICE_INPUT:
            self._add_notice("Hands-free mode needs a working microphone. %s"
                             % (SR_ERROR or ENGLISH_ONLY_NOTE))
            self._toast("Microphone unavailable")
            return
        self.handsfree = not self.handsfree
        colour = CYAN if self.handsfree else TEXT_MUTE
        for button, size in ((getattr(self, "handsfree_btn", None), 19),
                             (getattr(self, "hf_big_btn", None), 17)):
            if button is None:
                continue
            try:
                button.configure(image=make_icon("broadcast", colour, size, 1.9))
            except Exception:
                pass
        try:
            self.hf_hint.configure(
                text="HANDS-FREE ON" if self.handsfree else "HANDS-FREE",
                text_color=CYAN if self.handsfree else TEXT_MUTE)
        except Exception:
            pass
        self._toast("Hands-free " + ("enabled" if self.handsfree else "disabled"))
        self.log_activity("VOICE", "Hands-free mode %s."
                          % ("enabled" if self.handsfree else "disabled"))
        if self.handsfree and not (self._busy or self._speaking or self._capturing):
            self._schedule_handsfree(600)
        elif not self.handsfree and self._handsfree_job:
            try:
                self.after_cancel(self._handsfree_job)
            except Exception:
                pass
            self._handsfree_job = None

    def clear_conversation(self):
        for child in self.chat_inner.winfo_children():
            if child is self.typing_card:
                continue
            try:
                child.destroy()
            except Exception:
                pass
        alive = []
        for label in self._wrap_labels:
            try:
                if label.winfo_exists():
                    alive.append(label)
            except Exception:
                pass
        self._wrap_labels = alive
        self.conversation = []
        self.chat_row = 0
        self.msg_count = 0
        self.tool_count = 0
        self._first_message_done = False
        self.intro_card = self._conv_intro(self.chat_inner)
        self._restack_typing()
        self._refresh_session_labels()
        self.log_activity("SYSTEM", "Conversation cleared \u2014 history reset.")
        self._toast("Conversation cleared")

    def export_conversation(self):
        if not self.conversation:
            self._toast("Nothing to export yet")
            return
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(OUTPUT_DIR, "jarvis_session_%s.md" % stamp)
            lines = [
                "# J.A.R.V.I.S \u2014 Session Transcript",
                "",
                "Exported: %s" % _dt.datetime.now().strftime("%d %b %Y %H:%M:%S"),
                "Voice: %s" % PERSONA_LABEL.get(self.current_voice, "\u2014"),
                "Turns: %d" % (len(self.conversation) // 2),
                "",
                "---",
                "",
            ]
            for entry in self.conversation:
                speaker = "**You**" if entry.get("role") == "user" \
                    else "**J.A.R.V.I.S.**"
                lines.append("%s: %s" % (speaker, entry.get("content", "")))
                lines.append("")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            self.export_count += 1
            self._refresh_session_labels()
            self.log_activity("SYSTEM", "Transcript exported \u2192 %s"
                              % os.path.basename(path))
            self._toast("Exported to generated_files")
            if self.view == "deliverables":
                self.refresh_deliverables()
        except Exception as exc:
            self._toast("Export failed")
            self.log_activity("ERROR", "Export failed: %s" % exc)

    def open_path(self, path):
        try:
            os.startfile(path)                       # Windows shell open
        except AttributeError:
            try:
                webbrowser.open("file://" + os.path.abspath(path))
            except Exception as exc:
                self._toast("Could not open that path")
                self.log_activity("ERROR", "Open failed: %s" % exc)
        except Exception as exc:
            self._toast("Could not open that path")
            self.log_activity("ERROR", "Open failed: %s" % exc)

    # ---------------------------------------------------------------- chrome
    def _toast(self, text):
        if self._closing:
            return
        try:
            if self._toast_widget is not None:
                self._toast_widget.destroy()
        except Exception:
            pass
        try:
            widget = ctk.CTkLabel(self, text=text, font=(MONO, 9, "bold"),
                                  text_color=BG, fg_color=CYAN,
                                  corner_radius=10, padx=18, pady=9)
            widget.place(relx=0.985, rely=0.155, anchor="ne")
            self._toast_widget = widget
            if not self._closing:
                self._toast_job = self.after(2400, lambda: self._clear_toast(widget))
        except Exception:
            pass

    def _clear_toast(self, widget):
        try:
            widget.destroy()
        except Exception:
            pass
        if self._toast_widget is widget:
            self._toast_widget = None

    def _show_shortcuts(self):
        self._toast("Enter send  \u00b7  Esc interrupt  \u00b7  Ctrl+M mute  \u00b7  "
                    "F1 about")
        self.log_activity(
            "SYSTEM",
            "Keyboard \u2014 Enter send \u00b7 Shift+Enter newline \u00b7 Esc interrupt "
            "\u00b7 Ctrl+M mute \u00b7 Ctrl+Shift+V voice \u00b7 Ctrl+L clear \u00b7 "
            "Ctrl+E export \u00b7 Ctrl+1..6 views \u00b7 F1 about")

    def _bind_keys(self):
        def consume(action):
            def handler(event=None):
                try:
                    action()
                except Exception:
                    pass
                return "break"
            return handler

        bindings = {
            "<Control-Return>": self.send_input,
            "<Escape>": self.stop_speaking,
            "<F1>": self._show_shortcuts,
            "<Control-l>": self.clear_conversation,
            "<Control-L>": self.clear_conversation,
            "<Control-e>": self.export_conversation,
            "<Control-E>": self.export_conversation,
            "<Control-m>": self.toggle_mute,
            "<Control-M>": self.toggle_mute,
            "<Control-Shift-V>": self.start_voice,
            "<Control-Shift-v>": self.start_voice,
            "<Control-f>": self._focus_composer,
            "<Control-F>": self._focus_composer,
        }
        for index, (key, _kind, _label) in enumerate(RAIL_ITEMS, start=1):
            bindings["<Control-Key-%d>" % index] = (
                lambda k=key: self.show_view(k))
        for sequence, action in bindings.items():
            try:
                self.bind(sequence, consume(action), add="+")
            except Exception:
                pass

    def _on_close(self):
        self._closing = True
        self.handsfree = False
        for job_attr in ("_handsfree_job", "_poll_job", "_anim_job",
                         "_clock_job", "_boot_poll_job", "_shutter_job",
                         "_toast_job"):
            job = getattr(self, job_attr, None)
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, job_attr, None)
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

    # ========================================================= BOOT SHUTTER
    def _build_boot_overlay(self):
        overlay = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay = overlay

        centre = ctk.CTkFrame(overlay, fg_color=BG, corner_radius=0)
        centre.place(relx=0.5, rely=0.5, anchor="center")

        viewport = ctk.CTkFrame(centre, fg_color=SURFACE, corner_radius=16,
                                border_width=1, border_color=HAIRLINE_2)
        viewport.grid(row=0, column=0, pady=(0, 20))
        self.boot_reactor = ReactorCanvas(viewport, size=260)
        self.boot_reactor.set_state("BOOT")
        self.boot_reactor.grid(row=0, column=0, padx=16, pady=16)
        self.boot_video_canvas = tk.Canvas(viewport, width=440, height=40,
                                           bg=SURFACE, highlightthickness=0,
                                           bd=0, takefocus=0)

        ctk.CTkLabel(centre, text="J.A.R.V.I.S", font=(DISPLAY, 30, "bold"),
                     text_color=TEXT).grid(row=1, column=0)
        ctk.CTkLabel(centre, text="ARC INTERFACE   \u00b7   COLD START",
                     font=(MONO, 8), text_color=TEXT_MUTE).grid(
            row=2, column=0, pady=(3, 16))

        self.boot_log = ctk.CTkLabel(centre, text="", font=(MONO, 9),
                                     text_color=TEXT_DIM, justify="left",
                                     anchor="w", wraplength=540)
        self.boot_log.grid(row=3, column=0, sticky="w", pady=(0, 14))

        self.boot_progress = tk.Canvas(centre, width=520, height=4, bg=BG,
                                       highlightthickness=0, bd=0, takefocus=0)
        self.boot_progress.grid(row=4, column=0)
        self.boot_status = ctk.CTkLabel(centre, text="INITIALISING \u2026",
                                        font=(MONO, 8, "bold"), text_color=CYAN)
        self.boot_status.grid(row=5, column=0, pady=(12, 0))

        threading.Thread(target=self._boot_load_video, daemon=True).start()
        return overlay

    def _boot_load_video(self):
        """Decode jarvis/Loading.mp4 for the boot viewport (best effort)."""
        try:
            video = _find_video()
            if not video:
                return
            frames = _extract_frames(video, target_w=460, max_frames=110)
            if frames:
                self._boot_frames = frames
        except Exception:
            self._boot_frames = []

    def _boot_poll(self):
        if self._closing:
            return
        elapsed = time.time() - self._boot_t0
        for delay, note in BOOT_STEPS:
            if elapsed >= delay and note not in self._boot_logs:
                self._boot_logs.append(note)
                self._render_boot_log()

        progress = 1.0 if self._engine_ready else min(0.94, elapsed / 6.5)
        self._draw_boot_progress(progress)
        try:
            self.boot_reactor.tick(0.08, 0.12 + 0.10 * math.sin(elapsed * 2.0))
        except Exception:
            pass
        self._boot_pump()

        if self._engine_ready:
            try:
                self.boot_status.configure(
                    text="SYSTEM ONLINE \u2014 welcome back, sir."
                    if ENGINE_OK else "ENGINE UNAVAILABLE \u2014 demo mode",
                    text_color=GREEN if ENGINE_OK else RED)
            except Exception:
                pass
        if self._engine_ready and elapsed >= MIN_BOOT_SECONDS:
            self._start_shutter()
            return
        if not self._closing:
            self._boot_poll_job = self.after(80, self._boot_poll)

    def _boot_pump(self):
        frames = self._boot_frames
        if not frames or self._closing:
            return
        if not self._boot_video_shown:
            try:
                self.boot_reactor.grid_forget()
                width, height = frames[0].size
                self.boot_video_canvas.configure(width=width, height=height)
                self.boot_video_canvas.grid(row=0, column=0, padx=16, pady=16)
                self._boot_video_shown = True
            except Exception:
                return
        index = self._boot_video_index % len(frames)
        self._boot_video_index += 1
        try:
            photo = ImageTk.PhotoImage(frames[index])
            self.boot_video_canvas.delete("all")
            self.boot_video_canvas.create_image(0, 0, image=photo, anchor="nw")
            self._boot_video_photo = photo
        except Exception:
            pass

    def _render_boot_log(self):
        try:
            self.boot_log.configure(text="\n".join(self._boot_logs))
        except Exception:
            pass

    def _draw_boot_progress(self, fraction):
        try:
            canvas = self.boot_progress
            canvas.delete("all")
            width = 520
            fraction = max(0.0, min(1.0, fraction))
            canvas.create_rectangle(0, 0, width, 4, fill=HAIRLINE, outline="")
            if fraction > 0:
                canvas.create_rectangle(0, 0, width * fraction, 4,
                                        fill=CYAN, outline="")
        except Exception:
            pass

    def _start_shutter(self):
        if self._boot_closing:
            return
        self._boot_closing = True
        steps = 14

        def step(index=0):
            index += 1
            fraction = max(0.0, 1.0 - index / float(steps))
            try:
                self.overlay.place_configure(relx=0, rely=0, relwidth=1,
                                             relheight=fraction)
            except Exception:
                pass
            if index >= steps:
                try:
                    self.overlay.destroy()
                except Exception:
                    pass
                self.overlay = None
                self._boot_done()
            else:
                if not self._closing:
                    self._shutter_job = self.after(22, lambda: step(index))

        step()

    def _boot_done(self):
        if ENGINE_OK:
            self.set_state("READY", "Standing by")
            self.log_activity(
                "SYSTEM", "Engine ready in %.2f s \u2014 %d callable functions, "
                          "%d local voices."
                % (ENGINE_LOAD_MS / 1000.0, len(FUNCTION_MAP),
                   len(engine_get("voice_engines", {}) or {})))
            greeting = "System Online. Welcome back sir."
            self.msg_count += 1
            self.last_ai_text = greeting
            try:
                self.caption_ai.configure(text=greeting)
            except Exception:
                pass
            self._add_message("ai", greeting, voice=self.current_voice)
            self._refresh_session_labels()
            if self.tts_enabled:
                self._speak(greeting, self.current_voice)
        else:
            self.set_state("OFFLINE", "Engine offline \u2014 demo mode")
            self.log_activity("ERROR", "Engine load failed: %s" % ENGINE_ERR)
            self._add_notice(
                "The jarvis engine could not be loaded, so replies are "
                "unavailable. %s" % ENGINE_ERR)
        self._toast("J.A.R.V.I.S. ready")
        self._focus_composer()

    def _on_engine_ready(self):
        try:
            self.ribbon_engine.configure(
                text="ENGINE " + ("ONLINE" if ENGINE_OK else "OFFLINE"),
                text_color=TEXT_DIM if ENGINE_OK else RED)
        except Exception:
            pass
        self.refresh_diagnostics()


# ==========================================================================
# BOOT SEQUENCE COPY
# ==========================================================================
MIN_BOOT_SECONDS = 3.2

BOOT_STEPS = (
    (0.00, "spoken: cold start accepted"),
    (0.45, "arc reactor  \u00b7  core stable  \u00b7  rings nominal"),
    (1.05, "mounting Piper neural voices  (en \u00b7 hi)"),
    (1.85, "uplink: language-model provider chain"),
    (2.55, "registering local toolchain"),
)

SHORTCUTS = (
    ("Enter / Ctrl+Enter", "Dispatch the composed prompt"),
    ("Shift+Enter", "Insert a new line in the composer"),
    ("Esc", "Interrupt speech or cancel a voice capture"),
    ("Ctrl+M", "Mute or unmute spoken replies"),
    ("Ctrl+Shift+V", "Start a voice capture"),
    ("Ctrl+E", "Export the transcript to generated_files"),
    ("Ctrl+L", "Clear the conversation and history"),
    ("Ctrl+1 \u2026 Ctrl+6", "Switch workspace views"),
    ("F1", "Show the shortcut list"),
)

STACK = (
    "Python", "CustomTkinter", "Tkinter canvas animation",
    "Pillow raster icons", "jarvis.py engine", "Piper neural TTS (local)",
    "Groq \u00b7 Cerebras \u00b7 Gemini provider chain",
    "SpeechRecognition + sounddevice VAD", "psutil telemetry",
    "python-docx", "python-pptx", "Pexels imagery",
)


# ==========================================================================
# BOOT VIDEO (jarvis/Loading.mp4) — optional flourish
# ==========================================================================
VIDEO_CANDIDATES = (
    os.path.join(BASE_DIR, "jarvis", "Loading.mp4"),
    os.path.join(BASE_DIR, "Loading.mp4"),
)


def _find_video():
    for path in VIDEO_CANDIDATES:
        if os.path.isfile(path):
            return path
    folder = os.path.join(BASE_DIR, "jarvis")
    try:
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".mp4", ".avi", ".mov", ".webm", ".mkv")):
                return os.path.join(folder, name)
    except Exception:
        pass
    return None


def _extract_frames(video_path, target_w=460, max_frames=110):
    """Sample and downscale frames from the loading video (best effort)."""
    if not PIL_OK:
        return []
    try:
        import imageio.v2 as imageio
        reader = imageio.get_reader(video_path)
        try:
            total = min(int(reader.count_frames()), max_frames)
        except Exception:
            total = max_frames
        step = max(1, total // 100)
        frames = []
        for index in range(0, total, step):
            try:
                array = reader.get_data(index)
            except Exception:
                break
            image = Image.fromarray(array).convert("RGB")
            width, height = image.size
            if width > target_w:
                image = image.resize((target_w, int(height * target_w / width)),
                                     RESAMPLE_BILINEAR)
            frames.append(image)
        try:
            reader.close()
        except Exception:
            pass
        return frames
    except Exception:
        return []


# ==========================================================================
# ENTRY POINT
# ==========================================================================
def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    try:
        app = JarvisInterface()
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
