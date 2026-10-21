    def _run_chat(self, user_text):
        user_text = (user_text or "").strip()
        if not user_text:
            self.from_engine.put({"_kind": "status", "state": "READY"})
            return
        self.from_engine.put({"_kind": "user", "text": user_text})
        self.from_engine.put({"_kind": "status", "state": "THINKING"})

        if not ENGINE_OK or process_user_input is None:
            self.from_engine.put({"_kind": "error",
                                  "text": "The jarvis engine is unavailable. %s" % ENGINE_ERR})
            self.from_engine.put({"_kind": "status", "state": "READY"})
            return

        clean = user_text
        try:
            if detect_wake_word and detect_wake_word(clean):
                stripped = (strip_wake_word(clean) if strip_wake_word else "") or ""
                if not stripped.strip():
                    self.conversation.append({"role": "user", "content": clean})
                    self.conversation.append({"role": "assistant",
                                              "content": "Yes sir? How can I help you?"})
                    self._deliver("Yes sir? How can I help you?", None)
                    return
                clean = stripped.strip()
        except Exception:
            pass

        if clean.lower() in EXIT_WORDS:
            farewell = "Goodbye. Have a wonderful day."
            self.conversation.append({"role": "user", "content": clean})
            self.conversation.append({"role": "assistant", "content": farewell})
            self._deliver(farewell, None)
            return

        personality, language, reason = None, "en", None
        try:
            personality = detect_target_personality(clean) if detect_target_personality else None
            language = detect_lang(clean) if detect_lang else "en"
        except Exception:
            personality, language = None, "en"

        new_voice = None
        if personality == "jarvis":
            new_voice = "hi_male" if language == "hi" else "en_male"
            reason = "you addressed Jarvis"
        elif personality == "simmi":
            new_voice = "en_female"
            reason = "you addressed Simmi"
        elif language == "hi" and self.current_voice != "hi_male":
            new_voice = "hi_male"
            reason = "Hindi input detected"
        if new_voice and new_voice in VOICES and new_voice != self.current_voice:
            self.current_voice = new_voice
            self.from_engine.put({"_kind": "voice_switch", "voice": new_voice,
                                  "reason": reason})
        self.from_engine.put({"_kind": "intent", "text": "%s \u2192 %s" % (
            shorten(clean, 70), reason or "conversational turn")})

        t0 = time.time()
        try:
            result = process_user_input(clean, self.conversation, self.current_voice) or {}
        except Exception as exc:
            result = {}
            self.from_engine.put({"_kind": "error", "text": "Model call failed: %s" % exc})
        elapsed = int((time.time() - t0) * 1000)

        out = (result.get("response") or "").strip() or "I am on it."
        voice_out = self.current_voice
        preference = result.get("voice_preference")
        if preference and preference in VOICES and preference != self.current_voice:
            self.current_voice = preference
            voice_out = preference
            self.from_engine.put({"_kind": "voice_switch", "voice": preference,
                                  "reason": result.get("reason") or "model preference"})

        tool_info = None
        tool_call = result.get("tool_call")
        if tool_call:
            name = tool_call.get("name") or "unknown_tool"
            args = tool_call.get("arguments") or {}
            self.from_engine.put({"_kind": "tool_start", "name": name, "args": args})
            try:
                tool_result = execute_function(name, args)
                ok = str(tool_result).startswith("Success")
            except Exception as exc:
                tool_result, ok = "Error: %s" % exc, False
            tool_info = {"name": name.replace("_", " "), "ok": ok,
                         "detail": shorten(tool_result, 160)}
            self.from_engine.put({"_kind": "tool_done", "name": name, "ok": ok,
                                  "text": str(tool_result)})
            if "Permission denied" not in str(tool_result):
                if ok:
                    out = "%s Done! %s" % (out, str(tool_result).replace("Success: ", ""))
                else:
                    out = "%s %s" % (out, tool_result)

        self.conversation.append({"role": "user", "content": clean})
        self.conversation.append({"role": "assistant", "content": out})
        if len(self.conversation) > 60:
            self.conversation = self.conversation[-60:]

        self.from_engine.put({"_kind": "ai", "text": out, "tool": tool_info,
                              "voice": voice_out, "ms": elapsed, "user": clean})
        if self.tts_enabled:
            self._speak(out, voice_out)
        else:
            self.from_engine.put({"_kind": "status", "state": "READY"})

    def _deliver(self, text, tool):
        self.from_engine.put({"_kind": "ai", "text": text, "tool": tool,
                              "voice": self.current_voice, "ms": 0, "user": ""})
        if self.tts_enabled:
            self._speak(text, self.current_voice)
        else:
            self.from_engine.put({"_kind": "status", "state": "READY"})
