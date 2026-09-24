#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. — HUD GUI  (jarvis_gui.py)
================================================================================
A full-screen, Iron-Man-style holographic HUD front end for the local
`jarvis.py` engine. Visually modelled on a "SHIELD OS" style overlay:
a black backdrop, a large cyan targeting reactor in the centre, a stacked
pill navigation rail top-left, a digital clock block, small telemetry
gauges (CPU / memory / disk) styled as dashboard dials, and a bottom
command bar for typed or spoken commands.

Every control is wired to the real `jarvis.py` engine — nothing here is
decorative-only:

    • Conversation      -> process_user_input() -> execute_function() -> TTS
    • Capabilities       -> live catalogue of FUNCTION_MAP / AVAILABLE_TOOLS
    • Activity            -> real-time intent / tool-call / voice timeline
    • Deliverables       -> browses generated_files/
    • Diagnostics         -> psutil telemetry + provider + voice-stack status
    • Mic / Hands-free   -> SoundDeviceMicrophone + NaturalVoiceListener
    • Speak / Stop       -> Piper TTS with live amplitude metering that
                             drives the reactor's animation in real time

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
# THEME — matte black HUD, cyan targeting reticle, amber/green accents
# ==========================================================================
BG          = "#000000"
PANEL       = "#040A10"
PANEL_2     = "#071018"
HAIRLINE    = "#0E2430"
HAIRLINE_2  = "#164256"
CYAN        = "#37E9FF"
CYAN_DIM    = "#12657A"
CYAN_FAINT  = "#0B3A48"
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
    "BOOT":      (CYAN,  "Initialising systems",            2.2),
    "READY":     (CYAN,  "Standing by",                      0.30),
    "LISTENING": (GREEN, "Listening",                         2.4),
    "THINKING":  (AMBER, "Reasoning",                         3.6),
    "BUSY":      (AMBER, "Executing tool",                    3.2),
    "SPEAKING":  (CYAN,  "Speaking",                          1.5),
    "OFFLINE":   (RED,   "Engine offline",                    0.2),
    "ERROR":     (RED,   "Recovered from error",              0.2),
}

EXIT_WORDS = {"exit", "quit", "bye", "goodbye", "shutdown", "stop"}
PERSONA_LABEL = {"en_male": "JARVIS — EN", "hi_male": "JARVIS — HI",
                 "en_female": "SIMMI — EN"}
REPO_URL = "https://github.com/rajatrajdav/Local_AI-assistant"
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_files")

# ---------------------------------------------------------------- engine API
_engine = None
ENGINE_OK = False
ENGINE_ERR = "Engine has not been loaded yet."
ENGINE_LOAD_MS = 0
VOICES = {
    "en_male":   {"name": "English Male (Medium)", "language": "en"},
    "hi_male":   {"name": "Hindi Male (Pratham)",   "language": "hi"},
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
# Colour helpers
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
# ICONS — small stroked vector glyphs (Pillow supersampled)
# ==========================================================================
_ICON_CACHE = {}


def _draw_icon(d, kind, S, colour, w):
    def pts(*c):
        return [(S * x / 100.0, S * y / 100.0) for x, y in c]

    def line(*c, width=None):
        d.line(pts(*c), fill=colour, width=width or w, joint="curve")

    def circ(cx, cy, r, width=None, fill=False):
        rect = [S * (cx - r) / 100.0, S * (cy - r) / 100.0,
                S * (cx + r) / 100.0, S * (cy + r) / 100.0]
        if fill:
            d.ellipse(rect, fill=colour)
        else:
            d.ellipse(rect, outline=colour, width=width or w)

    def box(x0, y0, x1, y1, radius=0, width=None, fill=False):
        rect = [S * x0 / 100.0, S * y0 / 100.0, S * x1 / 100.0, S * y1 / 100.0]
        r = S * radius / 100.0
        if fill:
            d.rounded_rectangle(rect, radius=r, fill=colour)
        else:
            d.rounded_rectangle(rect, radius=r, outline=colour, width=width or w)

    def arc(cx, cy, r, a0, a1, width=None):
        rect = [S * (cx - r) / 100.0, S * (cy - r) / 100.0,
                S * (cx + r) / 100.0, S * (cy + r) / 100.0]
        d.arc(rect, start=a0, end=a1, fill=colour, width=width or w)

    if kind == "chat":
        box(12, 16, 88, 66, radius=15)
        line((30, 66), (30, 86), (50, 66))
        for cx in (36, 50, 64):
            circ(cx, 41, 4, fill=True)
    elif kind == "layers":
        box(12, 12, 46, 46, radius=7); box(54, 12, 88, 46, radius=7)
        box(12, 54, 46, 88, radius=7); box(54, 54, 88, 88, radius=7)
    elif kind == "pulse":
        line((8, 58), (28, 58), (38, 24), (50, 80), (62, 38), (72, 58), (92, 58))
    elif kind == "folder":
        box(8, 26, 92, 86, radius=9)
        line((8, 26), (8, 18), (36, 18), (46, 26))
    elif kind == "gauge":
        arc(50, 62, 33, 160, 380); line((50, 62), (74, 36)); circ(50, 62, 3, fill=True)
    elif kind == "info":
        circ(50, 50, 37); circ(50, 32, 3.6, fill=True); line((50, 44), (50, 70))
    elif kind == "mic":
        box(36, 10, 64, 56, radius=14); arc(50, 44, 27, 6, 174)
        line((50, 71), (50, 86)); line((35, 86), (65, 86))
    elif kind == "stop":
        box(27, 27, 73, 73, radius=7, fill=True)
    elif kind == "send":
        d.polygon(pts((10, 50), (90, 12), (58, 90), (46, 58)), fill=colour)
    elif kind == "speaker":
        d.polygon(pts((16, 38), (34, 38), (56, 18), (56, 82), (34, 62), (16, 62)), fill=colour)
        arc(50, 50, 20, 300, 60)
    elif kind == "mute":
        d.polygon(pts((14, 38), (32, 38), (54, 18), (54, 82), (32, 62), (14, 62)), fill=colour)
        line((68, 38), (90, 62)); line((90, 38), (68, 62))
    elif kind == "broadcast":
        circ(50, 66, 7, fill=True); arc(50, 66, 24, 195, 345); arc(50, 66, 40, 205, 335)
    elif kind == "export":
        line((50, 74), (50, 16)); line((33, 33), (50, 16), (67, 33))
        line((20, 58), (20, 86), (80, 86), (80, 58))
    elif kind == "refresh":
        arc(50, 50, 33, 34, 326); d.polygon(pts((82, 30), (66, 30), (78, 46)), fill=colour)
    elif kind == "trash":
        line((20, 28), (80, 28)); line((39, 28), (39, 14), (61, 14), (61, 28))
        line((29, 28), (36, 88), (64, 88), (71, 28))
        line((43, 40), (46, 76)); line((57, 40), (54, 76))
    elif kind == "chip":
        box(26, 26, 74, 74, radius=6); box(41, 41, 59, 59, radius=3)
        for c in (34, 50, 66):
            line((c, 12), (c, 26)); line((c, 74), (c, 88))
            line((12, c), (26, c)); line((74, c), (88, c))
    elif kind == "eye":
        d.polygon(pts((10, 50), (32, 30), (68, 30), (90, 50), (68, 70), (32, 70)), outline=colour)
        circ(50, 50, 9)
    elif kind == "terminal":
        box(8, 16, 92, 84, radius=8)
        line((24, 34), (40, 50), (24, 66)); line((50, 66), (74, 66))
    elif kind == "core":
        circ(50, 50, 36); circ(50, 50, 23); circ(50, 50, 11, fill=True)
        for i in range(8):
            ang = math.radians(i * 45)
            line((50 + 27 * math.cos(ang), 50 + 27 * math.sin(ang)),
                 (50 + 34 * math.cos(ang), 50 + 34 * math.sin(ang)))
    elif kind == "close":
        line((26, 26), (74, 74)); line((74, 26), (26, 74))
    elif kind == "power":
        arc(50, 50, 30, 300, 60); line((50, 14), (50, 52))


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
        _draw_icon(draw, kind, S, _rgb(colour), max(1, int(round(stroke * scale))))
    except Exception:
        pass
    img = img.resize((size, size), RESAMPLE_LANCZOS)
    icon = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = icon
    return icon


# ==========================================================================
# WIDGET — central HUD reactor (targeting-reticle style, state + amplitude
# reactive), matching the reference image's layered ring composition.
# ==========================================================================
class HUDReactor(tk.Canvas):
    def __init__(self, master, size=460, **kwargs):
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
        self.size = max(160, min(event.width, event.height))

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

        # dense cyan tick collar (inner)
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


class DialGauge(tk.Canvas):
    """Car-dashboard style arc dial (CPU / MEM / DISK style readouts)."""

    def __init__(self, master, size=96, label="", colour=CYAN, **kwargs):
        super().__init__(master, width=size, height=size, bg=PANEL,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.size = size
        self.label = label
        self.colour = colour
        self.value = 0.0
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.size = max(50, min(event.width, event.height))
        self._redraw()

    def set_value(self, pct):
        self.value = max(0.0, min(100.0, pct))
        self._redraw()

    def _redraw(self):
        try:
            self.delete("all")
        except tk.TclError:
            return
        S = self.size
        cx = cy = S / 2.0
        R = S * 0.42
        start, extent = 130, 280
        self.create_arc(cx - R, cy - R, cx + R, cy + R, start=start, extent=extent,
                        style="arc", outline=HAIRLINE_2, width=5)
        sweep = extent * (self.value / 100.0)
        self.create_arc(cx - R, cy - R, cx + R, cy + R, start=start, extent=sweep,
                        style="arc", outline=self.colour, width=5)
        for i in range(11):
            ang = math.radians(start + extent * i / 10.0)
            r0, r1 = R + 5, R + (11 if i % 5 == 0 else 8)
            self.create_line(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang),
                             cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                             fill=HAIRLINE_2, width=1)
        self.create_text(cx, cy - 2, text="%.0f%%" % self.value,
                         fill=TEXT, font=(MONO, max(8, int(S * 0.15)), "bold"))
        self.create_text(cx, cy + S * 0.24, text=self.label,
                         fill=TEXT_MUTE, font=(MONO, max(6, int(S * 0.08))))


class ArcMeter(tk.Canvas):
    """Bottom-left green ring meter, e.g. 'DISK 46%' like the reference art."""

    def __init__(self, master, size=118, label="DISK", colour=GREEN, **kwargs):
        super().__init__(master, width=size, height=size, bg=BG,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.size = size
        self.label = label
        self.colour = colour
        self.value = 0.0
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.size = max(50, min(event.width, event.height))
        self._redraw()

    def set_value(self, pct):
        self.value = max(0.0, min(100.0, pct))
        self._redraw()

    def _redraw(self):
        try:
            self.delete("all")
        except tk.TclError:
            return
        S = self.size
        cx = cy = S / 2.0
        R = S * 0.44
        self.create_oval(cx - R, cy - R, cx + R, cy + R, outline=HAIRLINE_2, width=3)
        sweep = 360.0 * (self.value / 100.0)
        self.create_arc(cx - R, cy - R, cx + R, cy + R, start=90, extent=-sweep,
                        style="arc", outline=self.colour, width=6)
        self.create_text(cx, cy - 4, text="%.0f%%" % self.value, fill=TEXT,
                         font=(MONO, max(8, int(S * 0.15)), "bold"))
        self.create_text(cx, cy + S * 0.22, text=self.label, fill=TEXT_MUTE,
                         font=(MONO, max(6, int(S * 0.09))))


CAPABILITY_GROUPS = (
    ("DOCUMENTS & CREATION", (
        ("create_word_document", "Builds a formatted .docx from a title and body content."),
        ("create_presentation", "Generates a .pptx slide deck — professional or Pexels creative engine."),
        ("create_resume", "Produces a structured r\u00e9sum\u00e9 with experience, education, skills."),
        ("create_file", "Writes plain-text notes or any text payload into generated_files/."),
    )),
    ("SYSTEM CONTROL", (
        ("open_application", "Launches desktop applications and websites by name."),
        ("execute_system_command", "Runs a CLI command and returns stdout (destructive commands blocked)."),
        ("list_running_processes", "Lists live processes, optionally filtered by name."),
        ("take_screenshot", "Captures the screen and stores a PNG in generated_files/."),
        ("write_to_clipboard", "Copies arbitrary text to the system clipboard."),
    )),
    ("INTELLIGENCE & RESEARCH", (
        ("search_web", "DuckDuckGo search returning summarised top results."),
        ("search_files_on_computer", "Finds files by name or pattern beneath a directory."),
        ("read_file_content", "Reads a text file and returns its contents."),
        ("get_system_info", "Reports CPU, memory, disk, battery and GPU telemetry."),
        ("get_current_time", "Returns the current date and time."),
        ("calculate", "Evaluates mathematical expressions safely."),
    )),
)

RAIL_ITEMS = (
    ("conversation", "chat", "CONVERSATION"),
    ("capabilities", "layers", "CAPABILITIES"),
    ("activity", "pulse", "ACTIVITY"),
    ("deliverables", "folder", "DELIVERABLES"),
    ("diagnostics", "gauge", "DIAGNOSTICS"),
    ("about", "info", "ABOUT"),
)


# ==========================================================================
# THE APPLICATION
# ==========================================================================
class JarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("J.A.R.V.I.S \u2014 HUD")
        self.geometry("1440x900")
        self.minsize(1180, 760)
        self.configure(fg_color=BG)

        # ---- session state ----
        self.conversation = []
        self.current_voice = "en_male"
        self.tts_enabled = True
        self.handsfree = False
        self.status = "BOOT"
        self.started = time.time()
        self.msg_count = 0
        self.tool_count = 0
        self.export_count = 0
        self.sys_info = {}
        self.view = "hud"          # "hud" or one of RAIL_ITEMS keys (overlay)

        self._busy = False
        self._speaking = False
        self._capturing = False
        self._closing = False
        self._engine_ready = False
        self._boot_t0 = time.time()
        self._last_frame = time.time()
        self._capture_token = 0
        self._thinking_since = 0.0
        self._handsfree_job = None
        self._wrap_labels = []
        self._activity_rows = []
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

        # The HUD-only screen looks great but hides every reply/error inside
        # a panel the user has to know to click open. Show the transcript by
        # default so replies, tool results and any boot problems are visible
        # immediately instead of appearing to "do nothing".
        self.after(50, lambda: self.show_view("conversation"))

    # ------------------------------------------------------------- layout
    def _build_layout(self):
        # Root canvas backdrop (pure black, HUD drawn on top with place())
        self.backdrop = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ---- centre HUD reactor ----
        self.reactor_holder = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.reactor_holder.place(relx=0.5, rely=0.5, anchor="center",
                                  relwidth=0.62, relheight=0.86)
        self.reactor = HUDReactor(self.reactor_holder, size=520)
        self.reactor.pack(fill="both", expand=True)
        self.reactor.bind("<Configure>", lambda e: None)

        # caption under reactor centre
        self.caption = ctk.CTkLabel(self, text=STATES["BOOT"][1], font=(UI, 13),
                                    text_color=TEXT, fg_color=BG)
        self.caption.place(relx=0.5, rely=0.855, anchor="center")
        self.subcaption = ctk.CTkLabel(self, text="", font=(MONO, 9),
                                       text_color=TEXT_MUTE, fg_color=BG,
                                       wraplength=560)
        self.subcaption.place(relx=0.5, rely=0.895, anchor="center")

        # ---- top-left: brand + nav pill rail ----
        top_left = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        top_left.place(relx=0.012, rely=0.015, anchor="nw")
        brand = ctk.CTkFrame(top_left, fg_color=PANEL, corner_radius=8,
                             border_width=1, border_color=HAIRLINE_2)
        brand.pack(anchor="w")
        ctk.CTkLabel(brand, text="  J.A.R.V.I.S", font=(DISPLAY, 15, "bold"),
                     text_color=CYAN).pack(anchor="w", padx=8, pady=(6, 0))
        self.brand_state = ctk.CTkLabel(brand, text="MARK III \u00b7 BOOT",
                                        font=(MONO, 8), text_color=TEXT_MUTE)
        self.brand_state.pack(anchor="w", padx=8, pady=(0, 6))
        self.brand_bar = tk.Canvas(brand, width=150, height=3, bg=PANEL,
                                   highlightthickness=0, bd=0)
        self.brand_bar.pack(padx=8, pady=(0, 8))

        self.rail_buttons = {}
        rail = ctk.CTkFrame(top_left, fg_color=BG, corner_radius=0)
        rail.pack(anchor="w", pady=(10, 0))
        for key, kind, label in RAIL_ITEMS:
            pill = ctk.CTkButton(
                rail, text="  " + label, image=make_icon(kind, TEXT_DIM, 14, 1.8),
                compound="left", anchor="w", font=(MONO, 9, "bold"),
                width=150, height=30, corner_radius=15, fg_color=PANEL,
                hover_color=PANEL_2, border_width=1, border_color=HAIRLINE_2,
                text_color=TEXT_DIM, command=lambda k=key: self.show_view(k))
            pill.pack(anchor="w", pady=3)
            self.rail_buttons[key] = pill

        # ---- top-left-under-rail: clock block ----
        clock_box = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        clock_box.place(relx=0.012, rely=0.40, anchor="w")
        self.date_label = ctk.CTkLabel(clock_box, text="", font=(MONO, 10),
                                       text_color=TEXT_MUTE)
        self.date_label.pack(anchor="w")
        self.clock_label = ctk.CTkLabel(clock_box, text="--:--", font=(DISPLAY, 30, "bold"),
                                        text_color=TEXT)
        self.clock_label.pack(anchor="w")
        self.session_label = ctk.CTkLabel(clock_box, text="SESSION 00:00",
                                          font=(MONO, 9), text_color=CYAN_DIM)
        self.session_label.pack(anchor="w", pady=(2, 0))

        # ---- top-right: quick toggles + state chip ----
        top_right = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        top_right.place(relx=0.988, rely=0.015, anchor="ne")
        icon_row = ctk.CTkFrame(top_right, fg_color=BG, corner_radius=0)
        icon_row.pack(anchor="e")
        self.mute_btn = ctk.CTkButton(icon_row, text="", image=make_icon("speaker", CYAN_DIM, 15, 1.8),
                                      width=32, height=28, corner_radius=8, fg_color=PANEL,
                                      hover_color=PANEL_2, command=self.toggle_mute)
        self.mute_btn.pack(side="left", padx=2)
        self.hf_btn = ctk.CTkButton(icon_row, text="", image=make_icon("broadcast", TEXT_MUTE, 15, 1.8),
                                    width=32, height=28, corner_radius=8, fg_color=PANEL,
                                    hover_color=PANEL_2, command=self.toggle_handsfree)
        self.hf_btn.pack(side="left", padx=2)
        refresh_btn = ctk.CTkButton(icon_row, text="", image=make_icon("refresh", TEXT_DIM, 15, 1.8),
                                    width=32, height=28, corner_radius=8, fg_color=PANEL,
                                    hover_color=PANEL_2, command=self.refresh_diagnostics)
        refresh_btn.pack(side="left", padx=2)
        self.state_chip = ctk.CTkLabel(top_right, text="\u25cf BOOT", font=(MONO, 10, "bold"),
                                       text_color=CYAN, fg_color=PANEL, corner_radius=999,
                                       padx=10, pady=4)
        self.state_chip.pack(anchor="e", pady=(8, 0))

        # ---- right side: dual dial gauges (CPU / MEM) ----
        gauges = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        gauges.place(relx=0.988, rely=0.40, anchor="e")
        self.gauge_cpu = DialGauge(gauges, size=104, label="CPU", colour=CYAN)
        self.gauge_cpu.grid(row=0, column=0, padx=6)
        self.gauge_mem = DialGauge(gauges, size=104, label="MEM", colour=GOLD)
        self.gauge_mem.grid(row=0, column=1, padx=6)

        # ---- bottom-left: disk arc meter ----
        self.arc_disk = ArcMeter(self, size=120, label="DISK", colour=GREEN)
        self.arc_disk.place(relx=0.03, rely=0.88, anchor="w")

        # ---- bottom-right: big status/power dial (click = interrupt / stop) ----
        self.power_btn = ctk.CTkButton(
            self, text="", image=make_icon("power", CYAN, 26, 2.2), width=64, height=64,
            corner_radius=32, fg_color=PANEL, hover_color=PANEL_2,
            border_width=2, border_color=HAIRLINE_2, command=self.stop_speaking)
        self.power_btn.place(relx=0.975, rely=0.88, anchor="e")

        # ---- bottom bar: command composer ----
        self._build_composer()

        # ---- overlay panel (conversation / capabilities / etc.) ----
        self._build_overlay()

        # ---- toast anchor ----
        self.backdrop.bind("<Configure>", lambda e: None)

    def _build_composer(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=16,
                           border_width=1, border_color=HAIRLINE_2)
        bar.place(relx=0.5, rely=0.975, anchor="s", relwidth=0.56)
        bar.grid_columnconfigure(1, weight=1)

        self.composer_mic = ctk.CTkButton(
            bar, text="", image=make_icon("mic", CYAN, 16, 1.9), width=38, height=38,
            corner_radius=19, fg_color=PANEL_2, hover_color=HAIRLINE_2, command=self.start_voice)
        self.composer_mic.grid(row=0, column=0, padx=(10, 8), pady=10)

        self.input = ctk.CTkEntry(bar, placeholder_text="Ask J.A.R.V.I.S. \u2026",
                                  font=(UI, 12), fg_color=PANEL, border_width=0,
                                  text_color=TEXT)
        self.input.grid(row=0, column=1, sticky="ew", pady=10)
        self.input.bind("<Return>", lambda e: self.send_input())

        self.send_btn = ctk.CTkButton(
            bar, text="", image=make_icon("send", BG, 16, 1.9), width=38, height=38,
            corner_radius=19, fg_color=CYAN, hover_color=mix(CYAN, "#FFFFFF", 0.25),
            command=self.send_input)
        self.send_btn.grid(row=0, column=2, padx=(8, 6), pady=10)

        self.stop_btn = ctk.CTkButton(
            bar, text="", image=make_icon("stop", TEXT_DIM, 14, 2.0), width=34, height=34,
            corner_radius=17, fg_color=PANEL_2, hover_color="#3A1E27", command=self.stop_speaking)
        self.stop_btn.grid(row=0, column=3, padx=(0, 10), pady=10)

    # ------------------------------------------------------------- overlay
    def _build_overlay(self):
        """Semi-transparent panel used for conversation / capabilities /
        activity / deliverables / diagnostics / about views. Hidden by
        default so the HUD is the primary view, exactly like the reference
        art; toggled from the nav rail."""
        self.overlay = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14,
                                    border_width=1, border_color=HAIRLINE_2)
        self.overlay.place(relx=0.5, rely=0.46, anchor="center",
                           relwidth=0.66, relheight=0.72)
        self.overlay.grid_rowconfigure(1, weight=1)
        self.overlay.grid_columnconfigure(0, weight=1)
        self.overlay.lower(self.reactor_holder)

        head = ctk.CTkFrame(self.overlay, fg_color=PANEL, corner_radius=0, height=44)
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        head.grid_columnconfigure(0, weight=1)
        self.overlay_title = ctk.CTkLabel(head, text="", font=(DISPLAY, 14, "bold"),
                                          text_color=TEXT)
        self.overlay_title.grid(row=0, column=0, sticky="w")
        self.overlay_actions = ctk.CTkFrame(head, fg_color=PANEL, corner_radius=0)
        self.overlay_actions.grid(row=0, column=1, sticky="e")
        close_btn = ctk.CTkButton(head, text="", image=make_icon("close", TEXT_DIM, 13, 2.0),
                                  width=28, height=28, corner_radius=8, fg_color=PANEL_2,
                                  hover_color=HAIRLINE_2, command=self.hide_overlay)
        close_btn.grid(row=0, column=2, padx=(8, 0))

        stack = ctk.CTkFrame(self.overlay, fg_color=PANEL, corner_radius=0)
        stack.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
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
        for v in self.views.values():
            v.grid(row=0, column=0, sticky="nsew")
        self.overlay.place_forget()   # hidden until a nav pill is clicked

    def _scroll_area(self, parent):
        holder = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, bd=0, takefocus=0)
        scroll = ctk.CTkScrollbar(holder, command=canvas.yview, width=9, corner_radius=5,
                                  fg_color=PANEL, button_color=HAIRLINE_2,
                                  button_hover_color=CYAN_DIM)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew", padx=(14, 4), pady=8)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))
        inner = ctk.CTkFrame(canvas, fg_color=PANEL, corner_radius=0)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        self._bind_wheel(canvas, canvas)
        self._bind_wheel(inner, canvas)
        return holder, canvas, inner

    def _bind_wheel(self, widget, canvas):
        def _wheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)) * 2, "units")
            except Exception:
                pass
        stack = [widget]
        while stack:
            cur = stack.pop()
            try:
                cur.bind("<MouseWheel>", _wheel, add="+")
            except Exception:
                pass
            try:
                stack.extend(cur.winfo_children())
            except Exception:
                pass

    def show_view(self, key):
        titles = {"conversation": "CONVERSATION", "capabilities": "CAPABILITIES",
                  "activity": "ACTIVITY", "deliverables": "DELIVERABLES",
                  "diagnostics": "DIAGNOSTICS", "about": "ABOUT"}
        if self.view == key:
            self.hide_overlay()
            return
        self.view = key
        self.overlay.place(relx=0.5, rely=0.46, anchor="center", relwidth=0.66, relheight=0.72)
        self.overlay.lift()
        self.views[key].tkraise()
        self.overlay_title.configure(text=titles.get(key, ""))
        for child in self.overlay_actions.winfo_children():
            child.destroy()
        builders = {"conversation": self._actions_conversation,
                    "deliverables": self._actions_deliverables,
                    "diagnostics": self._actions_diagnostics,
                    "activity": self._actions_activity}
        b = builders.get(key)
        if b:
            b()
        for name, button in self.rail_buttons.items():
            active = (name == key)
            button.configure(fg_color=PANEL_2 if active else PANEL,
                             text_color=CYAN if active else TEXT_DIM)
        if key == "deliverables":
            self.refresh_deliverables()
        elif key == "diagnostics":
            self.refresh_diagnostics()
        elif key == "capabilities":
            self._render_capabilities()

    def hide_overlay(self):
        self.overlay.place_forget()
        self.view = "hud"
        for button in self.rail_buttons.values():
            button.configure(fg_color=PANEL, text_color=TEXT_DIM)

    def _ensure_visible(self, key):
        """Bring a panel to front only if the HUD is currently bare (no
        overlay open) — so replies/errors are never silently invisible,
        without yanking the user out of a tab they deliberately opened."""
        if self.view == "hud":
            self.show_view(key)

    def _action_button(self, parent, kind, text, command):
        b = ctk.CTkButton(parent, text="  " + text, image=make_icon(kind, TEXT_DIM, 13, 1.9),
                          compound="left", font=(MONO, 8, "bold"), height=26, corner_radius=8,
                          fg_color=PANEL_2, hover_color=HAIRLINE_2, text_color=TEXT_DIM,
                          command=command)
        b.pack(side="left", padx=4)
        return b

    def _sub_header(self, parent, text, note=""):
        row = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=text, font=(MONO, 8, "bold"), text_color=CYAN_DIM).grid(
            row=0, column=0, sticky="w")
        if note:
            ctk.CTkLabel(row, text=note, font=(MONO, 8), text_color=TEXT_MUTE).grid(
                row=0, column=1, sticky="e")
        return row

    # ======================================================== CONVERSATION
    def _view_conversation(self, parent):
        page = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        holder, canvas, inner = self._scroll_area(page)
        holder.pack(fill="both", expand=True)
        self.chat_canvas = canvas
        self.chat_inner = inner
        self.chat_row = 0
        inner.grid_columnconfigure(0, weight=1)
        self.intro_card = self._conv_intro(inner)

        typing = ctk.CTkFrame(inner, fg_color=PANEL_2, corner_radius=10,
                              border_width=1, border_color=HAIRLINE)
        typing.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(typing, text="JARVIS", font=(MONO, 9, "bold"), text_color=CYAN).grid(
            row=0, column=0, sticky="w", padx=(12, 8), pady=(9, 0))
        self.typing_label = ctk.CTkLabel(typing, text="thinking.", font=(MONO, 9),
                                        text_color=TEXT_DIM, anchor="w")
        self.typing_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=(12, 12), pady=(2, 9))
        typing.grid_remove()
        self.typing_card = typing
        self._bind_wheel(typing, canvas)
        canvas.bind("<Configure>", self._resize_wraps, add="+")
        return page

    def _resize_wraps(self, event):
        width = max(280, event.width - 100)
        for label in list(self._wrap_labels):
            try:
                label.configure(wraplength=width)
            except Exception:
                pass

    def _conv_intro(self, inner):
        intro = ctk.CTkFrame(inner, fg_color=PANEL_2, corner_radius=12,
                             border_width=1, border_color=HAIRLINE_2)
        intro.grid(row=0, column=0, sticky="ew", pady=(6, 6))
        intro.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(intro, text="Standing by, sir", font=(DISPLAY, 14, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 0))
        ctk.CTkLabel(intro, text="Type a command below or tap the microphone. Try "
                                 "\u201ccreate a presentation on quantum computing\u201d or "
                                 "\u201cwhat is my CPU usage?\u201d",
                     font=(UI, 11), text_color=TEXT_DIM, wraplength=480,
                     justify="left").grid(row=1, column=0, sticky="w", padx=16, pady=(4, 14))
        self._bind_wheel(intro, self.chat_canvas if hasattr(self, "chat_canvas") else intro)
        return intro

    def _add_message(self, role, text, tool=None, voice=None):
        if role != "notice" and getattr(self, "intro_card", None):
            try:
                self.intro_card.destroy()
            except Exception:
                pass
            self.intro_card = None

        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        accent = {"user": GOLD, "ai": CYAN, "notice": HAIRLINE_2}.get(role, HAIRLINE_2)
        card = ctk.CTkFrame(self.chat_inner, fg_color=PANEL_2, corner_radius=10,
                            border_width=1, border_color=HAIRLINE)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(card, fg_color=accent, width=3, corner_radius=2).grid(
            row=0, column=0, rowspan=2, sticky="ns")
        head = ctk.CTkFrame(card, fg_color=PANEL_2, corner_radius=0)
        head.grid(row=0, column=1, sticky="ew", padx=(12, 12), pady=(9, 0))
        head.grid_columnconfigure(1, weight=1)
        name = "YOU" if role == "user" else ("SIMMI" if voice == "en_female" else "JARVIS") \
            if role == "ai" else "EVENT"
        ctk.CTkLabel(head, text=name, font=(MONO, 9, "bold"), text_color=accent).grid(
            row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text=stamp, font=(MONO, 8), text_color=TEXT_MUTE).grid(
            row=0, column=1, sticky="e")
        body = ctk.CTkLabel(card, text=text, font=(UI, 11),
                            text_color=TEXT_DIM if role == "notice" else TEXT,
                            wraplength=max(280, self.chat_canvas.winfo_width() - 100),
                            justify="left", anchor="w")
        body.grid(row=1, column=1, sticky="w", padx=(12, 14), pady=(5, 6 if tool else 11))
        self._wrap_labels.append(body)
        if tool:
            chip = ctk.CTkFrame(card, fg_color=PANEL, corner_radius=8, border_width=1,
                                border_color=HAIRLINE_2)
            chip.grid(row=2, column=1, sticky="ew", padx=(12, 14), pady=(0, 11))
            ok = tool.get("ok", True)
            ctk.CTkLabel(chip, text="", image=make_icon("chip", GREEN if ok else RED, 13, 1.8)).grid(
                row=0, column=0, padx=(8, 6), pady=6)
            ctk.CTkLabel(chip, text=tool.get("name", ""), font=(MONO, 8, "bold"),
                         text_color=CYAN).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(chip, text=shorten(tool.get("detail", ""), 90), font=(MONO, 8),
                         text_color=TEXT_MUTE, anchor="w").grid(row=0, column=2, sticky="w", padx=8)
        self.chat_row += 1
        card.grid(row=self.chat_row, column=0, sticky="ew", pady=4)
        self._bind_wheel(card, self.chat_canvas)
        self._restack_typing()
        if self.view == "conversation":
            self.after(30, lambda: self.chat_canvas.yview_moveto(1.0))
        return card

    def _add_notice(self, text):
        return self._add_message("notice", text)

    def _restack_typing(self):
        try:
            self.typing_card.grid(row=self.chat_row + 1, column=0, sticky="ew", pady=4)
        except Exception:
            pass

    def _set_typing(self, active):
        try:
            if active:
                self._restack_typing()
                self.typing_card.grid()
                if self.view == "conversation":
                    self.after(30, lambda: self.chat_canvas.yview_moveto(1.0))
            else:
                self.typing_card.grid_remove()
        except Exception:
            pass

    def _actions_conversation(self):
        self._action_button(self.overlay_actions, "export", "EXPORT", self.export_conversation)
        self._action_button(self.overlay_actions, "trash", "CLEAR", self.clear_conversation)

    # ======================================================== CAPABILITIES
    def _capability_catalogue(self):
        """Build the capability list LIVE from the loaded jarvis.py engine
        (FUNCTION_MAP) rather than a hardcoded snapshot, so every tool the
        real engine defines shows up here even if it's newer/larger than
        the jarvis.py this GUI was originally written against."""
        static_desc = {}
        for _group, entries in CAPABILITY_GROUPS:
            for name, desc in entries:
                static_desc[name] = desc

        groups = {"DOCUMENTS & CREATION": [], "SYSTEM CONTROL": [],
                  "INTELLIGENCE & RESEARCH": [], "OTHER": []}
        doc_names = {"create_word_document", "create_presentation", "create_resume", "create_file"}
        sys_names = {"open_application", "execute_system_command", "list_running_processes",
                     "take_screenshot", "write_to_clipboard", "read_clipboard", "list_files"}
        intel_names = {"search_web", "search_files_on_computer", "read_file_content",
                       "get_system_info", "get_current_time", "calculate"}

        names = sorted(FUNCTION_MAP.keys()) if FUNCTION_MAP else sorted(static_desc.keys())
        if not names:
            names = sorted(static_desc.keys())
        for name in names:
            func = FUNCTION_MAP.get(name)
            desc = static_desc.get(name)
            if not desc:
                doc = (getattr(func, "__doc__", None) or "").strip() if func else ""
                desc = doc.splitlines()[0].strip() if doc else "Callable tool exposed by the jarvis.py engine."
            bucket = "DOCUMENTS & CREATION" if name in doc_names else \
                "SYSTEM CONTROL" if name in sys_names else \
                "INTELLIGENCE & RESEARCH" if name in intel_names else "OTHER"
            groups[bucket].append((name, desc, func is not None))
        return [(g, items) for g, items in groups.items() if items]

    def _view_capabilities(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        self.cap_title = ctk.CTkLabel(inner, text="", font=(DISPLAY, 12, "bold"), text_color=TEXT)
        self.cap_title.grid(row=0, column=0, sticky="w", pady=(6, 10))
        self.cap_canvas = canvas
        self.cap_inner = inner
        self._render_capabilities()
        return holder

    def _render_capabilities(self):
        inner = self.cap_inner
        for child in list(inner.winfo_children()):
            if child is self.cap_title:
                continue
            child.destroy()
        catalogue = self._capability_catalogue()
        total = sum(len(items) for _g, items in catalogue)
        self.cap_title.configure(text="%d callable functions live from your jarvis.py \u00b7 3 offline voices" % total)
        row = 1
        for group, entries in catalogue:
            self._sub_header(inner, group, "%d" % len(entries)).grid(row=row, column=0, sticky="ew", pady=(12, 6))
            row += 1
            for name, desc, wired in entries:
                card = ctk.CTkFrame(inner, fg_color=PANEL_2, corner_radius=8, border_width=1,
                                    border_color=HAIRLINE)
                card.grid(row=row, column=0, sticky="ew", pady=2)
                card.grid_columnconfigure(1, weight=1)
                row += 1
                ctk.CTkLabel(card, text="", image=make_icon(
                    "chip", CYAN if wired else RED, 14, 1.7)).grid(
                    row=0, column=0, rowspan=2, padx=(10, 9), pady=9)
                ctk.CTkLabel(card, text=name, font=(MONO, 9, "bold"), text_color=TEXT).grid(
                    row=0, column=1, sticky="w", pady=(8, 0))
                ctk.CTkLabel(card, text=desc, font=(UI, 10), text_color=TEXT_DIM,
                             wraplength=440, justify="left", anchor="w").grid(
                    row=1, column=1, sticky="w", pady=(1, 9))
                ctk.CTkLabel(card, text="LIVE" if wired else "MISSING", font=(MONO, 7, "bold"),
                             text_color=GREEN if wired else RED).grid(row=0, column=2, rowspan=2, padx=(6, 12))
                self._bind_wheel(card, self.cap_canvas)

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
        self.log_activity("SYSTEM", "Timeline online.")
        return holder

    def log_activity(self, kind, text, colour=None):
        if not hasattr(self, "activity_inner"):
            return
        palette = {"INTENT": GOLD, "TOOL": CYAN, "VOICE": GREEN, "ERROR": RED,
                   "SYSTEM": TEXT_MUTE, "MODEL": GOLD}
        colour = colour or palette.get(kind, TEXT_DIM)
        self.activity_row += 1
        strip = ctk.CTkFrame(self.activity_inner, fg_color=PANEL, corner_radius=0)
        strip.grid(row=self.activity_row, column=0, sticky="ew", pady=1)
        strip.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(strip, text=_dt.datetime.now().strftime("%H:%M:%S"), font=(MONO, 8),
                     text_color=TEXT_MUTE).grid(row=0, column=0, padx=(2, 10), pady=3)
        ctk.CTkLabel(strip, text="%-7s" % kind, font=(MONO, 8, "bold"), text_color=colour).grid(
            row=0, column=1, sticky="w", padx=(0, 10))
        label = ctk.CTkLabel(strip, text=text, font=(MONO, 8), text_color=TEXT_DIM, anchor="w",
                             wraplength=max(260, self.activity_canvas.winfo_width() - 200))
        label.grid(row=0, column=2, sticky="w", pady=3)
        self._wrap_labels.append(label)
        self._activity_rows.append(strip)
        while len(self._activity_rows) > 200:
            try:
                self._activity_rows.pop(0).destroy()
            except Exception:
                break
        self._bind_wheel(strip, self.activity_canvas)
        if self.view == "activity":
            self.after(30, lambda: self.activity_canvas.yview_moveto(1.0))

    def _actions_activity(self):
        self._action_button(self.overlay_actions, "trash", "CLEAR", self.clear_activity_log)

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
        items.sort(key=lambda e: e[0], reverse=True)
        return items[:150]

    def refresh_deliverables(self):
        inner = self.deliverable_inner
        for child in inner.winfo_children():
            child.destroy()
        items = self._scan_deliverables()
        self._sub_header(inner, "GENERATED FILES", "%d item(s)" % len(items)).grid(
            row=0, column=0, sticky="ew", pady=(6, 8))
        if not items:
            ctk.CTkLabel(inner, text="Nothing generated yet.", font=(UI, 11),
                         text_color=TEXT_DIM).grid(row=1, column=0, sticky="w", pady=8)
            return
        row = 1
        for mtime, path, size in items:
            card = ctk.CTkFrame(inner, fg_color=PANEL_2, corner_radius=8, border_width=1,
                                border_color=HAIRLINE)
            card.grid(row=row, column=0, sticky="ew", pady=2)
            row += 1
            card.grid_columnconfigure(1, weight=1)
            ext = os.path.splitext(path)[1].lower().lstrip(".") or "file"
            icon_kind = "layers" if ext in ("pptx", "ppt") else \
                "chat" if ext in ("docx", "doc", "md", "txt") else \
                "eye" if ext in ("png", "jpg", "jpeg", "webp") else "folder"
            ctk.CTkLabel(card, text="", image=make_icon(icon_kind, CYAN, 14, 1.7)).grid(
                row=0, column=0, rowspan=2, padx=(10, 9), pady=8)
            ctk.CTkLabel(card, text=shorten(os.path.basename(path), 44), font=(MONO, 9, "bold"),
                         text_color=TEXT, anchor="w").grid(row=0, column=1, sticky="w", pady=(7, 0))
            detail = "%s \u00b7 %s \u00b7 %s" % (ext.upper(), human_size(size),
                                                time.strftime("%d %b %H:%M", time.localtime(mtime)))
            ctk.CTkLabel(card, text=detail, font=(MONO, 8), text_color=TEXT_MUTE, anchor="w").grid(
                row=1, column=1, sticky="w", pady=(0, 7))
            ctk.CTkButton(card, text="", image=make_icon("eye", TEXT_DIM, 13, 1.8), width=32, height=26,
                         corner_radius=7, fg_color=PANEL, hover_color=HAIRLINE_2,
                         command=lambda p=path: self.open_path(p)).grid(row=0, column=2, rowspan=2, padx=(6, 10))
            self._bind_wheel(card, self.deliverable_canvas)

    def _actions_deliverables(self):
        self._action_button(self.overlay_actions, "refresh", "REFRESH", self.refresh_deliverables)
        self._action_button(self.overlay_actions, "folder", "OPEN", lambda: self.open_path(OUTPUT_DIR))

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

        self._diag_section(inner, "COMPUTE")
        for key, label in (("cpu", "PROCESSOR LOAD"), ("mem", "MEMORY LOAD"),
                           ("disk", "SYSTEM DISK LOAD"), ("gpu", "GRAPHICS ADAPTER"),
                           ("battery", "POWER SOURCE"), ("uptime", "MACHINE UPTIME")):
            self._diag_item(inner, key, label)

        self._diag_section(inner, "LANGUAGE MODELS")
        for key, label in (("provider_groq", "GROQ CLOUD"), ("provider_cerebras", "CEREBRAS"),
                           ("provider_gemini", "GOOGLE GEMINI"), ("tools", "TOOL-CALL CONTRACT")):
            self._diag_item(inner, key, label)

        self._diag_section(inner, "VOICE STACK")
        for key, label in (("voice_en_male", "JARVIS \u2014 ENGLISH"), ("voice_hi_male", "JARVIS \u2014 HINDI"),
                           ("voice_en_female", "SIMMI \u2014 ENGLISH"), ("voice_input", "SPEECH INPUT")):
            self._diag_item(inner, key, label)

        self._diag_section(inner, "RUNTIME")
        for key, label in (("engine", "ENGINE STATUS"), ("engine_load", "ENGINE LOAD TIME"),
                           ("path", "PROJECT ROOT"), ("session", "SESSION AGE"),
                           ("counts", "MESSAGES \u00b7 TOOLS \u00b7 EXPORTS")):
            self._diag_item(inner, key, label)
        self.refresh_diagnostics()
        return holder

    def _diag_section(self, parent, title):
        self.diag_row += 1
        self._sub_header(parent, title).grid(row=self.diag_row, column=0, sticky="ew", pady=(14, 6))

    def _diag_item(self, parent, key, label):
        self.diag_row += 1
        card = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=7, border_width=1,
                            border_color=HAIRLINE)
        card.grid(row=self.diag_row, column=0, sticky="ew", pady=2)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(card, text=label, font=(MONO, 8), text_color=TEXT_MUTE).grid(
            row=0, column=0, sticky="w", padx=(10, 8), pady=9)
        value = ctk.CTkLabel(card, text="\u2014", font=(MONO, 9, "bold"), text_color=TEXT,
                             anchor="e")
        value.grid(row=0, column=1, sticky="e", padx=(0, 10), pady=9)
        self.diag_labels[key] = value

    def _diag_set(self, key, text, colour=None):
        v = self.diag_labels.get(key)
        if not v:
            return
        try:
            v.configure(text=str(text), text_color=colour or TEXT)
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

        def tone(v):
            return GREEN if v < 60 else (AMBER if v < 85 else RED)

        cpu, mem, disk = as_pct(info.get("cpu_usage")), as_pct(info.get("memory")), as_pct(info.get("disk_usage"))
        self._diag_set("cpu", info.get("cpu_usage", "collecting"), tone(cpu))
        self._diag_set("mem", "%s of %s" % (info.get("memory", "\u2014"), info.get("memory_total", "\u2014")), tone(mem))
        self._diag_set("disk", "%s used" % info.get("disk_usage", "\u2014"), tone(disk))
        gpu = info.get("gpu") or []
        self._diag_set("gpu", shorten(gpu[0].get("name", "N/A"), 34) if gpu else "N/A")
        self._diag_set("battery", info.get("battery", "\u2014"))
        psutil_mod = engine_get("psutil")
        uptime = "N/A"
        if psutil_mod is not None:
            try:
                uptime = hms(time.time() - psutil_mod.boot_time())
            except Exception:
                pass
        self._diag_set("uptime", uptime)

        for key, flag, model_attr in (("provider_groq", "USE_GROQ", "GROQ_MODEL_NAME"),
                                      ("provider_cerebras", "USE_CEREBRAS", "CEREBRAS_MODEL_NAME"),
                                      ("provider_gemini", "USE_GEMINI", "GEMINI_MODEL_NAME")):
            online = bool(engine_get(flag, False))
            model = shorten(str(engine_get(model_attr, "") or "auto"), 22)
            self._diag_set(key, ("ONLINE \u00b7 " + model) if online else "OFFLINE", GREEN if online else RED)
        self._diag_set("tools", "%d functions" % len(FUNCTION_MAP), CYAN if FUNCTION_MAP else RED)

        loaded = engine_get("voice_engines", {}) or {}
        for key, vk in (("voice_en_male", "en_male"), ("voice_hi_male", "hi_male"),
                        ("voice_en_female", "en_female")):
            ready = vk in loaded
            self._diag_set(key, "READY" if ready else "MISSING", GREEN if ready else RED)
        self._diag_set("voice_input", "READY" if VOICE_INPUT else "UNAVAILABLE",
                       GREEN if VOICE_INPUT else AMBER)
        self._diag_set("engine", "ONLINE" if ENGINE_OK else "OFFLINE \u00b7 " + shorten(ENGINE_ERR, 24),
                       GREEN if ENGINE_OK else RED)
        self._diag_set("engine_load", ("%.2f s" % (ENGINE_LOAD_MS / 1000.0)) if ENGINE_LOAD_MS else "\u2014")
        self._diag_set("path", shorten(BASE_DIR, 40))
        self._diag_set("session", hms(time.time() - self.started))
        self._diag_set("counts", "%d \u00b7 %d \u00b7 %d" % (self.msg_count, self.tool_count, self.export_count))

    def _actions_diagnostics(self):
        self._action_button(self.overlay_actions, "refresh", "REFRESH", self.refresh_diagnostics)

    # ================================================================= ABOUT
    def _view_about(self, parent):
        holder, canvas, inner = self._scroll_area(parent)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        holder.grid(row=0, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(inner, text="J.A.R.V.I.S", font=(DISPLAY, 22, "bold"), text_color=TEXT).grid(
            row=0, column=0, sticky="w", pady=(10, 0))
        ctk.CTkLabel(inner, text="HUD interface \u00b7 local voice assistant", font=(MONO, 9),
                     text_color=TEXT_MUTE).grid(row=1, column=0, sticky="w", pady=(2, 10))
        ctk.CTkLabel(inner, text="A context-aware desktop assistant that infers who you are "
                                 "addressing (JARVIS or Simmi), replies with offline neural "
                                 "voices, and turns conversation into finished documents, "
                                 "slide decks and r\u00e9sum\u00e9s through structured tool calls.",
                     font=(UI, 11), text_color=TEXT_DIM, wraplength=480, justify="left").grid(
            row=2, column=0, sticky="w", pady=(0, 12))
        ctk.CTkButton(inner, text="  github.com/rajatrajdav/Local_AI-assistant",
                     image=make_icon("export", CYAN, 13, 1.8), compound="left", font=(MONO, 9),
                     fg_color=PANEL_2, hover_color=HAIRLINE_2, text_color=CYAN, corner_radius=8,
                     height=30, command=lambda: webbrowser.open(REPO_URL)).grid(
            row=3, column=0, sticky="w", pady=(0, 16))
        shortcuts = (
            ("Enter", "Dispatch the composed prompt"),
            ("Esc", "Interrupt speech or cancel a voice capture"),
            ("Ctrl+M", "Mute or unmute spoken replies"),
            ("Ctrl+Shift+V", "Start a voice capture"),
            ("Ctrl+1..6", "Switch overlay views"),
            ("Ctrl+E", "Export the transcript"),
        )
        self._sub_header(inner, "SHORTCUTS").grid(row=4, column=0, sticky="ew", pady=(6, 6))
        row = 5
        for keys, action in shortcuts:
            card = ctk.CTkFrame(inner, fg_color=PANEL_2, corner_radius=7, border_width=1,
                                border_color=HAIRLINE)
            card.grid(row=row, column=0, sticky="ew", pady=2)
            row += 1
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=keys, font=(MONO, 9, "bold"), text_color=GOLD,
                         fg_color=PANEL, corner_radius=6, padx=8, pady=3).grid(row=0, column=0, padx=10, pady=6)
            ctk.CTkLabel(card, text=action, font=(UI, 10), text_color=TEXT_DIM, anchor="w").grid(
                row=0, column=1, sticky="w", padx=(0, 10))
        return holder

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
                    self.conversation.append({"role": "assistant", "content": "Yes sir? How can I help you?"})
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
            self.from_engine.put({"_kind": "voice_switch", "voice": new_voice, "reason": reason})
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
            tool_info = {"name": name.replace("_", " "), "ok": ok, "detail": shorten(tool_result, 160)}
            self.from_engine.put({"_kind": "tool_done", "name": name, "ok": ok, "text": str(tool_result)})
            if "Permission denied" not in str(tool_result):
                if ok:
                    out = "%s Done! %s" % (out, str(tool_result).replace("Success: ", ""))
                else:
                    out = "%s %s" % (out, tool_result)

        self.conversation.append({"role": "user", "content": clean})
        self.conversation.append({"role": "assistant", "content": out})
        if len(self.conversation) > 60:
            self.conversation = self.conversation[-60:]

        self.from_engine.put({"_kind": "ai", "text": out, "tool": tool_info, "voice": voice_out,
                              "ms": elapsed, "user": clean})
        if self.tts_enabled:
            self._speak(out, voice_out)
        else:
            self.from_engine.put({"_kind": "status", "state": "READY"})

    def _deliver(self, text, tool):
        self.from_engine.put({"_kind": "ai", "text": text, "tool": tool, "voice": self.current_voice,
                              "ms": 0, "user": ""})
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
        self.from_engine.put({"_kind": "voice_result", "text": text, "token": token})

    def _speak(self, text, voice):
        self._tts_stop.clear()
        threading.Thread(target=self._tts_worker, args=(text, voice), daemon=True).start()

    def _piper_play(self, text, voice, stop_event):
        engines = engine_get("voice_engines") or {}
        piper_voice = engines.get(voice)
        np_mod = engine_get("np")
        sd_mod = engine_get("sd")
        if piper_voice is None or np_mod is None or sd_mod is None:
            return False
        language = (VOICES.get(voice) or {}).get("language", "en")
        normaliser = engine_get("normalize_hindi_text" if language == "hi" else "normalize_english_text")
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
                self.subcaption.configure(text="YOU \u2014 " + shorten(msg.get("text", ""), 90))
            elif kind == "ai":
                self._on_ai_message(msg)
            elif kind == "status":
                self.set_state(msg.get("state", "READY"))
            elif kind == "intent":
                self.log_activity("INTENT", msg.get("text", ""))
            elif kind == "tool_start":
                self._on_tool_start(msg)
            elif kind == "tool_done":
                self.log_activity("TOOL", "%s \u2192 %s" % (msg.get("name", "tool"),
                                  shorten(msg.get("text", ""), 120)), CYAN if msg.get("ok") else RED)
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
                self._ensure_visible("conversation")
        except Exception as exc:
            try:
                self.log_activity("ERROR", "UI handler failed: %s" % exc)
            except Exception:
                pass

    def _on_ai_message(self, msg):
        self._set_typing(False)
        self._busy = False
        text = msg.get("text", "")
        voice = msg.get("voice", self.current_voice)
        self.msg_count += 1
        try:
            self.subcaption.configure(text=shorten(text, 170))
        except Exception:
            pass
        self._add_message("ai", text, tool=msg.get("tool"), voice=voice)
        self._ensure_visible("conversation")
        if msg.get("user"):
            self.log_activity("MODEL", "reply composed in %.2f s" % (msg.get("ms", 0) / 1000.0), GOLD)
        if not self.tts_enabled:
            self.set_state("READY")

    def _on_tool_start(self, msg):
        name = msg.get("name", "tool")
        args = msg.get("args") or {}
        detail = ", ".join("%s=%s" % (k, shorten(v, 24)) for k, v in list(args.items())[:4]) \
            if isinstance(args, dict) else shorten(args, 50)
        pretty = name.replace("_", " ")
        self.set_state("BUSY", "Executing %s" % pretty)
        self._toast("Executing %s" % pretty)
        self.log_activity("TOOL", "%s(%s)" % (name, detail))

    def _on_speech_end(self):
        self._speaking = False
        self.set_state("READY")
        if self.handsfree and not self._busy and not self._capturing:
            self._schedule_handsfree(900)

    def _on_voice_result(self, msg):
        self._capturing = False
        try:
            self.composer_mic.configure(fg_color=PANEL_2, image=make_icon("mic", CYAN, 16, 1.9))
        except Exception:
            pass
        if msg.get("token") != self._capture_token:
            return
        text = (msg.get("text") or "").strip()
        if text:
            self.subcaption.configure(text="YOU \u2014 " + shorten(text, 150))
            self.log_activity("VOICE", "Heard: %s" % shorten(text, 100))
            self._toast("Heard: %s" % shorten(text, 60))
            self.dispatch(text)
        else:
            self.set_state("READY", "No speech detected \u2014 try again")
            self._toast("No speech detected")
            self.log_activity("VOICE", "Capture finished with no transcript.")
            self._ensure_visible("conversation")
            if self.handsfree:
                self._schedule_handsfree(1400)

    def _on_sysinfo(self, info):
        def as_pct(v):
            try:
                return float(str(v).replace("%", "").strip().split()[0])
            except Exception:
                return 0.0
        cpu, mem, disk = as_pct(info.get("cpu_usage")), as_pct(info.get("memory")), as_pct(info.get("disk_usage"))
        self._cpu_hist.append(cpu)
        self._mem_hist.append(mem)
        try:
            self.gauge_cpu.set_value(cpu)
            self.gauge_mem.set_value(mem)
            self.arc_disk.set_value(disk)
        except Exception:
            pass
        if self.view == "diagnostics":
            self.refresh_diagnostics()

    # -------------------------------------------------------- state + chrome
    def set_state(self, state, note=None):
        if state not in STATES:
            state = "READY"
        self.status = state
        colour, caption, _speed = STATES[state]
        try:
            self.state_chip.configure(text="\u25cf " + state, text_color=colour)
            self.brand_state.configure(text=("%s \u00b7 %s" % (
                PERSONA_LABEL.get(self.current_voice, "JARVIS").split(" \u2014")[0], state)))
            self.caption.configure(text=note or caption, text_color=TEXT)
        except Exception:
            pass
        try:
            self.reactor.set_state(state)
        except Exception:
            pass
        if state == "THINKING":
            self._thinking_since = time.time()
            self._set_typing(True)
        if state in ("READY", "ERROR", "OFFLINE"):
            self._busy = False

    def _sync_voice_ui(self, reason=None):
        label = PERSONA_LABEL.get(self.current_voice, "JARVIS")
        note = "Voice \u2192 %s" % label
        if reason:
            note += "  (%s)" % reason
        self.log_activity("VOICE", note)

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
            self.clock_label.configure(text=now.strftime("%H:%M"))
            self.date_label.configure(text=now.strftime("%d-%b, %A").upper())
            self.session_label.configure(text="SESSION " + hms(time.time() - self.started))
        except Exception:
            pass
        self.after(1000, self._tick_clock)

    # ------------------------------------------------------------- animation
    def _animate(self):
        if self._closing:
            return
        now = time.time()
        dt = min(0.12, max(0.001, now - self._last_frame))
        self._last_frame = now
        try:
            self.reactor.tick(dt, self._current_amp())
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
        text = self.input.get().strip()
        if not text:
            self._toast("Compose a command first")
            return
        self.input.delete(0, "end")
        self.dispatch(text)

    def start_voice(self):
        if not VOICE_INPUT:
            self._add_notice("Voice input is unavailable \u2014 %s" % (SR_ERROR or ENGLISH_ONLY_NOTE))
            self._toast("Microphone unavailable")
            self._ensure_visible("conversation")
            return
        if self._capturing:
            self._toast("Already listening")
            return
        if self._speaking:
            self.stop_speaking()
        self._capture_token += 1
        self._capturing = True
        self.set_state("LISTENING", "Listening \u2014 speak now")
        self._toast("Listening\u2026 speak now")
        try:
            self.composer_mic.configure(fg_color=GREEN, image=make_icon("mic", BG, 16, 1.9))
        except Exception:
            pass
        self.log_activity("VOICE", "Microphone armed \u2014 natural VAD capture.")
        self.to_engine.put({"_kind": "voice_capture", "token": self._capture_token})

    def stop_speaking(self):
        if self._speaking or self.status == "SPEAKING":
            self._tts_stop.set()
            self._toast("Speech interrupted")
            self.log_activity("VOICE", "Playback interrupted by the user.")
        elif self._capturing:
            self._capture_token += 1
            self._capturing = False
            try:
                self.composer_mic.configure(fg_color=PANEL_2, image=make_icon("mic", CYAN, 16, 1.9))
            except Exception:
                pass
            self.set_state("READY", "Capture cancelled")
            self.log_activity("VOICE", "Voice capture cancelled.")

    def toggle_mute(self):
        self.tts_enabled = not self.tts_enabled
        if not self.tts_enabled and self._speaking:
            self._tts_stop.set()
        try:
            self.mute_btn.configure(image=make_icon(
                "speaker" if self.tts_enabled else "mute",
                CYAN_DIM if self.tts_enabled else TEXT_MUTE, 15, 1.8))
        except Exception:
            pass
        self._toast("Voice " + ("enabled" if self.tts_enabled else "muted"))
        self.log_activity("VOICE", "Voice output %s." % ("enabled" if self.tts_enabled else "muted"))

    def toggle_handsfree(self):
        if not VOICE_INPUT:
            self._add_notice("Hands-free mode needs a working microphone. %s" % (SR_ERROR or ENGLISH_ONLY_NOTE))
            self._toast("Microphone unavailable")
            self._ensure_visible("conversation")
            return
        self.handsfree = not self.handsfree
        colour = CYAN if self.handsfree else TEXT_MUTE
        try:
            self.hf_btn.configure(image=make_icon("broadcast", colour, 15, 1.8))
        except Exception:
            pass
        self._toast("Hands-free " + ("enabled" if self.handsfree else "disabled"))
        self.log_activity("VOICE", "Hands-free mode %s." % ("enabled" if self.handsfree else "disabled"))
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
        self.intro_card = self._conv_intro(self.chat_inner)
        self._restack_typing()
        self.log_activity("SYSTEM", "Conversation cleared.")
        self._toast("Conversation cleared")

    def export_conversation(self):
        if not self.conversation:
            self._toast("Nothing to export yet")
            return
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(OUTPUT_DIR, "jarvis_session_%s.md" % stamp)
            lines = ["# J.A.R.V.I.S \u2014 Session Transcript", "",
                     "Exported: %s" % _dt.datetime.now().strftime("%d %b %Y %H:%M:%S"),
                     "Voice: %s" % PERSONA_LABEL.get(self.current_voice, "\u2014"),
                     "Turns: %d" % (len(self.conversation) // 2), "", "---", ""]
            for entry in self.conversation:
                speaker = "**You**" if entry.get("role") == "user" else "**J.A.R.V.I.S.**"
                lines.append("%s: %s" % (speaker, entry.get("content", "")))
                lines.append("")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            self.export_count += 1
            self.log_activity("SYSTEM", "Transcript exported \u2192 %s" % os.path.basename(path))
            self._toast("Exported to generated_files")
            if self.view == "deliverables":
                self.refresh_deliverables()
        except Exception as exc:
            self._toast("Export failed")
            self.log_activity("ERROR", "Export failed: %s" % exc)

    def open_path(self, path):
        try:
            os.startfile(path)
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
            w = ctk.CTkLabel(self, text=text, font=(MONO, 9, "bold"), text_color=BG,
                             fg_color=CYAN, corner_radius=10, padx=16, pady=8)
            w.place(relx=0.5, rely=0.06, anchor="n")
            self._toast_widget = w
            self.after(2200, lambda: self._clear_toast(w))
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
        bindings = {
            "<Escape>": self.stop_speaking,
            "<Control-m>": self.toggle_mute, "<Control-M>": self.toggle_mute,
            "<Control-Shift-V>": self.start_voice, "<Control-Shift-v>": self.start_voice,
            "<Control-e>": self.export_conversation, "<Control-E>": self.export_conversation,
            "<Control-l>": self.clear_conversation, "<Control-L>": self.clear_conversation,
        }
        for i, (key, _kind, _label) in enumerate(RAIL_ITEMS, start=1):
            bindings["<Control-Key-%d>" % i] = (lambda k=key: self.show_view(k))
        for seq, action in bindings.items():
            try:
                self.bind(seq, consume(action), add="+")
            except Exception:
                pass

    def _on_close(self):
        self._closing = True
        self.handsfree = False
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
        self.refresh_diagnostics()
        try:
            self._render_capabilities()
        except Exception:
            pass
        if ENGINE_OK:
            self.set_state("READY")
            self.log_activity("SYSTEM", "Engine ready in %.2f s \u2014 %d callable functions." % (
                ENGINE_LOAD_MS / 1000.0, len(FUNCTION_MAP)))
            self.log_activity("SYSTEM", "Voice input: %s" % (
                "READY" if VOICE_INPUT else "UNAVAILABLE \u2014 " + (SR_ERROR or ENGLISH_ONLY_NOTE)),
                GREEN if VOICE_INPUT else AMBER)
            greeting = "System Online. Welcome back sir."
            self.msg_count += 1
            self.subcaption.configure(text=greeting)
            self._add_message("ai", greeting, voice=self.current_voice)
            self._toast("J.A.R.V.I.S. ready")
            if self.tts_enabled:
                self._speak(greeting, self.current_voice)
        else:
            self.set_state("OFFLINE")
            self.log_activity("ERROR", "Engine load failed: %s" % ENGINE_ERR)
            self._add_notice(
                "The jarvis.py engine could not be loaded, so chat, voice and tool "
                "features are unavailable until this is fixed:\n\n%s\n\n"
                "Common causes: jarvis_gui.py is not in the same folder as jarvis.py, "
                "a required package failed to import, or a Piper voice file is missing. "
                "Check the console window behind this app for the full traceback."
                % ENGINE_ERR)
            self._ensure_visible("conversation")
            self._toast("Engine failed to load \u2014 see Conversation panel")


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
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