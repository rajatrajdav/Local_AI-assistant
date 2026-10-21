# ==========================================================================
# THE APPLICATION
# ==========================================================================
class JarvisHUD(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("J.A.R.V.I.S")
        # Mini screen — compact and accurate for a demo / presentation look.
        self.geometry("720x520")
        self.minsize(620, 440)
        self.configure(fg_color=BG)

        # ---- session state ----
        self.conversation = []
        self.current_voice = "en_male"
        self.tts_enabled = True
        self.handsfree = True          # <-- auto-listen: no manual mic touch needed
        self.status = "BOOT"
        self.started = time.time()
        self.msg_count = 0
        self.tool_count = 0
        self.sys_info = {}
        self.process_step = ""         # prominent process line text

        self._busy = False
        self._speaking = False
        self._capturing = False
        self._closing = False
        self._engine_ready = False
        self._boot_t0 = time.time()
        self._last_frame = time.time()
        self._capture_token = 0
        self._handsfree_job = None
        self._loading_job = None
        self._bg_job = None
        self._boot_poll_job = None
        self._wrap_labels = []
        self._toast_widget = None

        self._tts_stop = threading.Event()
        self._amp_hist = deque([0.0] * 90, maxlen=90)
        self._cpu_hist = deque(maxlen=120)
        self._mem_hist = deque(maxlen=120)

        self.to_engine = queue.Queue()
        self.from_engine = queue.Queue()

        self._build_layout()
        threading.Thread(target=self._boot_engine, daemon=True).start()
        threading.Thread(target=self._engine_loop, daemon=True).start()
        threading.Thread(target=self._sysinfo_loop, daemon=True).start()

        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick_clock()
        self._poll_engine()
        self._animate()

        # Boot sequence: looping Loading.mp4 loading screen covers the window
        # while the heavy engine loads. On engine-ready we tear it down and
        # reveal the video-background mini interface.
        self._build_loading_screen()
        threading.Thread(target=self._decode_loading_video, daemon=True).start()
        self._boot_poll_job = self.after(250, self._boot_poll)
