# ==========================================================================
# WIDGET — central state core (targeting-reticle style, state + amplitude reactive)
# ==========================================================================
class HUDReactor(tk.Canvas):
    def __init__(self, master, size=220, **kwargs):
        super().__init__(master, width=size, height=size, bg=BG,
                         highlightthickness=0, bd=0, takefocus=0, **kwargs)
        self.size = size
        self.state = "BOOT"
        self.hue = CYAN
        self.amp = 0.0
        self.spin = 0.0
        self.spin_speed = 0.35
        self.levels = deque([0.0] * 90, maxlen=90)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self.size = max(120, min(event.width, event.height))

    def set_state(self, state):
        info = STATES.get(state, STATES["READY"])
        self.hue = info[0]
        self.spin_speed = info[2]
        self.state = state

    def tick(self, dt, amp):
        self.amp += (amp - self.amp) * 0.45
        self.spin = (self.spin + self.spin_speed * dt * 60.0) % 360.0
        self.levels.append(amp)
        self._redraw()

    def _redraw(self):
        try:
            self.delete("fx")
        except tk.TclError:
            return
        S = self.size
        if S < 80:
            return
        cx = cy = S / 2.0
        R = S * 0.46
        hue = self.hue
        spin = self.spin

        # outer degree ring with tick marks (targeting reticle)
        self.create_oval(cx - R, cy - R, cx + R, cy + R, outline=HAIRLINE_2,
                         width=1, tags="fx")
        for i in range(72):
            ang = math.radians(i * 5)
            major = (i % 9 == 0)
            r0 = R - (20 if major else 11)
            r1 = R
            bright = 0.55 if major else 0.22
            self.create_line(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang),
                             cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                             fill=mix(HAIRLINE_2, hue, bright), width=1, tags="fx")

        # rotating broken arcs (segmented bezel)
        r1 = R - 26
        for i in range(6):
            start = (spin * 0.6 + i * 60) % 360
            self.create_arc(cx - r1, cy - r1, cx + r1, cy + r1,
                            start=start, extent=34, style="arc",
                            outline=mix(HAIRLINE_2, hue, 0.85), width=2, tags="fx")

        # dense tick collar (inner)
        r2 = R - 46
        n_ticks = 64
        for i in range(n_ticks):
            ang = math.radians(i * (360.0 / n_ticks) + spin * 1.4)
            bright = 0.25 + 0.4 * (0.5 + 0.5 * math.cos(ang - math.radians(spin)))
            rr0, rr1 = r2 - 9, r2
            self.create_line(cx + rr0 * math.cos(ang), cy + rr0 * math.sin(ang),
                             cx + rr1 * math.cos(ang), cy + rr1 * math.sin(ang),
                             fill=mix(HAIRLINE, hue, bright), width=2, tags="fx")

        # counter-rotating segmented ring (bright)
        r3 = R - 66
        for i in range(3):
            start = (-spin * 1.3 + i * 120) % 360
            self.create_arc(cx - r3, cy - r3, cx + r3, cy + r3,
                            start=start, extent=70, style="arc",
                            outline=fade(hue, 0.85), width=3, tags="fx")

        # inner solid ring
        r4 = R - 92
        self.create_oval(cx - r4, cy - r4, cx + r4, cy + r4,
                         outline=mix(HAIRLINE_2, hue, 0.6), width=2, tags="fx")

        # speaking waveform ring (real TTS amplitude)
        if self.state == "SPEAKING":
            base_r = r4 - 16
            vals = list(self.levels)
            n = max(1, len(vals))
            for i in range(0, n, 2):
                ang = math.radians(i * (360.0 / n) - spin * 0.5)
                level = vals[i]
                length = 5 + level * 34
                self.create_line(cx + base_r * math.cos(ang), cy + base_r * math.sin(ang),
                                 cx + (base_r + length) * math.cos(ang),
                                 cy + (base_r + length) * math.sin(ang),
                                 fill=mix(CYAN_DIM, hue, min(1.0, 0.3 + level)),
                                 width=2, tags="fx")

        # scanning sweep (radar look)
        sweep_ang = math.radians(spin * 2.0)
        r5 = r4 - 14
        self.create_line(cx, cy, cx + r5 * math.cos(sweep_ang), cy + r5 * math.sin(sweep_ang),
                         fill=fade(hue, 0.5), width=1, tags="fx")

        # cross hairs
        for ang in (0, 90, 180, 270):
            a = math.radians(ang)
            self.create_line(cx + (r4 - 20) * math.cos(a), cy + (r4 - 20) * math.sin(a),
                             cx + (r4 + 6) * math.cos(a), cy + (r4 + 6) * math.sin(a),
                             fill=mix(HAIRLINE_2, hue, 0.7), width=1, tags="fx")

        # centre glow + core
        core_r = 30 + self.amp * 14
        for i, gr in enumerate((core_r + 26, core_r + 18, core_r + 10)):
            bright = 0.08 + 0.22 * (i / 3.0) + self.amp * 0.25
            self.create_oval(cx - gr, cy - gr, cx + gr, cy + gr,
                             outline=fade(hue, bright), width=1, tags="fx")
        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r,
                         fill=mix(BG, hue, 0.14), outline=mix(hue, GOLD, 0.35),
                         width=2, tags="fx")
        inner = core_r * 0.5
        self.create_oval(cx - inner, cy - inner, cx + inner, cy + inner,
                         outline=hue, width=1, tags="fx")
