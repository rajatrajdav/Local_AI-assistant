    def _speak(self, text, voice):
        self._tts_stop.clear()
        threading.Thread(target=self._tts_worker, args=(text, voice),
                         daemon=True).start()

    def _piper_play(self, text, voice, stop_event):
        engines = engine_get("voice_engines") or {}
        piper_voice = engines.get(voice)
        np_mod = engine_get("np")
        sd_mod = engine_get("sd")
        if piper_voice is None or np_mod is None or sd_mod is None:
            return False
        language = (VOICES.get(voice) or {}).get("language", "en")
        normaliser = engine_get("normalize_hindi_text" if language == "hi"
                                else "normalize_english_text")
        if callable(normaliser):
            try:
                text = normaliser(text)
            except Exception:
                pass
        if not text.strip():
            return True
        rate = getattr(getattr(piper_voice, "config", None), "sample_rate", 22050)
        with sd_mod.OutputStream(samplerate=rate, channels=1, dtype="int16") as stream:
            for chunk in piper_voice.synthesize(text):
                if stop_event.is_set():
                    break
                data = np_mod.frombuffer(chunk.audio_int16_bytes, dtype=np_mod.int16)
                if data.size:
                    level = float(np_mod.abs(data).mean()) / 6000.0
                    self._amp_hist.append(max(0.0, min(1.0, level)))
                    stream.write(data)
        return True

    def _tts_worker(self, text, voice):
        stop_event = self._tts_stop
        self.from_engine.put({"_kind": "speech_start"})
        handled = False
        try:
            handled = self._piper_play(text, voice, stop_event)
        except Exception:
            handled = False
        if not handled:
            speak_blocking(text, voice, stop_event=stop_event)
        self._amp_hist.append(-1.0)
        self.from_engine.put({"_kind": "speech_end"})
