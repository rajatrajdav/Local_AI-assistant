"""
Jarvis API Server — Full Backend Integration
==============================================
Exposes ALL jarvis.py features as REST API endpoints.
Usage: python api_server.py
       Then open http://localhost:5000
"""

import os
import sys
import json
import time
import asyncio
import threading
import traceback
import re
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── App setup ─────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/api/*": {"origins": "*"}})

if getattr(sys, 'frozen', False):
    BASE_DIR = os.environ.get("JARVIS_BASE_DIR", os.path.dirname(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR = os.path.join(BASE_DIR, "generated_files")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ================================================================
# GROQ LLM
# ================================================================
USE_GROQ = False
groq_client = None
try:
    from groq import Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    if GROQ_API_KEY:
        groq_client = Groq(api_key=GROQ_API_KEY)
        USE_GROQ = True
        print("✓ Groq API connected")
    else:
        print("⚠ GROQ_API_KEY not found in .env")
except Exception as e:
    print(f"⚠ Groq connection failed: {e}")

# ================================================================
# PIPER TTS
# ================================================================
PIPER_AVAILABLE = False
voice_engines = {}
try:
    from piper import PiperVoice
    import numpy as np
    import sounddevice as sd
    import pygame

    POSSIBLE_VOICE_ROOTS = [
        os.path.join(BASE_DIR, "voices"),
    ]
    
    def find_voice_file(model_name, ext):
        for root in POSSIBLE_VOICE_ROOTS:
            for subdir in ["english", "en"]:
                path = os.path.join(root, subdir, f"{model_name}.{ext}")
                if os.path.exists(path): return path
            path = os.path.join(root, f"{model_name}.{ext}")
            if os.path.exists(path): return path
            for subdir in ["hindi", "hi"]:
                path = os.path.join(root, subdir, f"{model_name}.{ext}")
                if os.path.exists(path): return path
        return None

    VOICES_MODELS = {
        "en_male": {"model_name": "en_US-hfc_male-medium", "name": "English Male"},
        "en_female": {"model_name": "en_US-libritts_r-medium", "name": "English Female"},
        "hi_male": {"model_name": "hi_IN-pratham-medium", "name": "Hindi Male"},
    }
    for key, info in VOICES_MODELS.items():
        try:
            model_path = find_voice_file(info["model_name"], "onnx")
            config_path = find_voice_file(info["model_name"], "onnx.json")
            if model_path and config_path:
                voice_engines[key] = PiperVoice.load(model_path, config_path=config_path)
                print(f"✓ Loaded voice: {info['name']}")
        except Exception as e:
            print(f"⚠ Failed to load {info['name']}: {e}")
    if voice_engines:
        PIPER_AVAILABLE = True
        print(f"✓ Piper TTS ready ({len(voice_engines)} voices)")
    else:
        print("⚠ No Piper voices loaded")
except Exception as e:
    print(f"⚠ Piper TTS not available: {e}")

# ================================================================
# SYSTEM TOOLS
# ================================================================
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
import pyperclip
import speech_recognition as sr

# ================================================================
# IMPORT BACKEND TOOLS
# ================================================================
def import_backend_tools():
    """Lazy-import jarvis functions to avoid circular imports."""
    from jarvis import (
        create_word_document, create_presentation, create_resume,
        open_application, get_system_info, write_to_clipboard,
        read_clipboard, create_file, list_files as jarvis_list_files
    )
    return {
        "create_word_document": create_word_document,
        "create_presentation": create_presentation,
        "create_resume": create_resume,
        "open_application": open_application,
        "get_system_info": get_system_info,
        "write_to_clipboard": write_to_clipboard,
        "read_clipboard": read_clipboard,
        "create_file": create_file,
        "list_files": jarvis_list_files,
    }

# ================================================================
# PERSONALITIES
# ================================================================
PERSONALITIES = {
    "en_male": {
        "name": "Jarvis",
        "system_prompt": """You are Jarvis, a professional and efficient male AI assistant.
Your name is JARVIS. Speak in a professional, concise, authoritative tone.
Keep conversational responses SHORT (1-2 sentences).
For document/presentation content, generate DETAILED, COMPREHENSIVE material.

Available tools: create_word_document, create_presentation, create_resume, 
open_application, get_system_info, write_to_clipboard, create_file.

RESPOND WITH VALID JSON ONLY:
{
    "voice_preference": null,
    "response_language": "en",
    "response": "your response text",
    "tool_call": null
}"""
    },
    "en_female": {
        "name": "Simmi",
        "system_prompt": """You are Simmi, a warm, friendly, and cheerful female AI assistant.
Your name is SIMMI. Speak in a warm, empathetic, and slightly playful tone.
Keep conversational responses SHORT (1-2 sentences).
For document/presentation content, generate DETAILED, PROFESSIONAL material.

Available tools: create_word_document, create_presentation, create_resume,
open_application, get_system_info, write_to_clipboard, create_file.

RESPOND WITH VALID JSON ONLY:
{
    "voice_preference": "en_female",
    "response_language": "en",
    "response": "your response text",
    "tool_call": null
}"""
    },
    "hi_male": {
        "name": "Jarvis",
        "system_prompt": """आप जार्विस हैं, एक पेशेवर और कुशल पुरुष AI सहायक हैं।
हिंदी में उत्तर दें जब तक अंग्रेजी न मांगी जाए।
संक्षिप्त और स्पष्ट रहें।

RESPOND WITH VALID JSON ONLY:
{
    "voice_preference": "hi_male",
    "response_language": "hi",
    "response": "your response text",
    "tool_call": null
}"""
    }
}

def detect_lang(text):
    for char in text:
        if 0x0900 <= ord(char) <= 0x097F:
            return "hi"
    return "en"

def detect_personality(user_input):
    user_lower = user_input.lower()
    if any(k in user_lower for k in ["simmi", "सिमी"]):
        return "en_female"
    elif any(k in user_lower for k in ["jarvis", "जार्विस"]):
        return "en_male"
    if detect_lang(user_input) == "hi":
        return "hi_male"
    return None

# ================================================================
# LLM CHAT (matches jarvis.py logic exactly)
# ================================================================
def chat_with_llm(user_input, conversation_history=None, personality="en_male"):
    if not USE_GROQ:
        return {"error": "Groq API is not configured. Set GROQ_API_KEY in .env"}
    try:
        personality_data = PERSONALITIES.get(personality, PERSONALITIES["en_male"])
        system_prompt = personality_data["system_prompt"]
        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for msg in conversation_history[-20:]:
                messages.append(msg)
        messages.append({"role": "user", "content": user_input})

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.6,
            max_tokens=4096,
        )
        content = response.choices[0].message.content or ""
        json_str = content.strip()
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
        json_str = json_str.strip()

        try:
            result = json.loads(json_str)
            return {
                "response": result.get("response", content),
                "voice_preference": result.get("voice_preference"),
                "response_language": result.get("response_language", "en"),
                "tool_call": result.get("tool_call"),
            }
        except json.JSONDecodeError:
            return {
                "response": content,
                "voice_preference": None,
                "response_language": detect_lang(content),
                "tool_call": None,
            }
    except Exception as e:
        return {"error": f"LLM Error: {str(e)}"}

# ================================================================
# API ROUTES
# ================================================================

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "online",
        "groq_connected": USE_GROQ,
        "piper_tts_available": PIPER_AVAILABLE,
        "voices_loaded": list(voice_engines.keys()) if PIPER_AVAILABLE else [],
        "personalities": list(PERSONALITIES.keys()),
        "timestamp": datetime.now().isoformat(),
    })

@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Message is required"}), 400

    user_input = data["message"]
    personality = data.get("personality", "en_male")
    conversation_history = data.get("history", [])

    # Auto-detect personality (exactly like jarvis.py)
    detected = detect_personality(user_input)
    if detected:
        personality = detected

    # Check for personality name in message
    user_lower = user_input.lower()
    if "simmi" in user_lower or "सिमी" in user_lower:
        personality = "en_female"
    elif "jarvis" in user_lower or "जार्विस" in user_lower:
        personality = "en_male"
    if detect_lang(user_input) == "hi":
        personality = "hi_male"

    result = chat_with_llm(user_input, conversation_history, personality)
    if "error" in result:
        return jsonify(result), 500

    return jsonify({
        "response": result["response"],
        "voice_preference": result.get("voice_preference"),
        "response_language": result.get("response_language", "en"),
        "personality": personality,
        "tool_call": result.get("tool_call"),
    })

@app.route("/api/execute-tool", methods=["POST"])
def execute_tool_endpoint():
    """Execute any backend tool (presentation, document, resume, etc.)."""
    data = request.get_json()
    if not data or "tool" not in data:
        return jsonify({"error": "Tool name is required"}), 400

    try:
        tools = import_backend_tools()
        func = tools.get(data["tool"])
        if not func:
            return jsonify({"error": f"Unknown tool: {data['tool']}"}), 400

        args = data.get("arguments", {})
        parsed_args = {}
        for key, value in args.items():
            if isinstance(value, str) and value.strip().startswith(("[", "{")):
                try:
                    parsed_args[key] = json.loads(value)
                except:
                    parsed_args[key] = value
            else:
                parsed_args[key] = value

        result = func(**parsed_args)
        return jsonify({
            "success": True,
            "result": str(result),
            "path": result if isinstance(result, str) else None
        })
    except Exception as e:
        return jsonify({"error": f"Tool execution failed: {str(e)}"}), 500

@app.route("/api/system-info", methods=["GET"])
def system_info_endpoint():
    info = {}
    if PSUTIL_AVAILABLE:
        try:
            info["cpu_usage"] = psutil.cpu_percent(interval=0.5)
            info["ram_usage"] = psutil.virtual_memory().percent
            info["ram_total"] = round(psutil.virtual_memory().total / (1024**3), 1)
            info["ram_used"] = round(psutil.virtual_memory().used / (1024**3), 1)
            info["disk_usage"] = psutil.disk_usage("/").percent
            info["cpu_temp"] = None
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            info["cpu_temp"] = entries[0].current
                            break
            except:
                pass
            info["battery"] = None
            try:
                battery = psutil.sensors_battery()
                if battery:
                    info["battery"] = battery.percent
            except:
                pass
            info["network_sent"] = round(psutil.net_io_counters().bytes_sent / (1024**2), 1)
            info["network_recv"] = round(psutil.net_io_counters().bytes_recv / (1024**2), 1)
        except:
            pass
    else:
        info["cpu_usage"] = 42
        info["ram_usage"] = 55
        info["disk_usage"] = 60
    return jsonify(info)

@app.route("/api/speak", methods=["POST"])
def speak_endpoint():
    """Server-side TTS via Piper (plays audio through computer speakers)."""
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Text is required"}), 400
    text = data["text"]
    voice = data.get("voice", "en_male")

    if not PIPER_AVAILABLE or voice not in voice_engines:
        return jsonify({
            "success": False,
            "message": "Piper TTS not available. Use browser TTS.",
            "use_browser_tts": True
        })

    def tts_thread(text, voice_key):
        try:
            print(f"[TTS] Speaking with {voice_key}: {text[:50]}...")
            
            # Import and use the EXACT same function from jarvis.py
            # This ensures we use the same proven-working audio code
            from jarvis import play_piper_tts
            play_piper_tts(text, voice_key)
            
            print(f"[TTS] Finished speaking")
                
        except Exception as e:
            print(f"[TTS Error]: {e}")
            import traceback
            traceback.print_exc()

    threading.Thread(target=tts_thread, args=(text, voice), daemon=True).start()
    return jsonify({"success": True, "message": "Speaking through speakers"})

@app.route("/api/listen", methods=["GET"])
def listen_endpoint():
    """Speech-to-text - capture microphone and transcribe."""
    try:
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 1000
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 2.0

        with sr.Microphone() as source:
            print("  🎤 [Listening...]")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=10)
            except sr.WaitTimeoutError:
                return jsonify({"transcript": None, "error": "No speech detected"})

        try:
            text = recognizer.recognize_google(audio, language="en-IN,hi-IN,en-US")
            return jsonify({"transcript": text, "language": detect_lang(text)})
        except sr.UnknownValueError:
            return jsonify({"transcript": None, "error": "Could not understand audio"})
        except sr.RequestError as e:
            return jsonify({"transcript": None, "error": f"STT error: {e}"})
    except Exception as e:
        return jsonify({"transcript": None, "error": str(e)})

@app.route("/api/generate-presentation", methods=["POST"])
def generate_presentation_endpoint():
    data = request.get_json()
    if not data or "topic" not in data:
        return jsonify({"error": "Topic is required"}), 400
    topic = data["topic"]

    prompt = f"""Generate content for a professional presentation about: {topic}
IMPORTANT: Exactly 10 slides (plus title slide = 11 total).
Each slide must have: title, content (4-6 detailed bullet points), image_query.

Return ONLY valid JSON array:
[{{"title":"Slide Title","content":"Bullet 1\\nBullet 2\\nBullet 3\\nBullet 4","image_query":"search term"}},...10 items...]

Rules:
- Each bullet = complete informative sentence (15+ words)
- image_query: 2-4 word Pexels search term
- Professional, detailed content only"""

    result = chat_with_llm(prompt, personality="en_male")
    if "error" in result:
        return jsonify(result), 500

    try:
        response_text = result["response"]
        start_idx = response_text.find("[")
        end_idx = response_text.rfind("]") + 1
        if start_idx >= 0 and end_idx > start_idx:
            slides_content = json.loads(response_text[start_idx:end_idx])
        else:
            slides_content = json.loads(response_text)

        from jarvis import create_presentation
        tool_result = create_presentation(
            title=topic,
            slides_content=json.dumps(slides_content),
            filename=data.get("filename"),
        )
        return jsonify({
            "success": True,
            "slides": slides_content,
            "result": str(tool_result),
            "path": tool_result if isinstance(tool_result, str) else None,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/create-document", methods=["POST"])
def create_document_endpoint():
    data = request.get_json()
    if not data or "title" not in data or "content" not in data:
        return jsonify({"error": "Title and content required"}), 400
    from jarvis import create_word_document
    result = create_word_document(data["title"], data["content"], data.get("filename"))
    return jsonify({"success": True, "path": result})

@app.route("/api/create-resume", methods=["POST"])
def create_resume_endpoint():
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name required"}), 400
    from jarvis import create_resume
    result = create_resume(
        data["name"],
        data.get("contact_info", ""),
        data.get("experience", []),
        data.get("education", []),
        data.get("skills", []),
        data.get("filename"),
    )
    return jsonify({"success": True, "path": result})

@app.route("/api/open-app", methods=["POST"])
def open_app_endpoint():
    data = request.get_json()
    if not data or "app_name" not in data:
        return jsonify({"error": "App name required"}), 400
    from jarvis import open_application
    result = open_application(data["app_name"])
    return jsonify({"success": True, "result": result})

@app.route("/api/clipboard", methods=["GET", "POST"])
def clipboard_endpoint():
    if request.method == "POST":
        data = request.get_json()
        if not data or "text" not in data:
            return jsonify({"error": "Text required"}), 400
        pyperclip.copy(data["text"])
        return jsonify({"success": True, "message": "Copied to clipboard"})
    else:
        try:
            text = pyperclip.paste()
            return jsonify({"success": True, "text": text})
        except:
            return jsonify({"success": False, "text": ""})

@app.route("/api/create-file", methods=["POST"])
def create_file_endpoint():
    data = request.get_json()
    if not data or "filename" not in data or "content" not in data:
        return jsonify({"error": "Filename and content required"}), 400
    filepath = os.path.join(OUTPUT_DIR, data["filename"])
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(data["content"])
    return jsonify({"success": True, "path": filepath})

@app.route("/api/list-files", methods=["GET"])
def list_files_endpoint():
    directory = request.args.get("directory")
    try:
        if directory:
            files = os.listdir(directory)
        else:
            files = os.listdir(os.path.expanduser("~\\Desktop"))
        return jsonify({"files": files[:30]})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/personalities", methods=["GET"])
def personalities_endpoint():
    return jsonify({
        person: {
            "name": info["name"],
            "voices": list(voice_engines.keys()) if PIPER_AVAILABLE else [],
        }
        for person, info in PERSONALITIES.items()
    })


# ================================================================
# ENTRY POINT
# ================================================================

def run_server(host="0.0.0.0", port=5000):
    print("=" * 54)
    print("  J.A.R.V.I.S. API Server v2.0")
    print("  All Backend Features Available")
    print("=" * 54)
    print(f"  Groq     : {'✓' if USE_GROQ else '⚠'}  {'Connected' if USE_GROQ else 'Not configured'}")
    print(f"  Piper TTS: {'✓' if PIPER_AVAILABLE else '⚠'}  {', '.join(voice_engines.keys()) if PIPER_AVAILABLE else 'Not available'}")
    print(f"  psutil   : {'✓' if PSUTIL_AVAILABLE else '⚠'}")
    print(f"  Server   : http://localhost:{port}")
    print("=" * 54)
    print("  Endpoints:")
    print("    GET /api/health")
    print("    POST /api/chat")
    print("    GET /api/system-info")
    print("    POST /api/speak")
    print("    GET /api/listen")
    print("    POST /api/execute-tool")
    print("    POST /api/generate-presentation")
    print("    POST /api/create-document")
    print("    POST /api/create-resume")
    print("    POST /api/open-app")
    print("    GET/POST /api/clipboard")
    print("    POST /api/create-file")
    print("    GET /api/list-files")
    print("    GET /api/personalities")
    print("=" * 54)
    app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    run_server()