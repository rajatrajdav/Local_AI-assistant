#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. — Professional Desktop GUI
=================================================================
A futuristic, HUD-style desktop interface for the Jarvis & Simmi
AI voice assistant, built with CustomTkinter on top of the
existing jarvis.py engine (LLM tool-calling, dual personalities,
local Piper TTS, system control).

Pages
-----
  • Chat          — text chat with Jarvis / Simmi, quick commands
  • System Monitor— live CPU / RAM / Disk / Battery gauges
  • Abilities     — showcase of every tool the assistant can run
  • About         — project showcase / tech-stack panel

Architecture
------------
The engine (jarvis.py) does all network + audio work on a
dedicated background thread so the interface never freezes.
Thread→UI messages are marshalled through a thread-safe queue
which the UI polls a few times per second with `after(...)`.

Run with:
    python jarvis_gui.py
"""

import os
import sys
import time
import json
import queue
import asyncio
import threading
import datetime as _dt

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)  # stable paths for voices/ and generated_files/

import tkinter as tk

# ---------------------------------------------------------------
# CustomTkinter — required for the main UI. If missing, try to
# auto-install it so the app never dies with a cryptic AttributeError.
# ---------------------------------------------------------------
try:
    import customtkinter as ctk
    CTK_ERROR = None
except Exception as _ce:
    CTK_ERROR = _ce
    ctk = None
    try:
        import subprocess as _sp
        _sp.check_call([sys.executable, "-m", "pip", "install",
                        "customtkinter", "--quiet"])
        import customtkinter as ctk
        CTK_ERROR = None
    except Exception:
        ctk = None
if ctk is None:
    print("FATAL: CustomTkinter could not be imported.\n"
          "       Run:  pip install customtkinter\n"
          f"       Reason: {CTK_ERROR}")
    sys.exit(2)

# =================================================================
# Colour palette — Iron-Man / HUD dark theme
# =================================================================
BG       = "#0B0E14"
PANEL    = "#121722"
PANEL_2  = "#1A2130"
BORDER   = "#1E2A45"
ACCENT   = "#00E5FF"   # cyber cyan
ACCENT_2 = "#3B82F6"   # electric blue
GOOD     = "#22C55E"   # online / success
WARN     = "#F59E0B"   # processing / amber
BAD      = "#EF4444"   # error / off
TEXT     = "#EAF3FF"
MUTED    = "#8FA3C4"
SOFT     = "#5B6B8C"

FONT = "Segoe UI"

STATUS_STYLE = {
    "ONLINE":     {"color": GOOD,  "glyph": "\u25cf"},
    "LISTENING":  {"color": GOOD,  "glyph": "\u25cf"},
    "PROCESSING": {"color": WARN,  "glyph": "\u25d0"},
    "SPEAKING":   {"color": ACCENT, "glyph": "\u25c9"},
    "BUSY":       {"color": WARN,  "glyph": "\u25d0"},
    "OFFLINE":    {"color": BAD,   "glyph": "\u25cb"},
    "ERROR":      {"color": BAD,   "glyph": "\u2716"},
    "IDLE":       {"color": SOFT,  "glyph": "\u25cb"},
}

# =================================================================
# Engine import (jarvis.py) — LAZY. The slow import runs in a
# background thread while the video splash screen is animating.
# =================================================================
_engine = None
ENGINE_OK = False
ENGINE_ERR = "Engine not loaded yet."
VOICES = {
    "en_male":  {"name": "Jarvis (English)"},
    "hi_male":  {"name": "Jarvis (Hindi)"},
    "en_female": {"name": "Simmi (English)"},
}
PERSONALITIES = {}
FUNCTION_MAP = {}
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_files")
process_user_input = None
execute_function = None
get_system_info = None
detect_target_personality = None
detect_lang = None
get_personality = None
_sr = None
_SndMic = None
VOICE_INPUT = False


def _load_engine():
    """Import the heavy jarvis.py engine. Call from a background thread."""
    global _engine, ENGINE_OK, ENGINE_ERR, VOICES, PERSONALITIES
    global FUNCTION_MAP, OUTPUT_DIR, process_user_input, execute_function
    global get_system_info, detect_target_personality, detect_lang
    global get_personality, _sr, _SndMic, VOICE_INPUT
    try:
        import jarvis as _engine
        from jarvis import (
            VOICES, PERSONALITIES, FUNCTION_MAP, OUTPUT_DIR,
            process_user_input, execute_function, get_system_info,
            detect_target_personality, detect_lang, get_personality,
        )
        ENGINE_OK = True
    except Exception as _exc:
        ENGINE_OK = False
        ENGINE_ERR = str(_exc)
    try:
        import speech_recognition as _sr
        _SndMic = getattr(_engine, "SoundDeviceMicrophone", None)
        VOICE_INPUT = bool(_SndMic)
    except Exception:
        _sr = None
        _SndMic = None
        VOICE_INPUT = False
    return ENGINE_OK


def _speak_async(text, voice):
    """TTS bridge: speak_handler is async; run it in a temporary loop."""
    if ENGINE_OK and _engine is not None and text:
        try:
            asyncio.run(_engine.speak_handler(text, voice))
        except Exception:
            pass


PERSONA_LABEL = {
    "en_male": "JARVIS \u2014 ENGLISH",
    "hi_male": "JARVIS \u2014 HINDI",
    "en_female": "SIMMI \u2014 ENGLISH",
}
# =================================================================
# Main application window
# =================================================================
class JarvisGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("J.A.R.V.I.S \u2014 Just A Rather Very Intelligent System")
        self.geometry("1220x800")
        self.minsize(1020, 690)
        self.configure(fg_color=BG)

        # ---- state -------------------------------------------------
        self.conversation = []
        self.current_voice = "en_male"
        self.tts_enabled = True
        self.status = "ONLINE" if ENGINE_OK else "OFFLINE"
        self._busy = False
        self._closing = False

        self.to_engine = queue.Queue()
        self.from_engine = queue.Queue()
        self.sys_info = {}
        self._sys_lock = threading.Lock()

        def F(size, weight="normal"):
            return (FONT, size, weight)

        self.f_title  = F(22, "bold")
        self.f_sub    = F(11)
        self.f_nav    = F(13, "bold")
        self.f_status = F(12, "bold")
        self.f_clock  = F(13, "bold")
        self.f_body   = F(13)
        self.f_small  = F(11)
        self.f_chip   = F(12, "bold")

        self._build_layout()

        threading.Thread(target=self._engine_loop, daemon=True).start()
        threading.Thread(target=self._sysinfo_loop, daemon=True).start()

        self.after(120, self._poll_ui)
        self._tick_clock()
        self._poll_sys()
        if ENGINE_OK:
            self._append_system("J.A.R.V.I.S engine online. Ready for text or voice commands.")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =============================================================
    # Engine worker — background thread, never blocks the UI
    # =============================================================
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
                    self._run_chat(job)
                elif kind == "voice_capture":
                    text = self._capture_voice()
                    self.from_engine.put({"_kind": "voice_result", "text": text})
                elif kind == "shutdown":
                    break
            except Exception as exc:
                self.from_engine.put({"_kind": "error", "msg": str(exc)})

    def _sysinfo_loop(self):
        while not self._closing:
            try:
                info = get_system_info() if ENGINE_OK else {}
            except Exception:
                info = {}
            info["_ts"] = time.time()
            with self._sys_lock:
                self.sys_info = info
            time.sleep(2)

    # -------------------------------------------------------------
    # Process a single chat turn (engine thread)
    # -------------------------------------------------------------
    def _run_chat(self, job):
        user_text = job["text"]
        self.from_engine.put({"_kind": "user_msg", "text": user_text})
        self.from_engine.put({"_kind": "status", "status": "PROCESSING"})

        try:
            result = process_user_input(
                user_text, self.conversation, self.current_voice)
        except Exception as exc:
            result = {"response": f"I hit an error while processing that: {exc}"}

        out = result.get("response") or "I'm processing your request."
        voice_out = self.current_voice

        pref = result.get("voice_preference")
        if pref and pref in VOICES and pref != self.current_voice:
            self.current_voice = pref
            voice_out = pref
            self.from_engine.put({"_kind": "voice_switch", "voice": pref})

        tool_line = None
        if result.get("tool_call"):
            tc = result["tool_call"]
            name = tc.get("name")
            args = tc.get("arguments") or {}
            try:
                res = execute_function(name, args)
                tool_line = f"\u2699  {name.replace('_', ' ')} \u2192 {str(res)[:180]}"
                if "Success" in str(res):
                    out = f"{out} \u2705 {str(res).replace('Success: ', '')}"
            except Exception as exc:
                tool_line = f"\u2716  {name} \u2192 {exc}"

        self.conversation.append({"role": "user", "content": user_text})
        self.conversation.append({"role": "assistant", "content": out})
        if len(self.conversation) > 60:
            self.conversation = self.conversation[-60:]

        self.from_engine.put({
            "_kind": "ai_msg", "text": out, "voice": voice_out, "tool": tool_line,
        })

        # Optional spoken reply (runs in this background thread)
        if self.tts_enabled:
            self.from_engine.put({"_kind": "status", "status": "SPEAKING"})
            _speak_async(out, voice_out)
            self.from_engine.put({"_kind": "status", "status": "ONLINE"})

    # -------------------------------------------------------------
    # Optional voice capture (engine thread)
    # -------------------------------------------------------------
    def _capture_voice(self):
        if not (VOICE_INPUT and _sr and _SndMic):
            return ""
        try:
            rec = _sr.Recognizer()
            with _SndMic(sample_rate=16000) as source:
                rec.adjust_for_ambient_noise(source, duration=0.4)
                audio = rec.listen(source, timeout=8, phrase_time_limit=12)
            try:
                return rec.recognize_google(audio)
            except (_sr.UnknownValueError, _sr.RequestError):
                return ""
        except Exception:
            return ""
# =============================================================
    # UI construction
    # =============================================================
    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.header = self._build_header()
        self.header.grid(row=0, column=0, sticky="ew")

        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        self.nav = self._build_nav(body)
        self.nav.grid(row=0, column=0, sticky="nsw", padx=(0, 0))

        self.page_holder = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=0)
        self.page_holder.grid(row=0, column=1, sticky="nsew")
        self.page_holder.grid_rowconfigure(0, weight=1)
        self.page_holder.grid_columnconfigure(0, weight=1)

        self.pages = {
            "chat": self._build_chat_page(),
            "monitor": self._build_monitor_page(),
            "abilities": self._build_abilities_page(),
            "about": self._build_about_page(),
        }
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self._show_page("chat")

        self.statusbar = self._build_statusbar()
        self.statusbar.grid(row=2, column=0, sticky="ew")

    def _show_page(self, name):
        self.current_page = name
        for key, page in self.pages.items():
            page.tkraise()
        for key, btn in self.nav_buttons.items():
            btn.configure(fg_color=ACCENT if key == name else PANEL_2)

    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=88)
        head.grid_propagate(False)
        head.grid_columnconfigure(0, weight=0)
        head.grid_columnconfigure(1, weight=1)
        head.grid_columnconfigure(2, weight=0)

        left = ctk.CTkFrame(head, fg_color=BG, corner_radius=0)
        left.grid(row=0, column=0, sticky="w", padx=14)
        self._draw_reactor(left)
        brand = ctk.CTkFrame(left, fg_color=BG, corner_radius=0)
        brand.grid(row=0, column=1, padx=10)
        ctk.CTkLabel(brand, text="J.A.R.V.I.S", font=self.f_title,
                     text_color=ACCENT).pack(anchor="w")
        ctk.CTkLabel(brand, text="Just A Rather Very Intelligent System",
                     font=self.f_sub, text_color=MUTED).pack(anchor="w")
        ctk.CTkLabel(brand, text="v3.0  \u2022  Local AI Assistant",
                     font=self.f_sub, text_color=SOFT).pack(anchor="w")

        right = ctk.CTkFrame(head, fg_color=BG, corner_radius=0)
        right.grid(row=0, column=2, sticky="e", padx=14)
        self.personality_pill = ctk.CTkLabel(
            right, text="\U0001f589  JARVIS \u2014 ENGLISH", font=self.f_status,
            text_color=ACCENT, corner_radius=14, fg_color=PANEL_2, padx=14, pady=5)
        self.personality_pill.grid(row=0, column=0, padx=8)
        self.status_pill = ctk.CTkLabel(
            right, text="\u25cf  ONLINE", font=self.f_status,
            text_color=GOOD, corner_radius=14, fg_color=PANEL_2, padx=14, pady=5)
        self.status_pill.grid(row=0, column=1, padx=8)
        self.clock = ctk.CTkLabel(right, text="--:--:--", font=self.f_clock,
                                  text_color=TEXT)
        self.clock.grid(row=0, column=2, padx=8)
        return head

    def _draw_reactor(self, parent):
        box = ctk.CTkFrame(parent, width=64, height=64, fg_color=PANEL_2,
                           corner_radius=30, border_width=2, border_color=ACCENT)
        box.grid(row=0, column=0, padx=(0, 8), pady=4)
        react = tk.Canvas(box, width=58, height=58, bg=PANEL_2,
                          highlightthickness=0, bd=0)
        react.pack(expand=True)
        self._reactor = react
        self._reactor_phase = 0
        self._reactor_anim()
        return react

    def _reactor_anim(self):
        try:
            if getattr(self, "_reactor", None) is None:
                return
            c = self._reactor
            phase = self._reactor_phase
            m = 4 if phase < 6 else (10 - phase)  # pulse 0..6..0
            cx, cy = 29, 29
            c.delete("all")
            col = GOOD if self.status in ("ONLINE", "LISTENING") else WARN
            c.create_oval(cx-m+3, cy-m+3, cx+m+15, cy+m+15,
                          outline=ACCENT, width=2)
            c.create_oval(cx-m, cy-m, cx+m+18-3, cy+m+18-3,
                          outline=BORDER, width=1)
            c.create_oval(cx-12, cy-12, cx+12, cy+12, fill="black",
                          outline=ACCENT, width=3)
            c.create_oval(cx-3, cy-3, cx+3, cy+3, fill=ACCENT,
                          outline=col, width=2)
            # rotating tick marks
            for i in range(12):
                a = (phase * 15 + i * 30)
                import math
                rad = math.radians(a)
                r0, r1 = 12, 16
                x0 = cx + r0 * math.cos(rad)
                y0 = cy + r0 * math.sin(rad)
                x1 = cx + (r1 + m) * math.cos(rad)
                y1 = cy + (r1 + m) * math.sin(rad)
                c.create_line(x0, y0, x1, y1, fill=ACCENT, width=2)
            self._reactor_phase = (phase + 1) % 12
            self.after(120, self._reactor_anim)
        except Exception:
            pass
# =============================================================
    # Navigation sidebar
    # =============================================================
    def _build_nav(self, parent):
        nav = ctk.CTkFrame(parent, fg_color=PANEL_2, corner_radius=0,
                           width=210, border_width=0)
        nav.grid_propagate(False)
        nav.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(nav, text="COMMAND CENTRE",
                     font=(FONT, 13, "bold"), text_color=MUTED).grid(
            row=0, column=0, sticky="w", padx=18, pady=(18, 10))

        items = [
            ("chat", "\U0001f4ac  Chat with Jarvis"),
            ("monitor", "\U0001f4ca  System Monitor"),
            ("abilities", "\u2699  Abilities"),
            ("about", "\U0001f30d  About Project"),
        ]
        self.nav_buttons = {}
        for i, (key, label) in enumerate(items):
            btn = ctk.CTkButton(
                nav, text=label, font=self.f_nav, anchor="w",
                fg_color=ACCENT if key == "chat" else PANEL_2,
                hover_color=ACCENT_2, corner_radius=10, height=44)
            btn.grid(row=i + 1, column=0, sticky="ew", padx=10, pady=6)
            btn.configure(command=lambda k=key: self._show_page(k))
            self.nav_buttons[key] = btn

        footer = ctk.CTkFrame(nav, fg_color=PANEL_2, corner_radius=0)
        footer.grid(row=6, column=0, sticky="sew", padx=10, pady=6)
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(footer, text="\u25cf", text_color=GOOD,
                     font=self.f_small).grid(row=0, column=0, padx=6)
        ctk.CTkLabel(footer,
                     text="Engine Online" if ENGINE_OK else "Engine Unavailable",
                     text_color=(GOOD if ENGINE_OK else BAD), font=self.f_small,
                     ).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(footer, text="Local AI v3.0",
                     text_color=SOFT, font=self.f_small).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6)
        return nav
# =============================================================
    # Chat page
    # =============================================================
    def _build_chat_page(self):
        page = ctk.CTkFrame(self.page_holder, fg_color=PANEL, corner_radius=0)
        for r in range(4):
            page.grid_rowconfigure(r, weight=(1 if r == 0 else 0))
        page.grid_columnconfigure(0, weight=1)

        log_frame = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=0)
        log_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=(10, 6))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        log = tk.Text(log_frame, wrap="word", state="disabled", bg=PANEL_2,
                      fg=TEXT, insertbackground=ACCENT, selectbackground=ACCENT_2,
                      relief="flat", bd=0, padx=10, pady=8, font=(FONT, 12))
        scroll = ctk.CTkScrollbar(log_frame, command=log.yview)
        log.configure(yscrollcommand=scroll.set)
        log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        log.tag_configure("user", foreground=ACCENT_2, font=(FONT, 12),
                          lmargin1=20, lmargin2=20, spacing1=8, spacing3=10)
        log.tag_configure("ai", foreground=TEXT, font=(FONT, 12),
                          lmargin1=20, lmargin2=20, spacing1=8, spacing3=10)
        log.tag_configure("sys", foreground=ACCENT, font=(FONT, 11, "italic"),
                          spacing1=2, spacing3=6)
        log.tag_configure("tool", foreground=GOOD, font=(FONT, 10, "bold"),
                          spacing1=2, spacing3=6)
        log.tag_configure("meta", foreground=MUTED, font=(FONT, 9),
                          spacing1=2, spacing3=4)
        self.chat_log = log

        chips = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=0)
        chips.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        chips.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(chips, text="QUICK COMMANDS",
                     text_color=MUTED, font=self.f_small).grid(
            row=0, column=0, sticky="w", padx=4)
        self._build_chips(chips)

        inp = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=0)
        inp.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        inp.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(
            inp, placeholder_text="Type a command for Jarvis / Simmi \u2026 (or press the mic)",
            font=(FONT, 13), fg_color=PANEL, corner_radius=12, height=42)
        self.entry.grid(row=0, column=0, sticky="ew", padx=6)
        self.entry.bind("<Return>", lambda _e: self._send())

        self.mic_btn = ctk.CTkButton(
            inp, text="\U0001f3a4", width=48, height=42, corner_radius=12,
            fg_color=PANEL_2, hover_color=ACCENT_2, font=(FONT, 16),
            command=self._voice)
        self.mic_btn.grid(row=0, column=1, padx=4)

        ctk.CTkButton(inp, text="Send", width=96, height=42, corner_radius=12,
                      fg_color=ACCENT, hover_color=ACCENT_2, font=self.f_status,
                      command=self._send).grid(row=0, column=2, padx=4)

        bar = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=0)
        bar.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 8))
        bar.grid_columnconfigure(0, weight=1)
        self.tts_toggle = ctk.CTkSwitch(
            bar, text="Voice output (TTS)", font=self.f_small,
            progress_color=ACCENT, command=self._toggle_tts)
        self.tts_toggle.select()
        self.tts_toggle.grid(row=0, column=0, sticky="w", padx=6)
        self.persona_menu = ctk.CTkOptionMenu(
            bar, values=["Jarvis \u2014 English", "Jarvis \u2014 Hindi",
                         "Simmi \u2014 English"],
            command=self._set_persona, fg_color=PANEL, button_color=PANEL_2,
            button_hover_color=ACCENT_2, text_color=TEXT, font=self.f_small,
            dropdown_font=self.f_small)
        self.persona_menu.set("Jarvis \u2014 English")
        self.persona_menu.grid(row=0, column=1, sticky="e", padx=6)
        ctk.CTkButton(bar, text="\u21bb Clear", width=90, height=30,
                      corner_radius=10, fg_color=PANEL_2, hover_color=BAD,
                      font=self.f_small, command=self._clear_chat).grid(
            row=0, column=2, padx=6)
        return page

    def _build_chips(self, chips):
        cmds = [
            ("System status", "check my system status"),
            ("Open Chrome", "jarvis, open chrome"),
            ("Create notes", "create a text file called notes with my to-do list"),
            ("Make a doc", "create a word document about artificial intelligence"),
            ("Presentation", "create a presentation about the future of AI"),
            ("Search web", "search the web for latest AI news"),
            ("Calculate", "calculate 15% of 2500"),
            ("Screenshot", "take a screenshot"),
        ]
        for i, (label, prompt) in enumerate(cmds):
            ctk.CTkButton(
                chips, text=label, width=118, height=30, corner_radius=12,
                fg_color=PANEL_2, hover_color=ACCENT_2, font=self.f_small,
                command=lambda p=prompt: self._quick(p)).grid(
                row=1 + i // 4, column=i % 4, padx=4, pady=2)
# =============================================================
    # Monitor page — live system gauges
    # =============================================================
    def _build_monitor_page(self):
        page = ctk.CTkFrame(self.page_holder, fg_color=PANEL, corner_radius=0)
        page.grid_columnconfigure((0, 1), weight=1)
        page.grid_rowconfigure((0, 1, 2), weight=1)
        page.grid_rowconfigure(3, weight=0)

        ctk.CTkLabel(page, text="SYSTEM DIAGNOSTICS",
                     font=(FONT, 20, "bold"), text_color=ACCENT).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=8)
        ctk.CTkLabel(page,
                     text="Live telemetry refreshed every 2 seconds (psutil + NVIDIA).",
                     font=self.f_small, text_color=MUTED).grid(
            row=0, column=1, sticky="e", padx=16)

        self.gauges = {}
        metrics = [
            ("cpu", "CPU LOAD", ACCENT),
            ("mem", "MEMORY", ACCENT_2),
            ("disk", "DISK (C:)", GOOD),
            ("battery", "BATTERY", WARN),
        ]
        for i, (key, label, color) in enumerate(metrics):
            r, c = 1 + i // 2, i % 2
            card = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=14,
                                border_width=2, border_color=BORDER)
            card.grid(row=r, column=c, sticky="nsew", padx=16, pady=12)
            card.grid_columnconfigure(0, weight=1)
            val_label = ctk.CTkLabel(card, text="-- %", font=(FONT, 34, "bold"),
                                     text_color=color)
            val_label.grid(row=0, column=0, pady=(6, 0))
            ctk.CTkLabel(card, text=label, font=self.f_body,
                         text_color=MUTED).grid(row=1, column=0)
            pb = ctk.CTkProgressBar(card, height=16, corner_radius=6,
                                    progress_color=color, fg_color=PANEL)
            pb.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
            sub = ctk.CTkLabel(card, text="collecting \u2026", font=self.f_small,
                               text_color=SOFT)
            sub.grid(row=3, column=0)
            self.gauges[key] = (pb, val_label, sub, color)

        detail = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=12,
                              border_width=1, border_color=BORDER)
        detail.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=8)
        detail.grid_columnconfigure(0, weight=1)
        self.mon_detail = ctk.CTkLabel(detail, text="CPU cores / GPU / uptime",
                     font=self.f_body, text_color=TEXT)
        self.mon_detail.grid(row=0, column=0, sticky="w", padx=14)
        self.mon_ts = ctk.CTkLabel(detail, text="\u23f3 --:--:--", font=self.f_small,
                                   text_color=MUTED)
        self.mon_ts.grid(row=0, column=1, sticky="e", padx=14)
        return page
# =============================================================
    # Abilities page — feature showcase
    # =============================================================
    def _build_abilities_page(self):
        page = ctk.CTkFrame(self.page_holder, fg_color=PANEL, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(page, fg_color=PANEL_2, corner_radius=0)
        body.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="ASSISTANT ABILITIES",
                     font=(FONT, 20, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", padx=10, pady=6)

        groups = [
            ("\U0001f4dd  DOCUMENTS & CREATION",
             ["Create Word documents (.docx) with professional content",
              "Generate PowerPoint presentations (Professional + Creative engines)",
              "Build resumes with structured layouts",
              "Write & save text/notes files to generated_files/"]),
            ("\U0001f4bb  SYSTEM CONTROL",
             ["Open applications (Chrome, Notepad, Explorer, PowerShell\u2026)",
              "Live system diagnostics: CPU, RAM, Disk, Battery, GPU",
              "List running processes and search files on disk",
              "Take screenshots, run system commands"]),
            ("\U0001f50d  RESEARCH & TOOLS",
             ["Web search and fetch results for any topic",
              "Read + summarize file contents",
              "Clipboard read / write helper",
              "Instant math & calculation engine"]),
            ("\U0001f3a4  VOICE & PERSONALITY",
             ["Local Piper TTS \u2014 offline, no cloud needed",
              "Dual personalities: Jarvis (male) & Simmi (female)",
              "Automatic Hindi / English language detection",
              "Wake-word voice commands & barge-in"]),
        ]
        row = 1
        for grp, items in groups:
            ctk.CTkLabel(body, text=grp, font=self.f_nav, text_color=TEXT).grid(
                row=row, column=0, sticky="w", padx=10, pady=(12, 2))
            row += 1
            for it in items:
                ctk.CTkLabel(body, text="     \u2022  " + it, font=self.f_body,
                             text_color=MUTED, anchor="w").grid(
                    row=row, column=0, sticky="w", padx=10)
                row += 1
        return page
# =============================================================
    # About page — project showcase
    # =============================================================
    def _build_about_page(self):
        page = ctk.CTkFrame(self.page_holder, fg_color=PANEL, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure((0, 1, 2), weight=1)
        page.grid_rowconfigure(3, weight=0)

        title = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=14,
                             border_width=2, border_color=ACCENT)
        title.grid(row=0, column=0, sticky="new", padx=24, pady=(18, 8))
        title.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title, text="J.A.R.V.I.S", font=(FONT, 30, "bold"),
                     text_color=ACCENT).pack(pady=6)
        ctk.CTkLabel(title, text="Just A Rather Very Intelligent System",
                     font=(FONT, 16), text_color=TEXT).pack()
        ctk.CTkLabel(title,
                     text="A context-aware AI voice assistant that understands who "
                          "you are talking to \u2014 Jarvis or Simmi \u2014 without "
                          "any switch commands.",
                     font=self.f_body, text_color=MUTED, wraplength=820,
                     justify="left").pack(pady=6)

        stack = ctk.CTkFrame(page, fg_color=PANEL_2, corner_radius=12)
        stack.grid(row=1, column=0, sticky="nsew", padx=24, pady=6)
        stack.grid_columnconfigure(1, weight=1)
        rows = [
            ("\U0001f9e0  Adaptive Brain",
             "Groq + Cerebras + Google Gemini with automatic provider fallback & tool calling."),
            ("\U0001f3ac  Next-Gen Presentations",
             "4-step professional design engine + Pexels background-first creative engine."),
            ("\U0001f50a  Local Voice",
             "Piper neural TTS running 100% offline with English & Hindi voices."),
            ("\U0001f4eb  Tool Calling",
             "Documents, slides, system control, web, files \u2014 all via structured JSON tool calls."),
        ]
        for i, (head, desc) in enumerate(rows):
            card = ctk.CTkFrame(stack, fg_color=PANEL, corner_radius=8)
            card.grid(row=i, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
            ctk.CTkLabel(card, text=head, font=self.f_nav,
                         text_color=TEXT).grid(row=0, column=0, sticky="w",
                                               padx=12, pady=(6, 0))
            ctk.CTkLabel(card, text="  " + desc, font=self.f_body,
                         text_color=MUTED, anchor="w", justify="left").grid(
                row=0, column=1, sticky="w", padx=12)

        ctk.CTkLabel(page,
                     text="Built with Python \u2022 CustomTkinter \u2022 Groq \u2022 "
                          "Piper TTS \u2014 a FINAL YEAR showcase",
                     font=self.f_small, text_color=SOFT).grid(
            row=3, column=0, sticky="ew", padx=24, pady=(2, 10))
        return page

    # =============================================================
    # Status bar
    # =============================================================
    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL_2, corner_radius=0, height=26)
        bar.grid_propagate(False)
        bar.grid_columnconfigure(2, weight=1)
        self.status_glyph = ctk.CTkLabel(bar, text="\u25cf", text_color=GOOD,
                                         font=self.f_small)
        self.status_glyph.grid(row=0, column=0, padx=8)
        self.status_text = ctk.CTkLabel(
            bar, text="SYSTEM STATUS: " + self.status.title(),
            text_color=MUTED, font=self.f_small)
        self.status_text.grid(row=0, column=1, padx=4)
        self.status_extra = ctk.CTkLabel(bar, text="", text_color=SOFT,
                                         font=self.f_small)
        self.status_extra.grid(row=0, column=2, sticky="w", padx=4)
        self.voice_ind = ctk.CTkLabel(bar, text="VOICE: OFF", text_color=SOFT,
                                      font=self.f_small)
        self.voice_ind.grid(row=0, column=3, padx=8)
        return bar
# =============================================================
    # Poll engine messages (UI thread)
    # =============================================================
    def _poll_ui(self):
        if self._closing:
            return
        try:
            while True:
                msg = self.from_engine.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.after(120, self._poll_ui)

    def _handle_msg(self, msg):
        kind = msg.get("_kind")
        if kind == "user_msg":
            self._append_user(msg.get("text", ""))
            self._set_status("PROCESSING")
        elif kind == "ai_msg":
            self._append_ai(msg.get("text", ""))
            if msg.get("tool"):
                self._append_tool(msg["tool"])
            self._append_meta("(voice: %s)" % PERSONA_LABEL.get(msg.get("voice"), "?"))
            self._set_status("ONLINE")
        elif kind == "status":
            self._set_status(msg.get("status", "ONLINE"))
        elif kind == "voice_switch":
            self.current_voice = msg.get("voice", self.current_voice)
            self._sync_persona_ui()
        elif kind == "voice_result":
            text = (msg.get("text") or "").strip()
            if text:
                self._send_text(text)
            else:
                self._append_sys("(no speech recognised)")
                self._set_status("ONLINE")
        elif kind == "error":
            self._append_sys("Engine error: " + msg.get("msg", ""))
            self._set_status("ERROR")
        elif kind == "system":
            self._append_system(msg.get("text", ""))

    def _set_status(self, status):
        status = status.upper()
        style = STATUS_STYLE.get(status, STATUS_STYLE["IDLE"])
        self.status = status
        self.status_glyph.configure(text=style["glyph"], text_color=style["color"])
        self.status_text.configure(text="SYSTEM STATUS: " + status,
                                   text_color=style["color"])
        try:
            self.status_pill.configure(text=f"{style['glyph']}  {status}",
                                       text_color=style["color"])
        except Exception:
            pass

    def _sync_persona_ui(self):
        try:
            label = PERSONA_LABEL.get(self.current_voice, "JARVIS")
            self.personality_pill.configure(text="\U0001f589  " + label,
                                            text_color=ACCENT)
        except Exception:
            pass

    # =============================================================
    # Logging helpers (UI thread only)
    # =============================================================
    def _append(self, text, tag):
        self.chat_log.configure(state="normal")
        self.chat_log.insert("end", text + "\n", tag)
        self.chat_log.see("end")
        self.chat_log.configure(state="disabled")

    def _append_user(self, text):
        self._append("\U0001f4ac  You\n        " + text, "user")

    def _append_ai(self, text):
        name = PERSONA_LABEL.get(self.current_voice, "AI").split(" \u2014")[0]
        self._append("\U0001f916  " + name + "\n        " + text, "ai")

    def _append_system(self, text):
        self._append("\u26a1  " + text, "sys")

    def _append_tool(self, text):
        self._append(text, "tool")

    def _append_meta(self, text):
        self._append(text, "meta")
# =============================================================
    # User actions
    # =============================================================
    def _send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._send_text(text)

    def _send_text(self, text):
        if self._busy:
            self._append_sys("(queued \u2014 the engine is still busy)")
        self.to_engine.put({"_kind": "chat", "text": text})

    def _quick(self, prompt):
        self._send_text(prompt)

    def _voice(self):
        if not VOICE_INPUT:
            self._append_system("Voice input unavailable (SpeechRecognition/sounddevice).")
            return
        self._set_status("LISTENING")
        self.status_extra.configure(text="listening \u2026")
        self.to_engine.put({"_kind": "voice_capture"})

    def _clear_chat(self):
        self.chat_log.configure(state="normal")
        self.chat_log.delete("1.0", "end")
        self.chat_log.configure(state="disabled")
        self._append_system("Conversation cleared.")

    def _toggle_tts(self):
        self.tts_enabled = bool(self.tts_toggle.get())
        self.voice_ind.configure(
            text="VOICE: ON" if self.tts_enabled else "VOICE: OFF",
            text_color=(ACCENT if self.tts_enabled else SOFT))

    def _set_persona(self, value):
        mapping = {
            "Jarvis \u2014 English": "en_male",
            "Jarvis \u2014 Hindi": "hi_male",
            "Simmi \u2014 English": "en_female",
        }
        self.current_voice = mapping.get(value, "en_male")
        self._sync_persona_ui()

    # =============================================================
    # Periodic refresh (clock + system monitor)
    # =============================================================
    def _tick_clock(self):
        now = _dt.datetime.now()
        self.clock.configure(text=now.strftime("%H:%M:%S"))
        self.after(1000, self._tick_clock)

    def _poll_sys(self):
        if self._closing:
            return
        with self._sys_lock:
            info = dict(self.sys_info)
        if info:
            self._refresh_gauges(info)
        self.after(500, self._poll_sys)

    def _refresh_gauges(self, info):
        def pct(key):
            v = info.get(key)
            if v is None:
                return None
            if isinstance(v, str):
                try:
                    return float(v.replace("%", ""))
                except Exception:
                    return None
            try:
                return float(v)
            except Exception:
                return None

        labels = {
            "cpu": "CPU LOAD",
            "mem": "MEMORY",
            "disk": "DISK (C:)",
            "battery": "BATTERY",
        }
        for key in self.gauges:
            pb, val_label, sub, color = self.gauges[key]
            val = pct(key)
            if val is None:
                continue
            val = max(0.0, min(100.0, val))
            pb.set(val / 100.0)
            val_label.configure(text=f"{val:.0f} %")
            sub_text = labels[key]
            if key == "mem" and "memory_total" in info:
                sub_text = labels[key] + "  (" + str(info["memory_total"]) + " total)"
            sub.configure(text=sub_text)

        detail = "CPU: " + str(info.get("cpu_count", "?")) + "  \u2022  "
        gpu = info.get("gpu")
        if gpu and isinstance(gpu, list) and gpu:
            detail += "GPU: " + str(gpu[0].get("name", "?"))[:24]
        else:
            detail += "GPU: N/A"
        detail += "  \u2022  Battery: " + str(info.get("battery", "N/A"))
        self.mon_detail.configure(text=detail)
        ts = info.get("_ts")
        if ts:
            self.mon_ts.configure(
                text="\u23f3  updated " + time.strftime("%H:%M:%S", time.localtime(ts)))

    # =============================================================
    # Shutdown
    # =============================================================
    def _on_close(self):
        self._closing = True
        try:
            self.to_engine.put({"_kind": "shutdown"})
        except Exception:
            pass
        self.destroy()
# =============================================================
# Entry point
# =============================================================
def main():
    if ctk is None:
        print("CustomTkinter is not installed.\nInstall with: pip install customtkinter")
        return
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    if not ENGINE_OK:
        print("WARNING: Jarvis engine could not be loaded. GUI runs in demo mode.")
    app = JarvisGUI()
    app.mainloop()


if __name__ == "__main__":
    main()