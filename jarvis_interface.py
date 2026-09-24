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
    img = img.resize((size, size), Image.LANCZOS)
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
