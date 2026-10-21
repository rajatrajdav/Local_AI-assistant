    def set_state(self, state, note=None):
        if state not in STATES:
            state = "READY"
        self.status = state
        colour, caption, _speed = STATES[state]
        try:
            self.state_chip.configure(text="\u25cf %s" % state, text_color=colour)
            self.process_lbl.configure(text=note or caption, text_color=TEXT)
            self.core.set_state(state)
        except Exception:
            pass
        try:
            if state == "LISTENING":
                self.mic_ind.configure(text="\u25cf LISTENING", text_color=GREEN)
            elif state == "SPEAKING":
                self.mic_ind.configure(text="\u25cf SPEAKING", text_color=CYAN)
            elif state == "THINKING" or state == "BUSY":
                self.mic_ind.configure(text="\u25cf PROCESSING", text_color=AMBER)
            else:
                self.mic_ind.configure(text="\u25cf MIC OFF", text_color=TEXT_MUTE)
        except Exception:
            pass
        if state == "THINKING":
            self._busy = True
        if state in ("READY", "ERROR", "OFFLINE"):
            self._busy = False

    def _sync_voice_ui(self, reason=None):
        label = PERSONA_LABEL.get(self.current_voice, "JARVIS")

    def _schedule_handsfree(self, delay=900):
        if self._handsfree_job:
            try:
                self.after_cancel(self._handsfree_job)
            except Exception:
                pass
        self._handsfree_job = self.after(delay, self._handsfree_tick)

    def _handsfree_tick(self):
        self._handsfree_job = None
        if self._closing or not self.handsfree:
            return
        if self._busy or self._speaking or self._capturing:
            return
        self.start_voice()

    def _tick_clock(self):
        if self._closing:
            return
        self.after(1000, self._tick_clock)

    # ------------------------------------------------------------- animation
    def _animate(self):
        if self._closing:
            return
        now = time.time()
        dt = min(0.12, max(0.001, now - self._last_frame))
        self._last_frame = now
        try:
            self.core.tick(dt, self._current_amp())
        except Exception:
            pass
        self.after(33, self._animate)

    def _current_amp(self):
        if self.status == "SPEAKING":
            recent = [v for v in list(self._amp_hist)[-8:] if v >= 0]
            base = max(recent) if recent else 0.14
            return min(1.0, 0.24 + base * 0.9)
        return 0.05 + 0.03 * (0.5 + 0.5 * math.sin(time.time() * 1.4))
