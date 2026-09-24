"""Temporary engine-bridge test — safe to delete.

Loads the real jarvis.py engine through the interface bridge, then boots the
GUI with the engine already warm and inspects the boot greeting + diagnostics.
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis_interface as ji          # noqa: E402


def main():
    started = time.time()
    ok = ji._load_engine()
    print("ENGINE_OK          :", ok, "(%.1f s)" % (time.time() - started))
    print("ENGINE_ERR         :", ji.ENGINE_ERR[:180])
    print("FUNCTION_MAP       :", len(ji.FUNCTION_MAP), "tools")
    print("VOICES             :", list(ji.VOICES.keys()))
    print("voice engines      :", list((ji.engine_get("voice_engines", {}) or {}).keys()))
    print("USE_GROQ           :", ji.engine_get("USE_GROQ"),
          "|", ji.engine_get("GROQ_MODEL_NAME"))
    print("USE_CEREBRAS       :", ji.engine_get("USE_CEREBRAS"),
          "|", ji.engine_get("CEREBRAS_MODEL_NAME"))
    print("USE_GEMINI         :", ji.engine_get("USE_GEMINI"),
          "|", ji.engine_get("GEMINI_MODEL_NAME"))
    print("VOICE_INPUT        :", ji.VOICE_INPUT, "|", ji.SR_ERROR[:70])
    print("get_system_info    :", bool(ji.get_system_info))
    print("process_user_input :", bool(ji.process_user_input))

    app = ji.JarvisInterface()
    app.tts_enabled = False

    def report():
        try:
            app.refresh_diagnostics()
            print("\n--- GUI WITH WARM ENGINE ---")
            print("status        :", app.status)
            print("greeting      :", app.last_ai_text[:70])
            print("cards         :", app.chat_row)
            print("activity rows :", len(app._activity_rows))
            print("sysinfo keys  :", sorted(k for k in (app.sys_info or {})
                                           if not k.startswith("_")))
            for key in ("cpu", "mem", "disk", "gpu", "cores", "battery",
                        "uptime", "provider_groq", "provider_cerebras",
                        "provider_gemini", "tools", "voice_en_male",
                        "voice_input", "engine", "engine_load", "counts"):
                entry = app.diag_labels.get(key)
                print("  %-16s %s" % (key, entry[0].cget("text") if entry else "?"))
        except Exception:
            traceback.print_exc()
        finally:
            app._on_close()

    app.after(14000, report)
    app.mainloop()


if __name__ == "__main__":
    main()
