"""
Jarvis Voice Assistant — STT → Gemini LLM → TTS
==================================================
A clean, continuous-loop voice assistant that:

  1. Listens  (Speech-to-Text via speech_recognition + PyAudio)
  2. Thinks   (Gemini via Google AI Studio API)
  3. Speaks   (Text-to-Speech via pyttsx3 — offline, no API key needed)

Usage:
    python voice_assistant.py

Configuration:
    Set your Gemini API key in the .env file:
      GEMINI_API_KEY=your_key_here

Required packages:
    pip install speechrecognition pyttsx3 google-generativeai python-dotenv pyaudio

    If pyaudio fails to install on Windows:
        pip install pipwin
        pipwin install pyaudio
"""

import os
import sys
import time
import json
from pathlib import Path

# ── Load environment variables ──────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv()

# ── Speech Recognition ──────────────────────────────────────────────────────
import speech_recognition as sr

# ── Text-to-Speech (offline, cross-platform) ────────────────────────────────
import pyttsx3

# ============================================================================
# CONFIGURATION
# ============================================================================

# ── 1. LLM Provider — Gemini (Google AI Studio) ─────────────────────────────
# Get your free API key at: https://aistudio.google.com/app/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or "your-gemini-api-key-here"
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"

# Validation
if not GEMINI_API_KEY or GEMINI_API_KEY == "your-gemini-api-key-here":
    print("⚠  No GEMINI_API_KEY found. Set it in .env or edit the script.")
    print("   Get a free key from https://aistudio.google.com/app/apikey")
    sys.exit(1)

# ── Initialize Gemini ─────────────────────────────────────────────────────
import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL)

# ── 2. Wake word ────────────────────────────────────────────────────────────
# The assistant only responds when it hears this word (case-insensitive).
# Set to None or empty string to respond to EVERY utterance.
WAKE_WORD = "Jarvis"

# ── 3. Microphone settings ──────────────────────────────────────────────────
MIC_DEVICE_INDEX = None       # None = default microphone
MIC_TIMEOUT = 5                # seconds to wait for speech to start
MIC_PHRASE_LIMIT = 10          # max seconds per utterance

# ── 4. Voice settings (pyttsx3) ─────────────────────────────────────────────
TTS_VOICE_RATE = 180           # words per minute (default ~200)
TTS_VOLUME = 0.9               # 0.0 to 1.0

# ============================================================================
# INITIALIZE ENGINE
# ============================================================================

print("=" * 54)
print("  J.A.R.V.I.S. — Voice Assistant")
print("  Just A Rather Very Intelligent System")
print("=" * 54)

# ── Recognizer ──────────────────────────────────────────────────────────────
recognizer = sr.Recognizer()
recognizer.energy_threshold = 1000       # sensitivity to ambient noise
recognizer.dynamic_energy_threshold = True
recognizer.dynamic_energy_adjustment_damping = 0.15
recognizer.dynamic_energy_ratio = 1.5
recognizer.pause_threshold = 0.8         # pause before end-of-speech
recognizer.non_speaking_duration = 0.5

# ── TTS Engine ──────────────────────────────────────────────────────────────
tts_engine = pyttsx3.init()
tts_engine.setProperty("rate", TTS_VOICE_RATE)
tts_engine.setProperty("volume", TTS_VOLUME)

# Try to select a good voice (optional)
voices = tts_engine.getProperty("voices")
for v in voices:
    if "david" in v.name.lower() or "zira" in v.name.lower() or "male" in v.name.lower():
        tts_engine.setProperty("voice", v.id)
        break

print(f"  TTS Engine: {tts_engine.getProperty('name')}")
print(f"  Wake Word : {'Enabled (' + WAKE_WORD + ')' if WAKE_WORD else 'Disabled (always listening)'}")
print(f"  LLM       : Gemini ({GEMINI_MODEL})")
print("=" * 54 + "\n")

# ── LLM System Prompt ───────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are JARVIS, the AI assistant from Iron Man. "
    "You are highly intelligent, articulate, professional, and slightly witty. "
    "You speak concisely — respond in 1–3 sentences unless asked for detail. "
    "You are loyal to your user ('Sir') and speak with calm confidence. "
    "Never mention that you are an AI or language model. "
    "Just respond as Jarvis would."
)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def speak(text: str) -> None:
    """Convert text to speech using pyttsx3 (offline, no API key)."""
    print(f"  🗣  Jarvis: {text}")
    tts_engine.say(text)
    tts_engine.runAndWait()


def listen(use_wake_word: bool = True) -> str | None:
    """
    Capture microphone input and convert to text.

    Args:
        use_wake_word: If True, waits for the wake word before transcribing.

    Returns:
        Transcribed text string, or None if nothing was captured.
    """
    with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
        print("\n  🎤 [Listening...]" if not use_wake_word else "\n  🎤 [Waiting for 'Jarvis'...]")
        recognizer.adjust_for_ambient_noise(source, duration=0.3)

        try:
            audio = recognizer.listen(
                source,
                timeout=MIC_TIMEOUT,
                phrase_time_limit=MIC_PHRASE_LIMIT,
            )
        except sr.WaitTimeoutError:
            # No speech detected before timeout — that's normal in a loop
            return None

    # ── Transcribe ──────────────────────────────────────────────────────────
    try:
        text = recognizer.recognize_google(audio, language="en-IN,en-US")
    except sr.UnknownValueError:
        print("  ❌ [Could not understand audio]")
        return None
    except sr.RequestError as e:
        print(f"  ⚠ [Speech recognition service error]: {e}")
        return None

    if not text:
        return None

    print(f"  📝 [You said]: {text}")

    # ── Wake word check ─────────────────────────────────────────────────────
    if use_wake_word and WAKE_WORD:
        if WAKE_WORD.lower() not in text.lower():
            return None
        # Strip the wake word from the text before sending to LLM
        text = text.lower().replace(WAKE_WORD.lower(), "").strip()
        # Also remove common filler after wake word
        for filler in ["please", "could you", "can you", "would you", "i need you to"]:
            if text.startswith(filler):
                text = text[len(filler):].strip()
        return text if text else "yes?"

    return text


def ask_llm(user_input: str) -> str:
    """
    Send user input to Gemini and return the response.

    Handles connection errors, rate limits, and unexpected failures
    so the loop never crashes.
    """
    try:
        # Build the full prompt with system instructions
        full_prompt = f"{SYSTEM_PROMPT}\n\nUser: {user_input}"
        response = gemini_model.generate_content(
            full_prompt,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 300,
            },
        )
        reply = response.text.strip()
        return reply

    except Exception as e:
        err_msg = str(e).lower()

        if "rate limit" in err_msg or "429" in err_msg or "resource exhausted" in err_msg:
            return "I'm being rate-limited, sir. Give me a moment."

        if "unauthorized" in err_msg or "401" in err_msg or "invalid api key" in err_msg or "api key" in err_msg:
            return "My API key seems to be invalid, sir. Please check the configuration."

        if "quota" in err_msg or "exceeded" in err_msg:
            return "My API quota has been exhausted, sir. I'll need a top-up."

        if "connection" in err_msg or "timeout" in err_msg or "deadline exceeded" in err_msg:
            return "I'm having trouble reaching my servers, sir. Check your internet connection."

        if "safety" in err_msg or "blocked" in err_msg or "harmful" in err_msg:
            return "I'm unable to respond to that request, sir. It appears to violate content safety guidelines."

        # Fallback for any other error — don't crash
        print(f"  ⚠ [Gemini Error]: {e}")
        return "I encountered an unexpected error, sir. Please try again."


# ============================================================================
# MAIN LOOP
# ============================================================================


def main():
    """Run the voice assistant in a continuous loop."""
    # Startup greeting
    speak("System online. How may I assist you, sir?")

    while True:
        try:
            # ── Step 1: Listen ──────────────────────────────────────────────
            user_text = listen(use_wake_word=True)

            if not user_text:
                # No speech or wake word not detected — loop again
                continue

            # ── Step 2: Think ───────────────────────────────────────────────
            print("  🧠 [Thinking...]")
            reply = ask_llm(user_text)

            # ── Step 3: Speak ───────────────────────────────────────────────
            speak(reply)

        except KeyboardInterrupt:
            print("\n\nShutting down. Goodbye, sir.")
            speak("Goodbye, sir.")
            break

        except Exception as e:
            # Catch-all to prevent the loop from crashing
            print(f"\n⚠  [Unexpected error]: {e}")
            speak("I encountered an unexpected issue, sir. I am still operational.")
            time.sleep(1)
            continue


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()