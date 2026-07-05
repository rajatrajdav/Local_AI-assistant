"""
J.A.R.V.I.S. Desktop Application — Console Mode
=================================================
Runs the Jarvis voice assistant natively on the system (console-based).
Uses Piper TTS + sounddevice for audio output — NO UI needed.

Usage:
    python main.py          → Console voice/text assistant
"""

import os
import sys

# Handle PyInstaller frozen executable paths
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

os.environ["JARVIS_BASE_DIR"] = BASE_DIR
os.chdir(BASE_DIR)  # Ensure CWD is the project root for voice file paths


def main():
    """Run the native console-based voice assistant (jarvis.py)."""
    print("=" * 56)
    print("  J.A.R.V.I.S. AI ASSISTANT")
    print("  Console Mode")
    print("=" * 56)
    print()
    print("  Audio: Piper TTS (local, offline)")
    print("  LLM  : Groq API (needs internet)")
    print("  Input: Type text or use 'v' for voice")
    print()

    # Import and run jarvis.py's async main loop
    from jarvis import chat_with_voice_assistant

    import asyncio
    try:
        asyncio.run(chat_with_voice_assistant())
    except KeyboardInterrupt:
        print("\n\n  Application stopped by user.")
    except Exception as e:
        print(f"\n  Fatal error: {e}")
        import traceback
        traceback.print_exc()
        input("\n  Press Enter to exit...")


if __name__ == "__main__":
    main()