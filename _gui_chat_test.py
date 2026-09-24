import time, traceback
import jarvis_gui as J

J._load_engine()
print("building GUI...", flush=True)
app = J.JarvisGUI()
app.tts_enabled = False   # no audio during this test

orig = app._handle_msg
def hooked(m):
    k = m.get("_kind")
    t = m.get("text", "")
    print("MSG:", k, "|", (t[:50].replace("\n"," ") if t else m.get("voice", m.get("status",""))), flush=True)
    return orig(m)
app._handle_msg = hooked

print("sending message...", flush=True)
app._send_text("give me a one sentence system status summary")

deadline = time.time() + 25
while time.time() < deadline:
    try:
        app.update()
    except Exception as e:
        print("UPDERR", repr(e), flush=True)
        traceback.print_exc()
        break
    time.sleep(0.03)

content = app.chat_log.get("1.0", "end")
print("LOG_HAS_AI:", "JARVIS" in content, flush=True)
print("TAIL:", repr(content[-300:]), flush=True)
try:
    app.destroy()
except Exception:
    pass
print("DONE", flush=True)