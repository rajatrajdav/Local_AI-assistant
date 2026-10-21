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
