    # ------------------------------------------------------------- layout
    def _build_layout(self):
        # Full-window backdrop canvas: the Loading.mp4 background is drawn
        # here and is NOT covered by any full-screen opaque frame.
        self.backdrop = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ---- central core (small reactor) ----
        self.core_holder = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.core_holder.place(relx=0.5, rely=0.42, anchor="center")
        self.core = HUDReactor(self.core_holder, size=220)
        self.core.pack()

        # brand
        self.brand = ctk.CTkLabel(self, text="J.A.R.V.I.S.",
                                  font=(DISPLAY, 20, "bold"), text_color=CYAN,
                                  fg_color=BG)
        self.brand.place(relx=0.5, rely=0.60, anchor="center")

        # ---- prominent process line (what Jarvis is doing right now) ----
        self.process_lbl = ctk.CTkLabel(
            self, text="Initialising …", font=(UI, 13, "bold"),
            text_color=TEXT, fg_color=BG)
        self.process_lbl.place(relx=0.5, rely=0.66, anchor="center")

        # state chip (small, under the process line)
        self.state_chip = ctk.CTkLabel(
            self, text="\u25cf BOOT", font=(MONO, 10, "bold"),
            text_color=CYAN, fg_color=PANEL, corner_radius=10, padx=10, pady=4)
        self.state_chip.place(relx=0.5, rely=0.715, anchor="center")

        # ---- mini transcript (bottom) ----
        self.tr_frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.tr_frame.place(relx=0.5, rely=0.855, anchor="center",
                            relwidth=0.94, relheight=0.22)
        self.tr_frame.grid_rowconfigure(0, weight=1)
        self.tr_frame.grid_columnconfigure(0, weight=1)

        self.tr_canvas = tk.Canvas(self.tr_frame, bg=PANEL, highlightthickness=0,
                                   bd=0, takefocus=0)
        self.tr_scroll = ctk.CTkScrollbar(self.tr_frame, command=self.tr_canvas.yview,
                                          width=10, corner_radius=6,
                                          fg_color=PANEL_2, button_color=HAIRLINE_2,
                                          button_hover_color=CYAN_DIM)
        self.tr_canvas.configure(yscrollcommand=self.tr_scroll.set)
        self.tr_canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 2), pady=6)
        self.tr_scroll.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 6))

        self.tr_inner = ctk.CTkFrame(self.tr_canvas, fg_color=PANEL, corner_radius=0)
        self.tr_window = self.tr_canvas.create_window((0, 0), window=self.tr_inner,
                                                      anchor="nw")
        self.tr_inner.bind("<Configure>",
                           lambda e: self.tr_canvas.configure(
                               scrollregion=self.tr_canvas.bbox("all")))
        self.tr_canvas.bind("<Configure>",
                            lambda e: self.tr_canvas.itemconfigure(
                                self.tr_window, width=e.width))
        self.tr_row = 0

        # ---- bottom mic / handsfree bar ----
        self.bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.bar.place(relx=0.5, rely=0.955, anchor="center",
                       relwidth=0.94, height=44)
        self.bar.grid_columnconfigure(0, weight=1)
        self.bar.grid_columnconfigure(1, weight=1)
        self.bar.grid_columnconfigure(2, weight=1)

        self.mic_ind = ctk.CTkLabel(
            self.bar, text="\u25cf MIC OFF", font=(MONO, 10, "bold"),
            text_color=TEXT_MUTE, fg_color=PANEL_2, corner_radius=8, padx=10, pady=6)
        self.mic_ind.grid(row=0, column=0, sticky="w", padx=10, pady=6)

        self.hf_btn = ctk.CTkButton(
            self.bar, text="", image=make_icon("broadcast", CYAN, 15, 1.8),
            width=34, height=30, corner_radius=10, fg_color=PANEL_2,
            hover_color=HAIRLINE_2, command=self.toggle_handsfree)
        self.hf_btn.grid(row=0, column=1)

        self.close_btn = ctk.CTkButton(
            self.bar, text="", image=make_icon("close", TEXT_DIM, 13, 1.8),
            width=34, height=30, corner_radius=10, fg_color=PANEL_2,
            hover_color=HAIRLINE_2, command=self._on_close)
        self.close_btn.grid(row=0, column=2, sticky="e", padx=10, pady=6)
