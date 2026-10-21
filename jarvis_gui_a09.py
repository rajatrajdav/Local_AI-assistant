    # ======================================================= ENGINE WORKERS
    def _boot_engine(self):
        _load_engine()
        self._engine_ready = True
        self.from_engine.put({"_kind": "engine_ready"})

    def _engine_loop(self):
        while not self._closing:
            try:
                job = self.to_engine.get(timeout=0.4)
            except queue.Empty:
                continue
            if job is None:
                break
            kind = job.get("_kind")
            try:
                if kind == "chat":
                    self._run_chat(job.get("text", ""))
                elif kind == "voice_capture":
                    self._run_capture(job.get("token"))
                elif kind == "shutdown":
                    break
            except Exception as exc:
                self.from_engine.put({"_kind": "error", "text": str(exc)})

    def _sysinfo_loop(self):
        while not self._closing:
            info = {}
            try:
                if ENGINE_OK and get_system_info:
                    info = get_system_info() or {}
            except Exception:
                info = {}
            info["_ts"] = time.time()
            self.sys_info = info
            self.from_engine.put({"_kind": "sysinfo", "info": info})
            time.sleep(2.0)

    def _run_capture(self, token):
        text = ""
        if VOICE_INPUT and listen_natural_fn:
            try:
                text = (listen_natural_fn() or "").strip()
            except Exception:
                text = ""
        self.from_engine.put({"_kind": "voice_result", "text": text, "token": token})
