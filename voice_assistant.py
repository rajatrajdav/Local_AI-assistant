"""
Jarvis Voice Assistant — STT → Gemini 3.1 Flash Live (native) → TTS
=====================================================================
A fast, continuous-loop voice assistant that uses Gemini 3.1 Flash Live
Preview natively — with intelligent Voice Activity Detection (VAD) for
natural conversation pacing.

The assistant listens intelligently:
  - Detects when you START speaking (voice activity)
  - Detects when you STOP speaking (natural silence pause)
  - Responds at a natural pace — not too quick, not too delayed
  - No fixed timeouts — adapts to your speech rhythm

  1. Listens  (VAD-based — detects natural speech boundaries)
  2. Thinks   (Gemini 3.1 Flash Live Preview — real-time optimized)
  3. Speaks   (Text-to-Speech via pyttsx3 — offline, no API key needed)

Usage:
    python voice_assistant.py

Configuration:
    Set your Gemini API key in the .env file:
      GEMINI_API_KEY=your_key_here

Required packages:
    pip install speechrecognition pyttsx3 google-generativeai python-dotenv pyaudio numpy sounddevice

    If pyaudio fails to install on Windows:
        pip install pipwin
        pipwin install pyaudio
"""

import os
import sys
import time
import json
import struct
import math
from pathlib import Path
from collections import deque

# ── Load environment variables ──────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv()

# ── Speech Recognition ──────────────────────────────────────────────────────
import speech_recognition as sr

# ── Text-to-Speech (offline, cross-platform) ────────────────────────────────
import pyttsx3

# ── Audio processing for VAD ────────────────────────────────────────────────
import numpy as np
import sounddevice as sd

# ============================================================================
# CONFIGURATION
# ============================================================================

# ── 1. LLM Provider — Gemini 3.1 Flash Live Preview (NATIVE, no fallback) ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or "your-gemini-api-key-here"
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.1-flash-live-preview"

if not GEMINI_API_KEY or GEMINI_API_KEY == "your-gemini-api-key-here":
    print("⚠  No GEMINI_API_KEY found. Set it in .env or edit the script.")
    print("   Get a free key from https://aistudio.google.com/app/apikey")
    sys.exit(1)

# ── Initialize Gemini 3.1 Flash Live Preview ──────────────────────────────
import google.generativeai as genai
genai.configure(api_key=GEMINI_API_KEY)

generation_config = {
    "temperature": 0.5,
    "top_p": 0.8,
    "top_k": 40,
    "max_output_tokens": 200,
    "candidate_count": 1,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
]

gemini_model = genai.GenerativeModel(
    GEMINI_MODEL,
    generation_config=generation_config,
    safety_settings=safety_settings,
)

# ── 2. Wake word ────────────────────────────────────────────────────────────
WAKE_WORD = "Jarvis"

# ── 3. Voice Activity Detection (VAD) Settings ──────────────────────────────
# These control how the assistant listens — natural conversation pacing
SAMPLE_RATE = 16000                # 16kHz for speech recognition
CHANNELS = 1
FRAME_DURATION_MS = 30             # 30ms frames for VAD (standard)
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples

# Energy threshold for VAD (adjust based on ambient noise)
VAD_ENERGY_THRESHOLD = 300         # RMS energy threshold for speech detection
VAD_SILENCE_DURATION = 1.2         # Seconds of silence before considering speech complete
VAD_MIN_SPEECH_DURATION = 0.3      # Minimum speech duration to ignore short noises
VAD_MAX_SPEECH_DURATION = 15.0     # Maximum recording duration (safety limit)
VAD_PRE_SPEECH_BUFFER = 0.5        # Seconds to keep before speech starts (for context)

# ── 4. Microphone settings ──────────────────────────────────────────────────
MIC_DEVICE_INDEX = None

# ── 5. Voice settings (pyttsx3) ─────────────────────────────────────────────
TTS_VOICE_RATE = 190
TTS_VOLUME = 0.9

# ============================================================================
# INITIALIZE ENGINE
# ============================================================================

print("=" * 60)
print("  J.A.R.V.I.S. — Voice Assistant")
print("  Just A Rather Very Intelligent System")
print("=" * 60)

# ── TTS Engine ──────────────────────────────────────────────────────────────
tts_engine = pyttsx3.init()
tts_engine.setProperty("rate", TTS_VOICE_RATE)
tts_engine.setProperty("volume", TTS_VOLUME)

voices = tts_engine.getProperty("voices")
for v in voices:
    if "david" in v.name.lower() or "zira" in v.name.lower() or "male" in v.name.lower():
        tts_engine.setProperty("voice", v.id)
        break

print(f"  TTS Engine: {tts_engine.getProperty('name')}")
print(f"  Wake Word : {'Enabled (' + WAKE_WORD + ')' if WAKE_WORD else 'Disabled (always listening)'}")
print(f"  LLM       : Gemini 3.1 Flash Live Preview — NATIVE (no fallback)")
print(f"  VAD       : Intelligent silence detection ({VAD_SILENCE_DURATION}s pause threshold)")
print("=" * 60 + "\n")

# ── LLM System Prompt ──────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are JARVIS, the AI assistant from Iron Man. "
    "You are highly intelligent, articulate, professional, and slightly witty. "
    "Respond in 1-2 short sentences. Be direct and conversational. "
    "Never mention you are an AI. Just respond as Jarvis would."
)

# ── Conversation history ────────────────────────────────────────────────────
conversation_history = []

# ============================================================================
# VOICE ACTIVITY DETECTION (VAD)
# ============================================================================


def compute_rms(audio_chunk: bytes) -> float:
    """
    Compute Root Mean Square (RMS) energy of an audio chunk.
    Higher RMS = louder sound (likely speech).
    Lower RMS = quieter sound (likely silence/background).
    """
    if len(audio_chunk) < 2:
        return 0.0
    count = len(audio_chunk) // 2
    fmt = f"<{count}h"
    try:
        samples = struct.unpack(fmt, audio_chunk[:count * 2])
        sum_sq = sum(s * s for s in samples)
        return math.sqrt(sum_sq / count)
    except (struct.error, ValueError):
        return 0.0


def listen_with_vad() -> bytes | None:
    """
    Listen with intelligent Voice Activity Detection.
    
    How it works:
    1. Continuously monitors audio from the microphone in 30ms frames
    2. Computes RMS energy for each frame
    3. When energy exceeds threshold → speech STARTED
    4. Buffers all audio while speech is active
    5. When silence persists for VAD_SILENCE_DURATION → speech ENDED
    6. Returns the complete audio chunk for transcription
    
    This creates a natural conversation flow — the assistant
    waits for you to FINISH speaking, then responds naturally.
    Not too quick (doesn't cut you off), not too delayed (doesn't
    make you wait after you've finished talking).
    """
    print("\n  🎤 [Listening... Speak now]")
    
    audio_buffer = bytearray()
    speech_active = False
    silence_frames = 0
    speech_frames = 0
    pre_speech_buffer = deque(maxlen=int(VAD_PRE_SPEECH_BUFFER * 1000 / FRAME_DURATION_MS))
    
    # Calculate frame limits
    silence_frame_limit = int(VAD_SILENCE_DURATION * 1000 / FRAME_DURATION_MS)
    max_speech_frames = int(VAD_MAX_SPEECH_DURATION * 1000 / FRAME_DURATION_MS)
    min_speech_frames = int(VAD_MIN_SPEECH_DURATION * 1000 / FRAME_DURATION_MS)
    
    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='int16',
            device=MIC_DEVICE_INDEX,
            blocksize=FRAME_SIZE,
        ) as stream:
            
            while True:
                # Read one frame of audio (30ms)
                data, _ = stream.read(FRAME_SIZE)
                rms = compute_rms(data)
                
                # Store in rolling pre-speech buffer (keeps last 0.5s of audio)
                pre_speech_buffer.append(bytes(data))
                
                if rms > VAD_ENERGY_THRESHOLD:
                    # ── SPEECH DETECTED ──
                    if not speech_active:
                        # Speech just started!
                        speech_active = True
                        speech_frames = 0
                        silence_frames = 0
                        # Include the pre-speech buffer so we don't clip the start
                        for chunk in pre_speech_buffer:
                            audio_buffer.extend(chunk)
                        audio_buffer.extend(data)
                        print("  🗣  [Speech started...]", end="", flush=True)
                    else:
                        # Continue recording speech
                        audio_buffer.extend(data)
                        silence_frames = 0
                    speech_frames += 1
                    
                else:
                    # ── SILENCE / NO SPEECH ──
                    if speech_active:
                        silence_frames += 1
                        audio_buffer.extend(data)
                        
                        # Check if silence is long enough to end utterance
                        if silence_frames >= silence_frame_limit:
                            # Natural pause detected — speech is complete
                            if speech_frames >= min_speech_frames:
                                print(f"\n  ✅ [End of speech — {silence_frames * FRAME_DURATION_MS / 1000:.1f}s silence]")
                                return bytes(audio_buffer)
                            else:
                                # Too short — probably a cough/click, discard
                                print("  [too short, discarding]")
                                speech_active = False
                                audio_buffer.clear()
                                silence_frames = 0
                                speech_frames = 0
                        
                        # Safety limit — max speech duration
                        if speech_frames >= max_speech_frames:
                            print(f"\n  ⏰ [Max speech duration reached ({VAD_MAX_SPEECH_DURATION}s)]")
                            return bytes(audio_buffer)
                    else:
                        # Not in speech mode — just keep updating pre-speech buffer
                        pass
                        
    except Exception as e:
        print(f"\n  ⚠ [Microphone error]: {e}")
        return None


def transcribe_audio(audio_data: bytes) -> str | None:
    """
    Transcribe audio using Google Web Speech API.
    Converts raw PCM bytes to text.
    """
    if not audio_data or len(audio_data) < 100:
        return None
    
    try:
        # Create an AudioData object from raw PCM (16-bit, 16kHz)
        audio = sr.AudioData(audio_data, SAMPLE_RATE, 2)
        text = audio.recognize_google(audio, language="en-IN,en-US")
        return text
    except sr.UnknownValueError:
        print("  ❌ [Could not understand audio]")
        return None
    except sr.RequestError as e:
        print(f"  ⚠ [Speech recognition service error]: {e}")
        return None
    except Exception as e:
        print(f"  ⚠ [Transcription error]: {e}")
        return None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def speak(text: str) -> None:
    """Convert text to speech using pyttsx3 (offline, no API key)."""
    print(f"  🗣  Jarvis: {text}")
    tts_engine.say(text)
    tts_engine.runAndWait()


def ask_llm(user_input: str) -> str:
    """
    Send user input to Gemini 3.1 Flash Live Preview natively.
    Maintains conversation history for natural context.
    """
    global conversation_history

    try:
        messages = [{"role": "user", "parts": [SYSTEM_PROMPT]}]
        
        # Add last 3 exchanges for context
        for msg in conversation_history[-6:]:
            messages.append(msg)
        
        messages.append({"role": "user", "parts": [user_input]})

        start_time = time.time()
        response = gemini_model.generate_content(
            messages,
            stream=False,
        )
        elapsed = time.time() - start_time
        print(f"  ⚡ [Gemini 3.1 Flash Live responded in {elapsed:.2f}s]")

        reply = response.text.strip()

        # Store in conversation history
        conversation_history.append({"role": "user", "parts": [user_input]})
        conversation_history.append({"role": "model", "parts": [reply]})
        if len(conversation_history) > 10:
            conversation_history = conversation_history[-10:]

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
            return "I'm unable to respond to that request, sir."

        print(f"  ⚠ [Gemini 3.1 Error]: {e}")
        return "I encountered an unexpected error, sir. Please try again."


# ============================================================================
# MAIN LOOP
# ============================================================================


def main():
    """Run the voice assistant in a continuous loop with VAD-based listening."""
    speak("System online. How may I assist you, sir?")

    while True:
        try:
            # ── Step 1: Listen with VAD (intelligent speech detection) ──────
            # The VAD system:
            #   - Detects when you START speaking (energy threshold)
            #   - Buffers audio while you speak
            #   - Detects when you STOP (1.2s of silence)
            #   - Returns the complete utterance
            # This creates NATURAL conversation pacing — not too quick,
            # not too delayed. The assistant waits for you to finish.
            audio_data = listen_with_vad()

            if not audio_data:
                continue

            # ── Step 1b: Transcribe ─────────────────────────────────────────
            print("  🧠 [Transcribing...]")
            user_text = transcribe_audio(audio_data)

            if not user_text:
                continue

            print(f"  📝 [You said]: {user_text}")

            # ── Wake word check ─────────────────────────────────────────────
            if WAKE_WORD and WAKE_WORD.lower() not in user_text.lower():
                print(f"  ⏭ [Wake word '{WAKE_WORD}' not detected, ignoring]")
                continue

            # Strip wake word
            user_text = user_text.lower().replace(WAKE_WORD.lower(), "").strip()
            for filler in ["please", "could you", "can you", "would you", "i need you to"]:
                if user_text.startswith(filler):
                    user_text = user_text[len(filler):].strip()
            if not user_text:
                user_text = "yes?"

            # ── Step 2: Think (Gemini 3.1 Flash Live — ultra-fast) ──────────
            print("  🧠 [Thinking...]")
            reply = ask_llm(user_text)

            # ── Step 3: Speak ───────────────────────────────────────────────
            speak(reply)

        except KeyboardInterrupt:
            print("\n\nShutting down. Goodbye, sir.")
            speak("Goodbye, sir.")
            break

        except Exception as e:
            print(f"\n⚠  [Unexpected error]: {e}")
            speak("I encountered an unexpected issue, sir. I am still operational.")
            time.sleep(1)
            continue


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()