    # ---------------------------------------------------------------- boot video
    def _build_loading_screen(self):
        """Mini loading screen: Loading.mp4 viewport + title while engine loads."""
        self.loading = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.loading.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.loading.lift()

        self.loading_vid = tk.Label(self.loading, bg=BG, bd=0,
                                    highlightthickness=0)
        self.loading_vid.place(relx=0.5, rely=0.42, anchor="center")

        self.loading_title = ctk.CTkLabel(
            self.loading, text="J.A.R.V.I.S.", font=(DISPLAY, 19, "bold"),
            text_color=CYAN, fg_color=BG)
        self.loading_title.place(relx=0.5, rely=0.60, anchor="center")

        self.loading_sub = ctk.CTkLabel(
            self.loading, text="Initialising systems …",
            font=(UI, 12), text_color=TEXT_DIM, fg_color=BG)
        self.loading_sub.place(relx=0.5, rely=0.66, anchor="center")

        self.loading_detail = ctk.CTkLabel(
            self.loading, text="Loading interface assets",
            font=(MONO, 9), text_color=TEXT_MUTE, fg_color=BG)
        self.loading_detail.place(relx=0.5, rely=0.70, anchor="center")

    def _boot_poll(self):
        if self._closing:
            return
        if self._engine_ready and getattr(self, "loading", None) is not None:
            self._finish_boot()
            return
        if not self._closing:
            self._boot_poll_job = self.after(250, self._boot_poll)

    def _decode_loading_video(self):
        """Decode Loading.mp4 frames on a background thread so boot stays fluid."""
        path = _find_video()
        frames = _extract_frames(path, target_w=640, max_frames=140) if path else []
        self._loading_frames = frames
        self.after(0, self._start_loading_animation)

    def _start_loading_animation(self):
        if self._closing or not getattr(self, "loading", None):
            return
        self._animate_loading()

    def _animate_loading(self, idx=0):
        if self._closing or not getattr(self, "loading", None):
            return
        frames = getattr(self, "_loading_frames", []) or []
        try:
            if frames:
                self.loading_vid.configure(image=frames[idx])
                self.loading_vid.image = frames[idx]
        except Exception:
            pass
        self._loading_job = self.after(VIDEO_FRAME_TIME,
                                       lambda: self._animate_loading(
                                           (idx + 1) % len(frames) if frames else idx))

    def _finish_boot(self):
        """Tear down the loading screen, start the video background, show HUD."""
        if self._closing:
            return
        try:
            if self._loading_job:
                self.after_cancel(self._loading_job)
            self._loading_job = None
            if getattr(self, "loading", None) is not None:
                self.loading.destroy()
                self.loading = None
        except Exception:
            pass
        self._start_background_video()
        self.after(80, self._show_transcript_intro)

    def _show_transcript_intro(self):
        self._add_message("notice", "System online. Say something — Jarvis is listening.")

    def _start_background_video(self):
        """Loop Loading.mp4 on the full-window backdrop behind the HUD."""
        path = _find_video()
        self.backdrop.configure(bg=BG)
        if not path:
            return
        self._bg_idx = 0
        size = (max(self.winfo_width(), 720), max(self.winfo_height(), 520))
        threading.Thread(target=self._decode_background_video,
                         args=(path, size), daemon=True).start()

    def _decode_background_video(self, path, size):
        frames = _extract_frames(path, target_w=max(size), max_frames=240)
        self._bg_frames = frames
        self.after(0, self._animate_background)

    def _animate_background(self):
        if self._closing or not getattr(self, "_bg_frames", None):
            return
        frames = self._bg_frames
        frame = frames[self._bg_idx]
        try:
            self.backdrop.delete("bg_frame")
            cx = max(self.winfo_width() // 2, 1)
            cy = max(self.winfo_height() // 2, 1)
            self.backdrop.create_image(cx, cy, image=frame, anchor="center",
                                       tags="bg_frame")
            self.backdrop.tag_lower("bg_frame")
        except Exception:
            pass
        self._bg_idx = (self._bg_idx + 1) % len(frames)
        self._bg_job = self.after(VIDEO_FRAME_TIME, self._animate_background)
