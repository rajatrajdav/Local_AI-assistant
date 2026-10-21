    # =============================================================== UI LOOP
    def _poll_engine(self):
        if self._closing:
            return
        try:
            while True:
                self._handle_message(self.from_engine.get_nowait())
        except queue.Empty:
            pass
        if not self._closing:
            self.after(55, self._poll_engine)

    def _handle_message(self, msg):
        kind = msg.get("_kind")
        try:
            if kind == "engine_ready":
                self._on_engine_ready()
            elif kind == "user":
                self._add_message("user", msg.get("text", ""))
                self.process_lbl.configure(text="Heard: %s" %
                                           shorten(msg.get("text", ""), 70))
            elif kind == "ai":
                self._on_ai_message(msg)
            elif kind == "status":
                self.set_state(msg.get("state", "READY"))
            elif kind == "intent":
                self.process_lbl.configure(text=msg.get("text", ""))
            elif kind == "tool_start":
                self._on_tool_start(msg)
            elif kind == "tool_done":
                self.process_lbl.configure(text="Tool: %s \u2192 %s" % (
                    msg.get("name", "tool"),
                    shorten(msg.get("text", ""), 60)))
            elif kind == "voice_switch":
                self.current_voice = msg.get("voice", self.current_voice)
            elif kind == "speech_start":
                self._speaking = True
                self.set_state("SPEAKING")
            elif kind == "speech_end":
                self._on_speech_end()
            elif kind == "voice_result":
                self._on_voice_result(msg)
            elif kind == "sysinfo":
                self._on_sysinfo(msg.get("info") or {})
            elif kind == "error":
                self.process_lbl.configure(text="Error: %s" %
                                           shorten(msg.get("text", ""), 70))
                self.set_state("ERROR")
        except Exception as exc:
            try:
                self.process_lbl.configure(text="UI error: %s" % exc)
            except Exception:
                pass

    def _on_ai_message(self, msg):
        self._busy = False
        text = msg.get("text", "")
        self.msg_count += 1
        self._add_message("ai", text, tool=msg.get("tool"), voice=msg.get("voice"))
        self.process_lbl.configure(text="Spoke reply (%d ms)" % msg.get("ms", 0))
        if not self.tts_enabled:
            self.set_state("READY")

    def _on_tool_start(self, msg):
        name = msg.get("name", "tool")
        args = msg.get("args") or {}
        detail = ", ".join("%s=%s" % (k, shorten(v, 24))
                           for k, v in list(args.items())[:4]) \
            if isinstance(args, dict) else shorten(args, 50)
        self.set_state("BUSY", "Executing %s" % name.replace("_", " "))
        self.process_lbl.configure(text="Running %s(%s)" % (name, detail))

    def _on_speech_end(self):
        self._speaking = False
        self.set_state("READY")
        if self.handsfree and not self._busy and not self._capturing:
            self._schedule_handsfree(900)

    def _on_voice_result(self, msg):
        self._capturing = False
        self.mic_ind.configure(text="\u25cf MIC OFF", text_color=TEXT_MUTE)
        if msg.get("token") != self._capture_token:
            return
        text = (msg.get("text") or "").strip()
        if text:
            self.process_lbl.configure(text="Heard: %s" % shorten(text, 70))
            self.dispatch(text)
        else:
            self.set_state("READY", "No speech detected — try again")
            if self.handsfree:
                self._schedule_handsfree(1400)

    def _on_sysinfo(self, info):
        def as_pct(v):
            try:
                return float(str(v).replace("%", "").strip().split()[0])
            except Exception:
                return 0.0
        cpu, mem, disk = as_pct(info.get("cpu_usage")), as_pct(info.get("memory")), \
            as_pct(info.get("disk_usage"))
        self._cpu_hist.append(cpu)
        self._mem_hist.append(mem)
