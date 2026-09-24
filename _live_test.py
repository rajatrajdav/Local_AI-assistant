import time, traceback, threading
import jarvis_gui as J

print("loading engine...", flush=True)
J._load_engine()
print("engine_ok:", J.ENGINE_OK, flush=True)

print("calling process_user_input...", flush=True)
try:
    res = J.process_user_input("hello jarvis, quick test", [], "en_male")
    print("keys:", list(res.keys()), flush=True)
    print("response:", str(res.get("response", ""))[:200], flush=True)
    print("voice_pref:", res.get("voice_preference"), flush=True)
    print("tool_call:", res.get("tool_call"), flush=True)
except Exception:
    traceback.print_exc()
    print("PROCESS-FAIL", flush=True)

print("testing TTS (speak_handler) for 5s...", flush=True)
try:
    threading.Thread(target=lambda: J._speak_async(
        "System online. Welcome back sir.", "en_male"), daemon=True).start()
    time.sleep(5)
    print("TTS-DONE", flush=True)
except Exception:
    traceback.print_exc()
    print("TTS-FAIL", flush=True)

print("ALL-TESTED", flush=True)