"""Temporary smoke test for jarvis_interface.py — safe to delete.

Boots the interface, walks every view, injects fake engine events, exercises
the real turn pipeline with stubbed engine functions, then shuts down.
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis_interface as ji          # noqa: E402

PROBLEMS = []


def guard(name, action):
    try:
        action()
        print("   ok   %s" % name)
    except Exception as exc:
        PROBLEMS.append((name, exc))
        print("   FAIL %s -> %s: %s" % (name, type(exc).__name__, exc))
        traceback.print_exc()


def main():
    app = ji.JarvisInterface()

    def step_views():
        for key in list(app.views):
            guard("view:%s" % key, lambda k=key: app.show_view(k))
        app.show_view("conversation")

    def step_events():
        post = app.from_engine.put
        guard("event user", lambda: post({"_kind": "user", "text": "hello jarvis"}))
        guard("event status", lambda: post({"_kind": "status", "state": "THINKING"}))
        guard("event intent", lambda: post({"_kind": "intent",
                                            "text": "hello -> conversational turn"}))
        guard("event tool start", lambda: post({"_kind": "tool_start",
                                                "name": "get_system_info",
                                                "args": {"detail": "cpu"}}))
        guard("event tool done", lambda: post({"_kind": "tool_done",
                                               "name": "get_system_info",
                                               "ok": True,
                                               "text": "Success: CPU 12%"}))
        guard("event ai", lambda: post({
            "_kind": "ai", "text": "All systems nominal, sir.",
            "tool": {"name": "get system info", "ok": True,
                     "detail": "CPU 12% \u00b7 RAM 44%"},
            "voice": "en_male", "ms": 812, "user": "hello jarvis"}))
        guard("event sysinfo", lambda: post({
            "_kind": "sysinfo", "info": {
                "cpu_usage": "23.5%", "memory": "61.2%",
                "memory_total": "16.0 GB", "disk_usage": "72.4%",
                "disk_free": "120.0 GB", "cpu_count": "16 cores",
                "battery": "No battery detected (desktop system)",
                "gpu": [{"name": "NVIDIA GeForce RTX 3050"}],
                "_ts": time.time()}}))
        guard("event voice switch", lambda: post({"_kind": "voice_switch",
                                                  "voice": "en_female",
                                                  "reason": "you addressed Simmi"}))
        guard("event notice", lambda: post({"_kind": "notice",
                                            "text": "smoke-test notice"}))
        guard("event speech", lambda: post({"_kind": "speech_start"}))
        guard("event speech end", lambda: post({"_kind": "speech_end"}))
        guard("event error", lambda: post({"_kind": "error",
                                           "text": "simulated failure"}))

    def step_pipeline():
        ji.process_user_input = lambda text, history, voice: {
            "response": "Understood, sir.",
            "voice_preference": None,
            "tool_call": {"name": "calculate", "arguments": {"expression": "2+2"}},
        }
        ji.execute_function = lambda name, args: "Success: 4"
        ji.detect_wake_word = lambda text: False
        ji.detect_target_personality = lambda text: None
        ji.detect_lang = lambda text: "en"
        app.tts_enabled = False
        guard("turn pipeline", lambda: app._run_chat("what is two plus two"))
        app.tts_enabled = True

    def step_actions():
        guard("mute on", app.toggle_mute)
        guard("mute off", app.toggle_mute)
        guard("stop speaking", app.stop_speaking)
        guard("toast", lambda: app._toast("smoke test"))
        guard("shortcuts", app._show_shortcuts)
        guard("empty send", app.send_input)
        guard("focus composer", app._focus_composer)
        guard("handsfree on", app.toggle_handsfree)
        guard("handsfree off", app.toggle_handsfree)
        guard("mic button", app.start_voice)
        guard("refresh deliverables", app.refresh_deliverables)
        guard("refresh diagnostics", app.refresh_diagnostics)

    def step_housekeeping():
        app.conversation = [{"role": "user", "content": "smoke"},
                            {"role": "assistant", "content": "ack"}]
        guard("export transcript", app.export_conversation)
        guard("clear conversation", app.clear_conversation)
        guard("clear activity", app.clear_activity_log)

    def step_report():
        print("   status          :", app.status)
        print("   rendered cards  :", app.chat_row)
        print("   activity lines  :", len(app._activity_rows))
        print("   engine ok       :", ji.ENGINE_OK, "|", ji.ENGINE_ERR[:70])
        print("   boot video      :", len(app._boot_frames), "frames")
        print("   reactor size    :", app.reactor.size)
        print("   views           :", len(app.views))
        print("   voice available :", ji.VOICE_INPUT)
        app._on_close()

    app.after(1200, step_views)
    app.after(2200, step_events)
    app.after(3400, step_pipeline)
    app.after(4600, step_actions)
    app.after(6000, step_housekeeping)
    app.after(7800, step_report)
    app.after(10000, lambda: None)
    try:
        app.mainloop()
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()
    print("\nPROBLEMS: %d" % len(PROBLEMS))
    for name, exc in PROBLEMS:
        print("  - %s: %s" % (name, exc))
