"""
2PAC GUI main window. Split (P1-12): shared names in gui_common.py, method groups in gui_status,
gui_utils_tab, gui_hardware, gui_ipc, gui_plot_interaction (mixins of MyApp).
"""
from gui_common import *  # noqa: F401,F403
from gui_common import _states_mod  # noqa: F401
from gui_status import StatusAlertsMixin
from gui_utils_tab import UtilsTabMixin
from gui_hardware import HardwareControlsMixin
from gui_ipc import IpcCommandsMixin
from gui_plot_interaction import PlotInteractionMixin




class DataFetchThread(QThread):
    state_update = pyqtSignal(str, str)
    procedure_finished = pyqtSignal(str)
    procedure_error = pyqtSignal(str, str)
    operator_action = pyqtSignal(str, str)

    def __init__(self, world, first_state, states_dict):
        super().__init__()
        self.world = world
        if self.world is not None:
            self.world._data_thread = self
        self.next_state = first_state
        self.states_dict = states_dict
        self.state = None
        self.running = True
        self.paused = False

    def set_combo_value(self, value):
        if isinstance(value, str):
            if value in self.states_dict:
                self.next_state = self.states_dict[value]
                self.paused = False
        else:
            self.next_state = value
            self.paused = False

    def run(self):
        while self.running:
            if self.next_state is not None:
                self.state = self.next_state
                self.next_state = None

            if self.state is None:
                time.sleep(0.5)
                continue

            state_name = self.state.name()
            # If entering ready_for_cooldown, emit operator action for the He-3 valve
            if state_name == "ready_for_cooldown":
                self.operator_action.emit(state_name, "⚠️ ACTION REQUIRED: Open the green He-3 valve on the cryostat.")

            try:
                runner = self.world.state_runner(self.state)
                self.world._update(self.state)
                tstart = self.world.last_update_time_s
                for (state, line_number) in runner:
                    if not self.running:
                        return
                    if self.next_state is not None:
                        break

                    pause_start = time.time()
                    while self.paused and self.next_state is None and self.running:
                        time.sleep(max(0.1, self.world.target_tick_rate_s))
                        self.world._update(state)
                        elapsed = self.world.last_update_time_s - tstart
                        s1 = f"state={state.name()} [PAUSED] {line_number=} {elapsed=:.2f}"
                        self.state_update.emit(s1, state.code_highlighted(line_number))

                    if hasattr(self.world, "command") and self.world.command is not None:
                        from engine import WaitUntil
                        if isinstance(self.world.command, WaitUntil):
                            self.world.command.time_s += (time.time() - pause_start)

                    if self.next_state is not None:
                        break

                    self.state = state
                    elapsed = self.world.last_update_time_s - tstart
                    s1 = f"state={state.name()} {line_number=} {elapsed=:.2f} state_elapsed_s={self.world.state_elapsed_s():.2f}"
                    s2 = state.code_highlighted(line_number)
                    self.state_update.emit(s1, s2)

                    # Check for valve instruction in active state
                    code_line = state.code_line(line_number)
                    if "CLOSE THE GREEN HE3 VALVE" in code_line:
                        self.operator_action.emit(state.name(), "⚠️ ACTION REQUIRED: Ensure the green He-3 valve on the cryostat is CLOSED.")
                    elif "OPEN THE GREEN HE3 VALVE" in code_line:
                        self.operator_action.emit(state.name(), "⚠️ ACTION REQUIRED: Open the green He-3 valve on the cryostat.")

                # If runner exited naturally without next_state being set
                if self.next_state is None and self.running:
                    finished_name = self.state.name()
                    self.procedure_finished.emit(finished_name)
                    # Automatically transition to IDLE_STATE (wait_forever)
                    idle_st = self.states_dict.get(IDLE_STATE)
                    if idle_st is not None:
                        self.state = idle_st
                    else:
                        time.sleep(1)

            except Exception as e:
                err_msg = str(e)
                failed_name = self.state.name() if self.state else "procedure"
                print(f"Error in state runner for '{failed_name}': {e}")
                self.procedure_error.emit(failed_name, err_msg)
                # Safely fall back to IDLE_STATE
                idle_st = self.states_dict.get(IDLE_STATE)
                self.state = idle_st
                time.sleep(1)


class MyApp(StatusAlertsMixin, UtilsTabMixin, HardwareControlsMixin, IpcCommandsMixin, PlotInteractionMixin, QWidget):
    sig_pid_status = pyqtSignal(str)
    sig_pid_read = pyqtSignal(dict)

    @property
    def live_dataset(self):
        if hasattr(self, "daily_logger") and self.daily_logger and getattr(self.daily_logger, "dataset", None) is not None:
            return self.daily_logger.dataset
        return getattr(self, "_initial_dataset", None)

    @live_dataset.setter
    def live_dataset(self, val):
        self._initial_dataset = val

    def __init__(self, world, dataset, states_dict, daily_logger=None):
        super().__init__()

        self.sig_pid_status.connect(self._handle_pid_status)
        self.sig_pid_read.connect(self._handle_pid_read)

        load_aliases()

        self.gui_settings = load_gui_settings()
        self.expert_mode = bool(self.gui_settings.get("expert_mode", False))

        self.world = world
        self.daily_logger = daily_logger
        self.world.target_tick_rate_s = float(self.gui_settings.get("log_interval_s", 1.0))
        import states as states_module
        states_module.ENABLE_TEXT_LOGGING = bool(self.gui_settings.get("text_logs", True))

        self.live_dataset = dataset
        self.historical_dataset = None
        self.displaying_historical = False
        self.states_dict = states_dict
        self.theme = self.gui_settings.get("theme", "light")
        self.current_badge_state = "idle"
        self.active_plot_tab = "Overview"
        self.temp_scale = "log"
        saved_range = self.gui_settings.get("default_range", "6 Hours")
        s_low = str(saved_range).lower()
        if "month" in s_low or "30" in s_low:
            self.time_window = "1 Month"
        elif "week" in s_low or "7" in s_low:
            self.time_window = "1 Week"
        elif "day" in s_low or "24" in s_low:
            self.time_window = "1 Day"
        elif "1" in s_low and "hour" in s_low:
            self.time_window = "1 Hour"
        elif "6" in s_low and "hour" in s_low:
            self.time_window = "6 Hours"
        else:
            self.time_window = "6 Hours"
        self.user_has_zoomed = False
        self.previewing_state = None
        self.axes_list = []
        self.on_mouse_move_event = None
        self.db_file_path = None
        self.hidden_channels = set()
        self._latest_magnet_current = 0.0

        # Mechanical heat switch state tracking (Pot, ADR, Charcoal)
        # Default condensation configuration: Charcoal OPEN, Pot CLOSED, ADR CLOSED
        self._hs_states = {"pot": "CLOSED", "adr": "CLOSED", "charcoal": "OPEN"}
        self._hs_pulsing = set()
        last_hw_init = None
        try:
            from daily_logger import get_last_hardware_state
            last_hw_init = get_last_hardware_state()
            if last_hw_init and "heatswitches" in last_hw_init:
                self._hs_states.update(last_hw_init["heatswitches"])
        except Exception:
            pass

        # Sync QCoDeS parameter caches without pulsing hardware relays
        if hasattr(self.world, "station") and hasattr(self.world.station, "labjack"):
            for _k in ("pot", "adr", "charcoal"):
                _p = getattr(self.world.station.labjack, f"heatswitch_{_k}", None)
                if _p and hasattr(_p, "cache"):
                    _p.cache.set(self._hs_states.get(_k, "CLOSED" if _k != "charcoal" else "OPEN"))
            _rel_p = getattr(self.world.station.labjack, "relay", None)
            if _rel_p and hasattr(_rel_p, "cache"):
                # Restore the last commanded relay position without pulsing. Older state files always
                # saved "CONTROL" on close (bug, fixed 2026-11-18); anything else restores as UNKNOWN.
                _saved_rel = "UNKNOWN"
                if last_hw_init and "relay" in last_hw_init and last_hw_init["relay"] in ("CONTROL", "RAMP"):
                    _saved_rel = last_hw_init["relay"]
                _rel_p.cache.set(_saved_rel)

        # Left-click drag & pan state
        self._drag_active = False
        self._drag_start_x = None
        self._drag_start_y = None
        self._drag_start_ax = None
        self._drag_init_xlim = None
        self._drag_init_ylim = None
        self._drag_has_moved = False

        screen_geometry = QApplication.desktop().screenGeometry()
        saved_w = self.gui_settings.get("window_width")
        saved_h = self.gui_settings.get("window_height")
        if saved_w and saved_h:
            win_w = max(950, min(int(saved_w), screen_geometry.width()))
            win_h = max(600, min(int(saved_h), screen_geometry.height()))
        else:
            win_w = min(1440, screen_geometry.width())
            win_h = min(900, int(0.85 * screen_geometry.height()))

        self.resize(win_w, win_h)
        self.setMinimumSize(950, 600)
        self.setWindowTitle("2pac gui — Idle")
        icon_path = Path(__file__).parent / "adr_gui_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ================= Overall Layout =================
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(3)

        # Operator Action / Alert Banner
        self.operator_banner = QFrame()
        self.operator_banner.setObjectName("operator_banner")
        banner_layout = QHBoxLayout(self.operator_banner)
        banner_layout.setContentsMargins(10, 6, 10, 6)
        banner_layout.setSpacing(8)
        self.lbl_operator_action = QLabel("")
        self.lbl_operator_action.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_operator_action.setWordWrap(True)
        self.btn_confirm_action = QPushButton("✔ Confirm Step Done")
        self.btn_confirm_action.setObjectName("btn_confirm_action")
        self.btn_confirm_action.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; border-radius: 4px; padding: 4px 12px;")
        self.btn_confirm_action.clicked.connect(self.confirm_operator_action)
        self.btn_dismiss_banner = QPushButton("Dismiss")
        self.btn_dismiss_banner.setFixedWidth(75)
        self.btn_dismiss_banner.clicked.connect(self.dismiss_operator_banner)
        banner_layout.addWidget(self.lbl_operator_action, stretch=1)
        banner_layout.addWidget(self.btn_confirm_action)
        banner_layout.addWidget(self.btn_dismiss_banner)
        self.operator_banner.setVisible(False)
        outer_layout.addWidget(self.operator_banner)

        # ================= Top Metric Readout Cards (5 Key Metrics) =================
        self.metric_cards_bar = QFrame()
        self.metric_cards_bar.setObjectName("metric_cards_bar")
        self.metric_cards_bar.setFixedHeight(66)
        metric_bar_layout = QHBoxLayout(self.metric_cards_bar)
        metric_bar_layout.setContentsMargins(2, 2, 2, 2)
        metric_bar_layout.setSpacing(6)

        self.metric_tiles = {}
        # Colors matched exactly to corresponding plot curves:
        # 4K Flange (Amber / Bronze #d97706), Charcoal (Forest Green #059669),
        # He-3 Pot (Purple #7c3aed), FAA Stage (Crimson Red #dc2626),
        # He-3 Pressure (Royal Blue #2563eb), Magnet Current (Deep Cyan #0891b2),
        # Relay / Setpoint (Slate Grey #475569)
        metric_specs = [
            ("cryocon_chC_temperature", "4K FLANGE", "#d97706"),
            ("cryocon_chB_temperature", "CHARCOAL", "#059669"),
            ("cryocon_chD_temperature", "HE-3 POT", "#7c3aed"),
            ("faa_temperature", "FAA STAGE", "#dc2626"),
            ("labjack_he3_pressure", "HE-3 PRESSURE", "#2563eb"),
            ("labjack_kepco_current", "MAGNET CURRENT", "#0891b2"),
            ("relay_heater_status", "RELAY STATE: —", "#475569"),
        ]

        for key, title, accent_color in metric_specs:
            tile_card = QFrame()
            tile_card.setObjectName("metric_tile")
            tl = QVBoxLayout(tile_card)
            tl.setContentsMargins(10, 5, 10, 5)
            tl.setSpacing(1)

            lbl_t = QLabel(title)
            lbl_t.setObjectName("metric_tile_title")
            lbl_t.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_t.setStyleSheet("color: rgba(255, 255, 255, 0.92); font-weight: 700; font-size: 11px; background: transparent;")

            lbl_v = QLabel("—")
            lbl_v.setObjectName("metric_tile_value")
            if key == "relay_heater_status":
                lbl_t.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                lbl_v.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                lbl_v.setFont(QFont("Segoe UI", 10, QFont.Bold))
                lbl_v.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 12px; background: transparent;")
                tile_card.setCursor(Qt.PointingHandCursor)
                tile_card.mousePressEvent = self._on_relay_tile_clicked
            else:
                lbl_v.setFont(QFont("Consolas", 16, QFont.Bold))
                lbl_v.setStyleSheet("color: #ffffff; font-weight: 800; font-size: 18px; background: transparent;")

            tl.addWidget(lbl_t)
            tl.addWidget(lbl_v)
            tile_card.setStyleSheet(
                f"QFrame#metric_tile {{ background-color: {accent_color}; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.18); }}"
            )
            metric_bar_layout.addWidget(tile_card)
            self.metric_tiles[key] = {
                "card": tile_card,
                "lbl_t": lbl_t,
                "val": lbl_v,
                "accent": accent_color,
                "title": title
            }

        outer_layout.addWidget(self.metric_cards_bar)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(4)

        # ================= Control Sidebar (Scrollable 265px) =================
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("sidebar_frame")
        sidebar_frame.setFixedWidth(265)
        sidebar_outer_layout = QVBoxLayout(sidebar_frame)
        sidebar_outer_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_outer_layout.setSpacing(0)

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("sidebar_scroll")
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QFrame.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        sidebar_content = QWidget()
        sidebar_content.setObjectName("sidebar_content")
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setAlignment(Qt.AlignTop)
        sidebar_layout.setContentsMargins(8, 6, 8, 6)
        sidebar_layout.setSpacing(5)

        self.lbl_status_badge = QLabel("IDLE")
        self.lbl_status_badge.setAlignment(Qt.AlignCenter)
        self.lbl_status_badge.setFixedHeight(24)
        sidebar_layout.addWidget(self.lbl_status_badge)

        lbl_proc = QLabel("Procedure:")
        lbl_proc.setObjectName("muted_label")
        sidebar_layout.addWidget(lbl_proc)

        self.combo_box = QComboBox(self)
        self._populate_state_combo()
        self.combo_box.currentIndexChanged.connect(self.on_combo_changed)
        sidebar_layout.addWidget(self.combo_box)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("btn_start")
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("btn_pause")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btn_stop")

        self.btn_start.clicked.connect(self.request_state_change)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop_state)

        btn_ctrl_row = QHBoxLayout()
        btn_ctrl_row.setSpacing(3)
        btn_ctrl_row.addWidget(self.btn_start)
        btn_ctrl_row.addWidget(self.btn_pause)
        btn_ctrl_row.addWidget(self.btn_stop)
        sidebar_layout.addLayout(btn_ctrl_row)

        # --- Procedure Phase / Sub-Step Tracker ---
        self.phase_box = QFrame()
        self.phase_box.setObjectName("phase_box")
        phase_layout = QVBoxLayout(self.phase_box)
        phase_layout.setContentsMargins(5, 5, 5, 5)
        phase_layout.setSpacing(2)

        self.lbl_phase_title = QLabel("PROCEDURE PHASE:")
        self.lbl_phase_title.setFont(QFont("Segoe UI", 7, QFont.Bold))

        self.lbl_phase_name = QLabel("Idle — Holding Steady")
        self.lbl_phase_name.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.lbl_phase_name.setWordWrap(True)

        self.lbl_phase_time = QLabel("Holding steady")
        self.lbl_phase_time.setFont(QFont("Consolas", 8))
        self.lbl_phase_time.setStyleSheet("color: #0284c7;")

        self.phase_progress_bar = QProgressBar()
        self.phase_progress_bar.setFixedHeight(6)
        self.phase_progress_bar.setTextVisible(False)
        self.phase_progress_bar.setRange(0, 100)
        self.phase_progress_bar.setValue(100)
        phase_layout.addWidget(self.lbl_phase_title)
        phase_layout.addWidget(self.lbl_phase_name)
        phase_layout.addWidget(self.lbl_phase_time)
        phase_layout.addWidget(self.phase_progress_bar)
        sidebar_layout.addWidget(self.phase_box)

        mode_box = QHBoxLayout()
        mode_box.setSpacing(4)
        mode_box.setContentsMargins(0, 2, 0, 2)

        self.btn_mode_simple = QPushButton("Simple")
        self.btn_mode_simple.setToolTip("Simple Mode: streamlined safe procedures with a clean interface.")
        self.btn_mode_simple.clicked.connect(lambda: self.toggle_expert_mode(False))
        mode_box.addWidget(self.btn_mode_simple)

        self.btn_mode_expert = QPushButton("Expert")
        self.btn_mode_expert.setToolTip("Expert Mode: show Scripts editor and full list of low-level states.")
        self.btn_mode_expert.clicked.connect(lambda: self.toggle_expert_mode(True))
        mode_box.addWidget(self.btn_mode_expert)

        self.btn_toggle_mode = self.btn_mode_simple  # Backward compatibility alias
        sidebar_layout.addLayout(mode_box)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        sep1.setObjectName("separator")
        sidebar_layout.addWidget(sep1)

        self.btn_reload_scripts = QPushButton("Reload Scripts")
        self.btn_reload_scripts.clicked.connect(self.reload_desktop_scripts)
        self.btn_reload_scripts.setVisible(self.expert_mode)
        sidebar_layout.addWidget(self.btn_reload_scripts)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        sep2.setObjectName("separator")
        sidebar_layout.addWidget(sep2)

        live_row = QHBoxLayout()
        live_row.setSpacing(3)
        self.lbl_data_source = QLabel("● Live")
        self.lbl_data_source.setAlignment(Qt.AlignCenter)
        live_row.addWidget(self.lbl_data_source)
        sidebar_layout.addLayout(live_row)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(3)
        self.btn_live_data = QPushButton("Live")
        self.btn_live_data.setToolTip("Return to live real-time telemetry view")
        self.btn_live_data.setEnabled(False)
        self.btn_live_data.clicked.connect(self.return_to_live)
        zoom_row.addWidget(self.btn_live_data)

        self.btn_reset_zoom = QPushButton("Reset Zoom")
        self.btn_reset_zoom.clicked.connect(self.reset_zoom)
        zoom_row.addWidget(self.btn_reset_zoom)
        sidebar_layout.addLayout(zoom_row)

        # Separator above Heat Switches
        sep_hs = QFrame()
        sep_hs.setFrameShape(QFrame.HLine)
        sep_hs.setFrameShadow(QFrame.Sunken)
        sep_hs.setObjectName("separator")
        sidebar_layout.addWidget(sep_hs)

        # ================= Heat Switches Control (Bottom Left) =================
        self.hs_box = QFrame()
        self.hs_box.setObjectName("heatswitch_box")
        hs_layout = QVBoxLayout(self.hs_box)
        hs_layout.setContentsMargins(0, 2, 0, 2)
        hs_layout.setSpacing(4)


        self.lbl_hs_title = QLabel("HEAT SWITCHES")
        self.lbl_hs_title.setFont(QFont("Segoe UI", 7, QFont.Bold))
        self.lbl_hs_title.setObjectName("muted_label")
        hs_layout.addWidget(self.lbl_hs_title)

        self.btn_hs_pot = QPushButton("● Pot: CLOSED")
        self.btn_hs_pot.setObjectName("btn_hs_pot")
        self.btn_hs_pot.setCursor(Qt.PointingHandCursor)
        self.btn_hs_pot.setToolTip("Pot Heat Switch (Click to toggle). Closed = thermal link engaged, Open = isolated.")
        self.btn_hs_pot.clicked.connect(lambda: self.on_heatswitch_clicked("pot", "Pot"))

        self.btn_hs_adr = QPushButton("● ADR: CLOSED")
        self.btn_hs_adr.setObjectName("btn_hs_adr")
        self.btn_hs_adr.setCursor(Qt.PointingHandCursor)
        self.btn_hs_adr.setToolTip("ADR Heat Switch (Click to toggle). Closed = thermal link engaged, Open = isolated.")
        self.btn_hs_adr.clicked.connect(lambda: self.on_heatswitch_clicked("adr", "ADR"))

        self.btn_hs_charcoal = QPushButton("● Charcoal: CLOSED")
        self.btn_hs_charcoal.setObjectName("btn_hs_charcoal")
        self.btn_hs_charcoal.setCursor(Qt.PointingHandCursor)
        self.btn_hs_charcoal.setToolTip("Charcoal Heat Switch (Click to toggle). Closed = thermal link engaged, Open = isolated.")
        self.btn_hs_charcoal.clicked.connect(lambda: self.on_heatswitch_clicked("charcoal", "Charcoal"))

        hs_layout.addWidget(self.btn_hs_pot)
        hs_layout.addWidget(self.btn_hs_adr)
        hs_layout.addWidget(self.btn_hs_charcoal)

        sidebar_layout.addWidget(self.hs_box)

        self.sep_adr = QFrame()
        self.sep_adr.setFrameShape(QFrame.HLine)
        self.sep_adr.setFrameShadow(QFrame.Sunken)
        self.sep_adr.setObjectName("separator")
        sidebar_layout.addWidget(self.sep_adr)

        # ================= ADR Parameters & Regulation Card (Bottom Left) =================
        self.adr_params_box = QFrame()
        self.adr_params_box.setObjectName("adr_params_box")
        adr_card_layout = QVBoxLayout(self.adr_params_box)
        adr_card_layout.setContentsMargins(5, 5, 5, 5)
        adr_card_layout.setSpacing(4)

        self.lbl_adr_card_title = QLabel("CYCLE & REGULATION PARAMETERS")
        self.lbl_adr_card_title.setFont(QFont("Segoe UI", 7, QFont.Bold))
        self.lbl_adr_card_title.setObjectName("muted_label")
        adr_card_layout.addWidget(self.lbl_adr_card_title)

        # Subsection 1: Heat Setpoints
        lbl_sp_sec = QLabel("HEAT SETPOINTS")
        lbl_sp_sec.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_sp_sec.setObjectName("muted_label")
        adr_card_layout.addWidget(lbl_sp_sec)

        grid_sp = QGridLayout()
        grid_sp.setSpacing(3)
        grid_sp.setContentsMargins(0, 0, 0, 0)

        tip_charcoal_sp = "Cryo-con loop 2 setpoint to heat sorption pump and desorb He-3 gas.\nDefault: 55.0 K."
        lbl_charcoal_sp = QLabel("Charcoal (K):")
        lbl_charcoal_sp.setFont(QFont("Segoe UI", 8))
        lbl_charcoal_sp.setToolTip(tip_charcoal_sp)
        self.spin_charcoal_sp = QDoubleSpinBox()
        self.spin_charcoal_sp.setDecimals(1)
        self.spin_charcoal_sp.setRange(1.0, 150.0)
        self.spin_charcoal_sp.setSingleStep(1.0)
        self.spin_charcoal_sp.setFixedWidth(64)
        self.spin_charcoal_sp.setFixedHeight(22)
        self.spin_charcoal_sp.setValue(float(self.gui_settings.get("adr_config", {}).get("charcoal_heat_sp", 55.0)))
        self.spin_charcoal_sp.setToolTip(tip_charcoal_sp)
        self.spin_charcoal_sp.valueChanged.connect(self._on_adr_param_changed)

        tip_flange_sp = "Cryo-con loop 1 setpoint for 60K flange / stage desorption baking.\nDefault: 65.0 K."
        lbl_flange_sp = QLabel("60K Flange (K):")
        lbl_flange_sp.setFont(QFont("Segoe UI", 8))
        lbl_flange_sp.setToolTip(tip_flange_sp)
        self.spin_flange_sp = QDoubleSpinBox()
        self.spin_flange_sp.setDecimals(1)
        self.spin_flange_sp.setRange(1.0, 300.0)
        self.spin_flange_sp.setSingleStep(1.0)
        self.spin_flange_sp.setFixedWidth(64)
        self.spin_flange_sp.setFixedHeight(22)
        self.spin_flange_sp.setValue(float(self.gui_settings.get("adr_config", {}).get("flange_60k_heat_sp", 65.0)))
        self.spin_flange_sp.setToolTip(tip_flange_sp)
        self.spin_flange_sp.valueChanged.connect(self._on_adr_param_changed)

        tip_pot_precool = "3K stage (Channel C) starting temperature threshold required before cycle begins.\nDefault: 3.2 K."
        lbl_pot_precool = QLabel("3K Starting (K):")
        lbl_pot_precool.setFont(QFont("Segoe UI", 8))
        lbl_pot_precool.setToolTip(tip_pot_precool)
        self.spin_pot_precool = QDoubleSpinBox()
        self.spin_pot_precool.setDecimals(1)
        self.spin_pot_precool.setRange(0.5, 10.0)
        self.spin_pot_precool.setSingleStep(0.1)
        self.spin_pot_precool.setFixedWidth(64)
        self.spin_pot_precool.setFixedHeight(22)
        val_3k = float(self.gui_settings.get("adr_config", {}).get("starting_temp_3k", self.gui_settings.get("adr_config", {}).get("pot_precool_limit_k", 3.2)))
        self.spin_pot_precool.setValue(val_3k)
        self.spin_pot_precool.setToolTip(tip_pot_precool)
        self.spin_pot_precool.valueChanged.connect(self._on_adr_param_changed)
        tip_launch_temp = "FAA stage launch temperature threshold required before opening ADR heat switch and ramping down magnet.\nDefault: 1.0 K."
        lbl_launch_temp = QLabel("Launch Temp (K):")
        lbl_launch_temp.setFont(QFont("Segoe UI", 8))
        lbl_launch_temp.setToolTip(tip_launch_temp)
        self.spin_launch_temp = QDoubleSpinBox()
        self.spin_launch_temp.setDecimals(2)
        self.spin_launch_temp.setRange(0.1, 10.0)
        self.spin_launch_temp.setSingleStep(0.1)
        self.spin_launch_temp.setFixedWidth(64)
        self.spin_launch_temp.setFixedHeight(22)
        val_launch = float(self.gui_settings.get("adr_config", {}).get("launch_temp_k", 1.0))
        self.spin_launch_temp.setValue(val_launch)
        self.spin_launch_temp.setToolTip(tip_launch_temp)
        self.spin_launch_temp.valueChanged.connect(self._on_adr_param_changed)

        grid_sp.addWidget(lbl_charcoal_sp, 0, 0)
        grid_sp.addWidget(self.spin_charcoal_sp, 0, 1)
        grid_sp.addWidget(lbl_flange_sp, 1, 0)
        grid_sp.addWidget(self.spin_flange_sp, 1, 1)
        grid_sp.addWidget(lbl_pot_precool, 2, 0)
        grid_sp.addWidget(self.spin_pot_precool, 2, 1)
        grid_sp.addWidget(lbl_launch_temp, 3, 0)
        grid_sp.addWidget(self.spin_launch_temp, 3, 1)
        adr_card_layout.addLayout(grid_sp)

        # Subsection 2: Hold / Soak / Dwell Times
        lbl_dwell_sec = QLabel("SOAK / DWELL TIMES")
        lbl_dwell_sec.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_dwell_sec.setObjectName("muted_label")
        adr_card_layout.addWidget(lbl_dwell_sec)

        grid_dwell = QGridLayout()
        grid_dwell.setSpacing(3)
        grid_dwell.setContentsMargins(0, 0, 0, 0)

        tip_condense = "Duration to hold charcoal hot (55K) and magnet energized to condense He-3 liquid.\nDefault: 3.5 h."
        lbl_condense = QLabel("Condense (h):")
        lbl_condense.setFont(QFont("Segoe UI", 8))
        lbl_condense.setToolTip(tip_condense)
        self.spin_condense_dwell = QDoubleSpinBox()
        self.spin_condense_dwell.setDecimals(1)
        self.spin_condense_dwell.setRange(0.1, 24.0)
        self.spin_condense_dwell.setSingleStep(0.5)
        self.spin_condense_dwell.setFixedWidth(64)
        self.spin_condense_dwell.setFixedHeight(22)
        self.spin_condense_dwell.setValue(float(self.gui_settings.get("adr_config", {}).get("he3_condense_dwell_h", 3.5)))
        self.spin_condense_dwell.setToolTip(tip_condense)
        self.spin_condense_dwell.valueChanged.connect(self._on_adr_param_changed)

        tip_launch_dwell = "Dwell / settle time (minutes) after opening ADR heat switch at launch temp before beginning magnet ramp down.\nAllows switch actuation friction heat to dissipate. Default: 10.0 min."
        lbl_launch_dwell = QLabel("Launch Settle (min):")
        lbl_launch_dwell.setFont(QFont("Segoe UI", 8))
        lbl_launch_dwell.setToolTip(tip_launch_dwell)
        self.spin_launch_dwell = QDoubleSpinBox()
        self.spin_launch_dwell.setDecimals(1)
        self.spin_launch_dwell.setRange(0.0, 120.0)
        self.spin_launch_dwell.setSingleStep(1.0)
        self.spin_launch_dwell.setFixedWidth(64)
        self.spin_launch_dwell.setFixedHeight(22)
        self.spin_launch_dwell.setValue(float(self.gui_settings.get("adr_config", {}).get("launch_dwell_min", 10.0)))
        self.spin_launch_dwell.setToolTip(tip_launch_dwell)
        self.spin_launch_dwell.valueChanged.connect(self._on_adr_param_changed)

        grid_dwell.addWidget(lbl_condense, 0, 0)
        grid_dwell.addWidget(self.spin_condense_dwell, 0, 1)
        grid_dwell.addWidget(lbl_launch_dwell, 1, 0)
        grid_dwell.addWidget(self.spin_launch_dwell, 1, 1)
        adr_card_layout.addLayout(grid_dwell)

        # Subsection 3: Magnet Ramp Speeds & Output
        lbl_ramp_sec = QLabel("MAGNET RAMP SPEEDS")
        lbl_ramp_sec.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_ramp_sec.setObjectName("muted_label")
        adr_card_layout.addWidget(lbl_ramp_sec)

        grid_ramp = QGridLayout()
        grid_ramp.setSpacing(3)
        grid_ramp.setContentsMargins(0, 0, 0, 0)

        tip_max_hout = "Peak magnet open-loop output % (~9.5 A).\nRamped up in Step 3 and held through the 3.5h condensation dwell. Default: 58.1%."
        lbl_max_hout = QLabel("Max Output (%):")
        lbl_max_hout.setFont(QFont("Segoe UI", 8))
        lbl_max_hout.setToolTip(tip_max_hout)
        self.spin_mag_max_hout = QDoubleSpinBox()
        self.spin_mag_max_hout.setDecimals(1)
        self.spin_mag_max_hout.setRange(0.0, 100.0)
        self.spin_mag_max_hout.setSingleStep(0.5)
        self.spin_mag_max_hout.setFixedWidth(64)
        self.spin_mag_max_hout.setFixedHeight(22)
        self.spin_mag_max_hout.setValue(float(self.gui_settings.get("adr_config", {}).get("magnet_max_hout", 58.1)))
        self.spin_mag_max_hout.setToolTip(tip_max_hout)
        self.spin_mag_max_hout.valueChanged.connect(self._on_adr_param_changed)

        tip_ramp_up = "RAMPED UP: Step 3 (start of cycle, before 3.5h condensation dwell).\nRamps magnet 0% -> full field with ADR switch closed to dump heat. Default: 45.0 min."
        lbl_ramp_up = QLabel("Ramp Up (min):")
        lbl_ramp_up.setFont(QFont("Segoe UI", 8))
        lbl_ramp_up.setToolTip(tip_ramp_up)
        self.spin_mag_ramp_up = QDoubleSpinBox()
        self.spin_mag_ramp_up.setDecimals(1)
        self.spin_mag_ramp_up.setRange(1.0, 120.0)
        self.spin_mag_ramp_up.setSingleStep(5.0)
        self.spin_mag_ramp_up.setFixedWidth(64)
        self.spin_mag_ramp_up.setFixedHeight(22)
        self.spin_mag_ramp_up.setValue(float(self.gui_settings.get("adr_config", {}).get("magnet_ramp_up_min", 45.0)))
        self.spin_mag_ramp_up.setToolTip(tip_ramp_up)
        self.spin_mag_ramp_up.valueChanged.connect(self._on_adr_param_changed)

        tip_ramp_down = "RAMPED DOWN (DEMAG): Step 6 (end of cycle, after charcoal cooling).\nOpens ADR switch and ramps magnet to 0% to cool FAA stage to base (<100 mK). Default: 45.0 min."
        lbl_ramp_down = QLabel("Ramp Down (min):")
        lbl_ramp_down.setFont(QFont("Segoe UI", 8))
        lbl_ramp_down.setToolTip(tip_ramp_down)
        self.spin_mag_ramp_down = QDoubleSpinBox()
        self.spin_mag_ramp_down.setDecimals(1)
        self.spin_mag_ramp_down.setRange(1.0, 120.0)
        self.spin_mag_ramp_down.setSingleStep(5.0)
        self.spin_mag_ramp_down.setFixedWidth(64)
        self.spin_mag_ramp_down.setFixedHeight(22)
        self.spin_mag_ramp_down.setValue(float(self.gui_settings.get("adr_config", {}).get("magnet_ramp_down_min", 60.0)))
        self.spin_mag_ramp_down.setToolTip(tip_ramp_down)
        self.spin_mag_ramp_down.valueChanged.connect(self._on_adr_param_changed)

        tip_settle = "Post-demag hold time (after magnet reaches 0%) before switching to closed PID regulation.\nDefault: 20.0 min."
        lbl_settle = QLabel("Demag Settle (min):")
        lbl_settle.setFont(QFont("Segoe UI", 8))
        lbl_settle.setToolTip(tip_settle)
        self.spin_demag_settle = QDoubleSpinBox()
        self.spin_demag_settle.setDecimals(1)
        self.spin_demag_settle.setRange(0.0, 120.0)
        self.spin_demag_settle.setSingleStep(5.0)
        self.spin_demag_settle.setFixedWidth(64)
        self.spin_demag_settle.setFixedHeight(22)
        self.spin_demag_settle.setValue(float(self.gui_settings.get("adr_config", {}).get("demag_settle_min", 20.0)))
        self.spin_demag_settle.setToolTip(tip_settle)
        self.spin_demag_settle.valueChanged.connect(self._on_adr_param_changed)

        grid_ramp.addWidget(lbl_max_hout, 0, 0)
        grid_ramp.addWidget(self.spin_mag_max_hout, 0, 1)
        grid_ramp.addWidget(lbl_ramp_up, 1, 0)
        grid_ramp.addWidget(self.spin_mag_ramp_up, 1, 1)
        grid_ramp.addWidget(lbl_ramp_down, 2, 0)
        grid_ramp.addWidget(self.spin_mag_ramp_down, 2, 1)
        grid_ramp.addWidget(lbl_settle, 3, 0)
        grid_ramp.addWidget(self.spin_demag_settle, 3, 1)
        adr_card_layout.addLayout(grid_ramp)

        # Subsection 4: Temperature Regulation (Placed at the bottom)
        lbl_reg_sec = QLabel("TEMPERATURE REGULATION")
        lbl_reg_sec.setFont(QFont("Segoe UI", 7, QFont.Bold))
        lbl_reg_sec.setObjectName("muted_label")
        adr_card_layout.addWidget(lbl_reg_sec)

        grid_reg = QGridLayout()
        grid_reg.setSpacing(3)
        grid_reg.setContentsMargins(0, 0, 0, 0)

        tip_reg = "Target temperature for closed-loop Lake Shore 370 PID regulation in RAMP mode (controlling magnet field).\nDefault: 50.0 mK."
        lbl_reg = QLabel("Regulate (mK):")
        lbl_reg.setFont(QFont("Segoe UI", 8))
        lbl_reg.setToolTip(tip_reg)
        self.spin_reg_temp = QDoubleSpinBox()
        self.spin_reg_temp.setDecimals(1)
        self.spin_reg_temp.setRange(1.0, 300000.0)
        self.spin_reg_temp.setSingleStep(5.0)
        self.spin_reg_temp.setFixedWidth(64)
        self.spin_reg_temp.setFixedHeight(22)
        adr_cfg = self.gui_settings.get("adr_config", {})
        if "regulate_temp_mk" in adr_cfg:
            init_mk = float(adr_cfg["regulate_temp_mk"])
        elif "regulate_temp_k" in adr_cfg:
            k_val = float(adr_cfg["regulate_temp_k"])
            init_mk = k_val if k_val >= 1.0 else k_val * 1000.0
        else:
            init_mk = 50.0
        self.spin_reg_temp.setValue(init_mk)
        self.spin_reg_temp.setToolTip(tip_reg)
        self.spin_reg_temp.valueChanged.connect(self._on_adr_param_changed)

        grid_reg.addWidget(lbl_reg, 0, 0)
        grid_reg.addWidget(self.spin_reg_temp, 0, 1)

        self.btn_regulate = QPushButton("Regulate")
        self.btn_regulate.setObjectName("btn_regulate")
        self.btn_regulate.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_regulate.setCursor(Qt.PointingHandCursor)
        self.btn_regulate.setToolTip("Engage or live-update closed-loop temperature regulation at the target setpoint.")
        self.btn_regulate.clicked.connect(self.start_or_update_regulation)
        grid_reg.addWidget(self.btn_regulate, 1, 0, 1, 2)
        adr_card_layout.addLayout(grid_reg)

        # Action Buttons Row: [Update Recipe] and [Reset Recipe Defaults]
        btn_action_row = QHBoxLayout()
        btn_action_row.setSpacing(4)

        self.btn_update_params = QPushButton("Update Recipe")
        self.btn_update_params.setObjectName("btn_update_params")
        self.btn_update_params.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.btn_update_params.setCursor(Qt.PointingHandCursor)
        self.btn_update_params.setToolTip("Hot-update active hardware setpoints (LS370 / Cryo-con) and save all parameter changes.")
        self.btn_update_params.clicked.connect(self.hot_update_params)
        btn_action_row.addWidget(self.btn_update_params, stretch=1)

        self.btn_reset_adr_params = QPushButton("Reset Defaults")
        self.btn_reset_adr_params.setObjectName("btn_reset_adr_params")
        self.btn_reset_adr_params.setFont(QFont("Segoe UI", 8))
        self.btn_reset_adr_params.setToolTip("Reset all setpoints, soak times, ramp durations, and regulation to factory recipe defaults.")
        self.btn_reset_adr_params.clicked.connect(self.reset_default_adr_params)
        btn_action_row.addWidget(self.btn_reset_adr_params, stretch=1)

        adr_card_layout.addLayout(btn_action_row)

        sidebar_layout.addWidget(self.adr_params_box)

        # Set initial visibility of expert section based on current mode
        self.adr_params_box.setVisible(self.expert_mode)
        self.sep_adr.setVisible(self.expert_mode)

        self.sidebar_scroll.setWidget(sidebar_content)
        sidebar_outer_layout.addWidget(self.sidebar_scroll)

        # Forward mouse wheel events on all sidebar inputs directly to sidebar_scroll
        self._sidebar_wheel_forwarder = forward_child_wheel_events(self.sidebar_scroll, sidebar_content)

        main_layout.addWidget(sidebar_frame)

        # ================= Four Primary Navigation Tabs =================
        self.main_tabs = QTabWidget()

        # --- 1. Plots Tab ---
        self.graphs_tab = QWidget()
        graphs_layout = QVBoxLayout()
        graphs_layout.setContentsMargins(1, 1, 1, 1)
        graphs_layout.setSpacing(2)

        # Sleek plot toolbar with View tabs, Time Range, Scale, Theme, and Plot controls
        plot_ctrl_bar = QHBoxLayout()
        plot_ctrl_bar.setContentsMargins(2, 2, 2, 2)
        plot_ctrl_bar.setSpacing(6)

        self.plot_view_tabs = QTabBar()
        self.plot_view_tabs.setObjectName("plot_view_tabs")
        self.plot_view_tabs.setDrawBase(False)
        self.plot_view_tabs.setExpanding(False)
        self.plot_view_tabs.setCursor(Qt.PointingHandCursor)
        self.plot_view_tabs.addTab("Overview")
        self.plot_view_tabs.addTab("Thermometers")
        self.plot_view_tabs.addTab("Pressures")
        self.plot_view_tabs.addTab("Diagnostics")
        self.plot_view_tabs.setCurrentIndex(0)
        self.plot_view_tabs.currentChanged.connect(self._on_plot_tab_index_changed)
        plot_ctrl_bar.addWidget(self.plot_view_tabs)

        plot_ctrl_bar.addSpacing(6)
        lbl_tw = QLabel("Range:")
        lbl_tw.setObjectName("muted_label")
        plot_ctrl_bar.addWidget(lbl_tw)

        self.combo_time_window = QComboBox()
        self.combo_time_window.wheelEvent = lambda event: None
        self.combo_time_window.addItems(["1 Hour", "6 Hours", "1 Day", "1 Week", "1 Month"])
        self.combo_time_window.setCurrentText(self.time_window)
        self.combo_time_window.currentTextChanged.connect(self.on_time_window_changed)
        self.combo_time_window.activated.connect(lambda idx: self.on_time_window_changed(self.combo_time_window.itemText(idx)))
        plot_ctrl_bar.addWidget(self.combo_time_window)

        plot_ctrl_bar.addSpacing(2)
        self.btn_toggle_temp_scale = QPushButton("Log Scale")
        self.btn_toggle_temp_scale.clicked.connect(self.toggle_temp_scale)
        plot_ctrl_bar.addWidget(self.btn_toggle_temp_scale)

        self.btn_subkelvin_filter = QPushButton("Sub-Kelvin")
        self.btn_subkelvin_filter.setCheckable(True)
        self.btn_subkelvin_filter.setToolTip("Toggle to isolate sub-Kelvin stages (Pot & FAA) and rescale Y-axis")
        self.btn_subkelvin_filter.clicked.connect(self.toggle_subkelvin_filter)
        plot_ctrl_bar.addWidget(self.btn_subkelvin_filter)

        self.btn_plot_reset_zoom = QPushButton("Reset Zoom")
        self.btn_plot_reset_zoom.setToolTip("Reset pan & zoom to default time window (or right-click anywhere on the plot)")
        self.btn_plot_reset_zoom.clicked.connect(self.reset_zoom)
        plot_ctrl_bar.addWidget(self.btn_plot_reset_zoom)

        self.btn_snapshot = QPushButton("Snapshot")
        self.btn_snapshot.setToolTip("Export 8-panel cooldown snapshot to ~/2pac_logs/snapshots/")
        self.btn_snapshot.clicked.connect(self.export_plot_snapshot)
        plot_ctrl_bar.addWidget(self.btn_snapshot)

        self.btn_theme_toggle = QPushButton("Light")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        plot_ctrl_bar.addWidget(self.btn_theme_toggle)

        plot_ctrl_bar.addStretch()

        self.figure = plt.Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.figure)
        graphs_layout.addLayout(plot_ctrl_bar)
        graphs_layout.addWidget(self.canvas)

        self.figure.canvas.mpl_connect("motion_notify_event", self.mpl_on_mouse_move)
        self.figure.canvas.mpl_connect("scroll_event", self.mpl_on_scroll)
        self.figure.canvas.mpl_connect("button_press_event", self.mpl_on_click)
        self.figure.canvas.mpl_connect("button_release_event", self.mpl_on_release)

        self.graphs_tab.setLayout(graphs_layout)

        # --- 2. Scripts Tab ---
        self.scripting_tab = QWidget()
        scripting_layout = QVBoxLayout()
        scripting_layout.setContentsMargins(8, 8, 8, 8)
        scripting_layout.setSpacing(6)

        script_bar = QHBoxLayout()
        self.lbl_script_name = QLabel("Active Script: wait_forever")
        self.lbl_script_name.setObjectName("muted_label")
        script_bar.addWidget(self.lbl_script_name)
        script_bar.addStretch()

        self.btn_apply_script = QPushButton("Execute Modified Code")
        self.btn_apply_script.clicked.connect(lambda: self.request_state_change(bypass_confirm=False))
        script_bar.addWidget(self.btn_apply_script)
        scripting_layout.addLayout(script_bar)

        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(False)
        scripting_layout.addWidget(self.text_output)
        self.scripting_tab.setLayout(scripting_layout)

        # --- 3. Channels Tab (Aliases) ---
        self.settings_tab = QWidget()
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(8, 8, 8, 8)
        settings_layout.setSpacing(6)

        settings_top = QHBoxLayout()
        lbl_settings_hdr = QLabel("Channel Aliases")
        lbl_settings_hdr.setObjectName("section_header")
        settings_top.addWidget(lbl_settings_hdr)
        settings_top.addStretch()

        self.btn_reset_aliases = QPushButton("Reset Defaults")
        self.btn_reset_aliases.clicked.connect(self.reset_default_aliases)
        settings_top.addWidget(self.btn_reset_aliases)

        self.btn_save_aliases = QPushButton("Save Aliases")
        self.btn_save_aliases.clicked.connect(self.save_channel_aliases)
        settings_top.addWidget(self.btn_save_aliases)
        settings_layout.addLayout(settings_top)

        lbl_settings_sub = QLabel("Assign human-readable aliases (Pot, FAA, Charcoal, 4K) to telemetry channels:")
        lbl_settings_sub.setObjectName("muted_label")
        settings_layout.addWidget(lbl_settings_sub)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self.alias_grid = QGridLayout(scroll_content)
        self.alias_grid.setSpacing(8)
        self.alias_grid.setContentsMargins(4, 4, 4, 4)

        self.alias_grid.addWidget(QLabel("<b>Hardware Channel</b>"), 0, 0)
        self.alias_grid.addWidget(QLabel("<b>Display Alias</b>"), 0, 1)

        self.alias_inputs = {}
        row_idx = 1
        # Order channels cleanly
        ordered_keys = list(DEFAULT_CHANNEL_ALIASES.keys()) + [k for k in CHANNEL_ALIASES if k not in DEFAULT_CHANNEL_ALIASES]
        for key in ordered_keys:
            alias = CHANNEL_ALIASES.get(key, DEFAULT_CHANNEL_ALIASES.get(key, key))
            lbl_k = QLabel(key)
            lbl_k.setObjectName("muted_label")
            self.alias_grid.addWidget(lbl_k, row_idx, 0)
            inp = QLineEdit(alias)
            self.alias_inputs[key] = inp
            self.alias_grid.addWidget(inp, row_idx, 1)
            row_idx += 1

        self.alias_grid.setRowStretch(row_idx, 1)
        scroll_area.setWidget(scroll_content)
        settings_layout.addWidget(scroll_area)
        self.settings_tab.setLayout(settings_layout)

        # --- 4. History Tab (Database Explorer) ---
        self.db_tab = QWidget()
        db_layout = QVBoxLayout()
        db_layout.setContentsMargins(8, 8, 8, 8)
        db_layout.setSpacing(6)

        db_top_bar = QHBoxLayout()
        lbl_db_hdr = QLabel("Daily Logs History")
        lbl_db_hdr.setObjectName("section_header")
        db_top_bar.addWidget(lbl_db_hdr)
        db_top_bar.addStretch()

        self.btn_select_db_file = QPushButton("Choose File...")
        self.btn_select_db_file.clicked.connect(self.choose_db_file)
        db_top_bar.addWidget(self.btn_select_db_file)

        self.btn_refresh_db = QPushButton("Refresh")
        self.btn_refresh_db.clicked.connect(self.populate_db_table)
        db_top_bar.addWidget(self.btn_refresh_db)

        self.btn_load_selected_run = QPushButton("Load Day")
        self.btn_load_selected_run.clicked.connect(self.load_selected_db_run)
        db_top_bar.addWidget(self.btn_load_selected_run)
        db_layout.addLayout(db_top_bar)

        self.db_table = QTableWidget()
        self.db_table.setColumnCount(4)
        self.db_table.setHorizontalHeaderLabels(["Date", "Data Points", "Time Span", "Size"])
        self.db_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.db_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.db_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.db_table.doubleClicked.connect(self.on_db_row_double_click)
        db_layout.addWidget(self.db_table)

        self.db_tab.setLayout(db_layout)

        # --- 5. Utils Tab ---
        self.utils_tab = self._build_utils_tab()

        # Add tabs: Plots, (Scripts in Expert mode), Channels, History, Utils
        self.main_tabs.addTab(self.graphs_tab, "Plots")
        if self.expert_mode:
            self.main_tabs.addTab(self.scripting_tab, "Scripts")
        self.main_tabs.addTab(self.settings_tab, "Channels")
        self.main_tabs.addTab(self.db_tab, "History")
        self.main_tabs.addTab(self.utils_tab, "Utils")
        self.main_tabs.currentChanged.connect(self._on_main_tab_changed)

        main_layout.addWidget(self.main_tabs, stretch=1)
        outer_layout.addLayout(main_layout, stretch=1)

        # ================= Dual-Row Bottom Status Bar =================
        status_frame = QFrame()
        status_frame.setObjectName("status_frame")
        status_frame.setFixedHeight(44)
        status_bar_layout = QVBoxLayout()
        status_bar_layout.setContentsMargins(8, 2, 8, 2)
        status_bar_layout.setSpacing(0)

        # Row 1: Cursor values in grey
        self.lbl_cursor_vals = QLabel("CURSOR  [Hover over plot to inspect point]")
        self.lbl_cursor_vals.setFont(QFont("Consolas", 9))
        self.lbl_cursor_vals.setFixedHeight(18)
        status_bar_layout.addWidget(self.lbl_cursor_vals)

        # Row 2: Persistent latest values in bold black
        self.lbl_latest_vals = QLabel("LATEST  Waiting for telemetry...")
        self.lbl_latest_vals.setFont(QFont("Consolas", 9, QFont.Bold))
        self.lbl_latest_vals.setFixedHeight(18)
        status_bar_layout.addWidget(self.lbl_latest_vals)

        status_frame.setLayout(status_bar_layout)
        outer_layout.addWidget(status_frame)

        self.setLayout(outer_layout)

        # Apply initial theme 
        self.apply_theme()

        # Initial DB population
        self.populate_db_table()

        # Startup hardware state recovery check
        from daily_logger import get_last_hardware_state
        last_hw = get_last_hardware_state()
        if last_hw and last_hw.get("magnet_current", 0.0) > 0.1:
            prev_i = last_hw["magnet_current"]
            self.show_operator_banner(f"ℹ Magnet energized at {prev_i:.3f} A. Hardware settings held safely from previous session.")

        # Thread setup with completion, error, and operator alert hooks
        first_st = wait_forever
        self.data_thread = DataFetchThread(world, first_state=first_st, states_dict=states_dict)
        self.data_thread.state_update.connect(self.state_update)
        self.data_thread.procedure_finished.connect(self._on_procedure_finished)
        self.data_thread.procedure_error.connect(self._on_procedure_error)
        self.data_thread.operator_action.connect(self._on_operator_action)
        self.data_thread.start()

        # Telemetry watchdog (banner + remote alert when updates stop or readings go NaN)
        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.setInterval(10000)
        self.watchdog_timer.timeout.connect(self._check_telemetry_watchdog)
        self.watchdog_timer.start()

        # Command IPC timer for automation and testing
        self.cmd_timer = QTimer(self)
        self.cmd_timer.setInterval(500)
        self.cmd_timer.timeout.connect(self._check_external_commands)
        self.cmd_timer.start()

        # Dedicated plot refresh timer
        self.plot_timer = QTimer(self)
        cadence_s = int(self.gui_settings.get("plot_refresh_s", 1))
        self.plot_timer.setInterval(cadence_s * 1000)
        self.plot_timer.timeout.connect(self._on_plot_timer)
        self.plot_timer.start()

        # Debounced zoom/pan line updater (for instantaneous responsiveness on scroll/drag)
        self._zoom_update_timer = QTimer(self)
        self._zoom_update_timer.setSingleShot(True)
        self._zoom_update_timer.timeout.connect(self.update_plot)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # 1. Quench Protection / Elevated Magnet Current Check
        magnet_current = abs(getattr(self, "_latest_magnet_current", 0.0))
        cur_state = self.current_selected_state_key()
        is_active_procedure = (cur_state != IDLE_STATE and cur_state is not None)

        if magnet_current > 0.1 or is_active_procedure:
            msg = (
                f"⚠️ Active Hardware / Magnet Current Warning\n\n"
                f"Magnet current is currently elevated at: {magnet_current:.3f} A\n"
                f"Active procedure: {state_label(cur_state)}\n\n"
                "IMPORTANT: Closing the application will leave all physical instrument "
                "settings HELD at their current values (no reset commands will be sent). "
                "The Lake Shore 370 DAC, Cryo-con, and Kepco supply will continue holding current, "
                "but automated software ramps will stop advancing.\n\n"
                "Are you sure you want to close the GUI and hold settings?"
            )
            reply = QMessageBox.warning(
                self,
                "Confirm Exit — Hold Instrument Settings",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        # 2. Persist hardware state snapshot for safe recovery
        from daily_logger import save_hardware_state
        try:
            recent = {}
            if hasattr(self, "live_dataset") and self.live_dataset:
                data = self.live_dataset.cache.data()
                for k in ("faa_temperature", "cryocon_chA_temperature", "cryocon_chB_temperature", "cryocon_chC_temperature", "cryocon_chD_temperature", "labjack_he3_pressure"):
                    if k in data and k in data[k] and len(data[k][k]) > 0:
                        recent[k] = float(data[k][k][-1])
            save_hardware_state(
                magnet_current=magnet_current,
                he3_pressure=recent.get("labjack_he3_pressure", 0.0),
                active_procedure=cur_state or IDLE_STATE,
                phase_name=getattr(self.world, "current_phase", "Holding steady"),
                temperatures=recent,
                heatswitches=self._hs_states,
                relay=self._cached_relay_state(),
            )
        except Exception as e:
            print(f"Warning saving hardware state on close: {e}")

        # 3. Flush daily logger
        if hasattr(self, "daily_logger") and self.daily_logger:
            try:
                self.daily_logger.flush()
            except Exception:
                pass

        # 4. Save window geometry. Merge into the file on disk instead of writing the whole in-memory copy:
        #    on 2026-11-18 a close wrote back a stale pid_config (P 3.5/I 60) over the applied P 7/I 80.
        if not self.isMaximized() and not self.isMinimized():
            disk = load_gui_settings()
            disk["window_geometry"] = {
                "x": self.pos().x(),
                "y": self.pos().y(),
                "width": self.size().width(),
                "height": self.size().height(),
            }
            save_gui_settings(disk)
        event.accept()

    def _cached_relay_state(self):
        """Relay position as last commanded (the latching relay has no feedback). Saved so a restart restores it."""
        try:
            v = self.world.station.labjack.relay.cache.get()
            return v if v in ("CONTROL", "RAMP") else "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def _set_status_badge(self, text, state_key):
        self.lbl_status_badge.setText(text)
        self.current_badge_state = state_key
        style = STATUS_BADGE_STYLES.get(self.theme, {}).get(state_key, "")
        self.lbl_status_badge.setStyleSheet(style)

    def _set_data_source_badge(self, is_live, text=None):
        if text:
            self.lbl_data_source.setText(text)
        else:
            self.lbl_data_source.setText("● Live" if is_live else "● Historical")
        style_key = "live" if is_live else "history"
        style = DATA_SOURCE_STYLES.get(self.theme, {}).get(style_key, "")
        self.lbl_data_source.setStyleSheet(style)

    def _style_temp_scale_btn(self):
        is_light = (self.theme == "light")
        if self.temp_scale == "log":
            self.btn_toggle_temp_scale.setText("Log Scale")
            if is_light:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #ffffff; color: #0284c7; border: 1px solid #0284c7; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
            else:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
        else:
            self.btn_toggle_temp_scale.setText("Linear Scale")
            if is_light:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #ffffff; color: #d97706; border: 1px solid #d97706; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
            else:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #1e293b; color: #fbbf24; border: 1px solid #fbbf24; font-weight: 600; padding: 4px 10px; border-radius: 4px;")

    def apply_theme(self):
        is_light = (self.theme == "light")
        self.setStyleSheet(LIGHT_QSS if is_light else DARK_QSS)

        self._style_temp_scale_btn()

        if is_light:
            self.btn_theme_toggle.setText("Dark")
            self.btn_theme_toggle.setStyleSheet("background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; font-weight: 500; padding: 4px 10px; border-radius: 4px;")
            self.lbl_cursor_vals.setStyleSheet("color: #64748b;")
            self.lbl_latest_vals.setStyleSheet("color: #0f172a;")
            self.metric_cards_bar.setStyleSheet("background-color: transparent;")
            self.phase_box.setStyleSheet("background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;")
            self.lbl_phase_title.setStyleSheet("color: #64748b;")
            self.lbl_phase_name.setStyleSheet("color: #0f172a;")
            self.btn_snapshot.setStyleSheet("background-color: #ffffff; color: #475569; border: 1px solid #cbd5e1; font-weight: 500; padding: 4px 10px; border-radius: 4px;")
            if hasattr(self, "adr_params_box"):
                self.adr_params_box.setStyleSheet("QFrame#adr_params_box { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }")
            if hasattr(self, "btn_regulate"):
                self.btn_regulate.setStyleSheet(
                    "QPushButton#btn_regulate { background-color: #0284c7; color: #ffffff; border: 1px solid #0369a1; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_regulate:hover { background-color: #0369a1; }"
                )
            if hasattr(self, "btn_update_params"):
                self.btn_update_params.setStyleSheet(
                    "QPushButton#btn_update_params { background-color: #475569; color: #ffffff; border: 1px solid #334155; font-weight: 600; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_update_params:hover { background-color: #334155; }"
                )
        else:
            self.btn_theme_toggle.setText("Light")
            self.btn_theme_toggle.setStyleSheet("background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; font-weight: 500; padding: 4px 10px; border-radius: 4px;")
            self.lbl_cursor_vals.setStyleSheet("color: #94a3b8;")
            self.lbl_latest_vals.setStyleSheet("color: #f8fafc;")
            self.metric_cards_bar.setStyleSheet("background-color: transparent;")
            self.phase_box.setStyleSheet("background-color: #0f172a; border: 1px solid #1e293b; border-radius: 6px;")
            self.lbl_phase_title.setStyleSheet("color: #94a3b8;")
            self.lbl_phase_name.setStyleSheet("color: #f8fafc;")
            self.btn_snapshot.setStyleSheet("background-color: #1e293b; color: #cbd5e1; border: 1px solid #334155; font-weight: 500; padding: 4px 10px; border-radius: 4px;")
            if hasattr(self, "adr_params_box"):
                self.adr_params_box.setStyleSheet("QFrame#adr_params_box { background-color: #0f172a; border: 1px solid #1e293b; border-radius: 6px; }")
            if hasattr(self, "btn_regulate"):
                self.btn_regulate.setStyleSheet(
                    "QPushButton#btn_regulate { background-color: #0284c7; color: #ffffff; border: 1px solid #38bdf8; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_regulate:hover { background-color: #0ea5e9; }"
                )
            if hasattr(self, "btn_update_params"):
                self.btn_update_params.setStyleSheet(
                    "QPushButton#btn_update_params { background-color: #334155; color: #f8fafc; border: 1px solid #475569; font-weight: 600; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_update_params:hover { background-color: #475569; }"
                )

        # Digital metric tiles styling — filled solid with plot line colors and white text
        for key, spec in self.metric_tiles.items():
            acc = spec["accent"]
            spec["card"].setStyleSheet(
                f"QFrame#metric_tile {{ background-color: {acc}; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.18); }}"
            )
            if "lbl_t" in spec:
                spec["lbl_t"].setStyleSheet("color: rgba(255, 255, 255, 0.92); font-weight: 700; font-size: 11px; background: transparent;")
            if key == "relay_heater_status":
                spec["val"].setStyleSheet("color: #ffffff; font-weight: 700; font-size: 12px; background: transparent;")
            else:
                spec["val"].setStyleSheet("color: #ffffff; font-weight: 800; font-size: 18px; background: transparent;")

        self._style_subkelvin_btn()
        self._style_mode_btn()
        self._update_heatswitch_ui()

        self._set_status_badge(self.lbl_status_badge.text(), getattr(self, "current_badge_state", "idle"))
        self._set_data_source_badge(not self.displaying_historical)

        thm = THEMES.get(self.theme, THEMES["light"])
        self.figure.set_facecolor(thm["fig_bg"])
        plt.rcParams['xtick.color'] = thm["tick_color"]
        plt.rcParams['ytick.color'] = thm["tick_color"]
        plt.rcParams['text.color'] = thm["text"]
        plt.rcParams['axes.labelcolor'] = thm["text"]
        plt.rcParams['axes.edgecolor'] = thm["spine"]

        for ax in self.figure.axes:
            ax.set_facecolor(thm["ax_bg"])
            for spine in ax.spines.values():
                spine.set_color(thm["spine"])
            ax.tick_params(axis="both", which="both", colors=thm["tick_color"], labelcolor=thm["tick_color"])
            ax.yaxis.set_tick_params(which="both", colors=thm["tick_color"], labelcolor=thm["tick_color"])
            ax.xaxis.set_tick_params(which="both", colors=thm["tick_color"], labelcolor=thm["tick_color"])

        self.update_plot()

    def _style_subkelvin_btn(self):
        is_light = (self.theme == "light")
        if self.btn_subkelvin_filter.isChecked():
            if is_light:
                self.btn_subkelvin_filter.setStyleSheet("background-color: #0284c7; color: white; border: 1px solid #0284c7; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
            else:
                self.btn_subkelvin_filter.setStyleSheet("background-color: #38bdf8; color: #0f172a; border: 1px solid #38bdf8; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
        else:
            if is_light:
                self.btn_subkelvin_filter.setStyleSheet("background-color: #ffffff; color: #0284c7; border: 1px solid #0284c7; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
            else:
                self.btn_subkelvin_filter.setStyleSheet("background-color: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; font-weight: 600; padding: 4px 10px; border-radius: 4px;")

    def toggle_subkelvin_filter(self):
        if self.btn_subkelvin_filter.isChecked():
            self.hidden_channels = {
                "cryocon_chA_temperature",
                "cryocon_chB_temperature",
                "cryocon_chC_temperature"
            }
            self.btn_subkelvin_filter.setText("👁 All Stages")
        else:
            self.hidden_channels = set()
            self.btn_subkelvin_filter.setText("🔍 Sub-Kelvin")
        self._style_subkelvin_btn()
        self.update_plot()

    def export_plot_snapshot(self, *args, bypass_popup=False):
        from datetime import datetime
        now = datetime.now()
        dt_str = now.strftime("%Y-%m-%d_%H-%M-%S")

        snapshots_dir = Path.home() / "2pac_logs" / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        out_path = snapshots_dir / f"snapshot_{dt_str}.png"
        alt_path = snapshots_dir / f"{dt_str}.png"

        dataset = self.historical_dataset if self.displaying_historical else self.live_dataset
        if dataset is None:
            if not bypass_popup:
                QMessageBox.warning(self, "Snapshot Error", "No active dataset available to snapshot.")
            return

        # Get the currently displayed x-limits ("Only the current data with the xrange shown")
        saved_xlim = self.axes_list[0].get_xlim() if (self.axes_list and len(self.axes_list) > 0) else None

        try:
            from plot_utils import export_snapshot_plot
            export_snapshot_plot(dataset, out_path, xlim=saved_xlim)

            # Also provide copy titled directly with datetime format YYYY-MM-DD_HH-MM-SS.png
            try:
                import shutil
                shutil.copy2(str(out_path), str(alt_path))
            except Exception:
                pass

            msg = f"📸 Snapshot saved: {out_path.name}"
            self.lbl_latest_vals.setText(msg)
            if not bypass_popup:
                QMessageBox.information(
                    self,
                    "Plot Snapshot Exported",
                    f"8-panel publication plot exported to:\n\n{out_path}\n\nVisible window data preserved."
                )
        except Exception as e:
            if not bypass_popup:
                QMessageBox.warning(self, "Snapshot Error", f"Could not export snapshot: {e}")
            else:
                print(f"[MyApp] Snapshot export error: {e}")

    def confirm_operator_action(self):
        if hasattr(self, "world") and self.world is not None:
            self.world.confirm_operator_action()
        self.dismiss_operator_banner()

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()

    # ------------- Database / Daily Logs Explorer Methods ---------------
    def choose_db_file(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Log Database or Directory", str(Path.home() / "2pac_logs"), "Database Files (*.db);;All Files (*)", options=options)
        if file_name:
            self.db_file_path = file_name
            try:
                from daily_logger import load_daily_dataset
                ds = load_daily_dataset(file_name)
                self.historical_dataset = ds
                self.displaying_historical = True
                date_tag = Path(file_name).parent.name if Path(file_name).is_file() else Path(file_name).name
                self._set_data_source_badge(False, f"● {date_tag}")
                self.btn_live_data.setEnabled(True)
                self.user_has_zoomed = False
                self.update_plot()
                self.main_tabs.setCurrentWidget(self.graphs_tab)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load dataset:\n\n{e}")

    def populate_db_table(self):
        from daily_logger import list_daily_logs
        try:
            entries = list_daily_logs()
            self._daily_log_entries = entries
            self.db_table.setRowCount(len(entries))
            today_str = datetime.now().strftime("%Y-%m-%d")
            for row_idx, item in enumerate(entries):
                d_str = item["date"]
                disp_date = f"{d_str} (Today)" if d_str == today_str else d_str
                pts_str = f"{item['points']:,}" if item['points'] > 0 else "0"
                size_str = f"{item['size_mb']:.1f} MB"

                self.db_table.setItem(row_idx, 0, QTableWidgetItem(disp_date))
                self.db_table.setItem(row_idx, 1, QTableWidgetItem(pts_str))
                self.db_table.setItem(row_idx, 2, QTableWidgetItem(item["time_range"]))
                self.db_table.setItem(row_idx, 3, QTableWidgetItem(size_str))
        except Exception as e:
            print(f"Error populating daily logs table: {e}")

    def on_db_row_double_click(self, item):
        self.load_selected_db_run()

    def load_selected_db_run(self):
        selected_items = self.db_table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Select Day", "Please select a day from the table first.")
            return

        row = selected_items[0].row()
        if hasattr(self, "_daily_log_entries") and row < len(self._daily_log_entries):
            entry = self._daily_log_entries[row]
            date_str = entry["date"]
            try:
                from daily_logger import load_daily_dataset
                ds = load_daily_dataset(date_str)
                self.historical_dataset = ds
                self.displaying_historical = True
                self._set_data_source_badge(False, f"● Day {date_str}")
                self.btn_live_data.setEnabled(True)
                self.user_has_zoomed = False
                self.update_plot()
                self.main_tabs.setCurrentWidget(self.graphs_tab)
            except Exception as e:
                QMessageBox.warning(self, "Load Error", f"Failed to load daily dataset for {date_str}:\n\n{e}")

    # ------------- Channels Aliases & Script Loader ---------------
    def save_channel_aliases(self):
        for key, inp in self.alias_inputs.items():
            CHANNEL_ALIASES[key] = inp.text().strip() or key
        save_aliases()
        self.update_plot()

    def reset_default_aliases(self):
        CHANNEL_ALIASES.clear()
        CHANNEL_ALIASES.update(DEFAULT_CHANNEL_ALIASES)
        if hasattr(self, "alias_inputs"):
            for key, inp in self.alias_inputs.items():
                inp.setText(CHANNEL_ALIASES.get(key, key))
        save_aliases()
        self.update_plot()
    def _populate_state_combo(self):
        cur_key = self.current_selected_state_key() or IDLE_STATE
        self.combo_box.blockSignals(True)
        self.combo_box.clear()

        if not self.expert_mode:
            for key in SIMPLE_WORKFLOW:
                if key in self.states_dict:
                    self.combo_box.addItem(state_label(key), key)
        else:
            first_keys = [k for k in SIMPLE_WORKFLOW if k in self.states_dict]
            other_keys = sorted([k for k in self.states_dict.keys() if k not in SIMPLE_WORKFLOW])
            for key in first_keys + other_keys:
                self.combo_box.addItem(state_label(key), key)

        found_idx = self.combo_box.findData(cur_key)
        if found_idx >= 0:
            self.combo_box.setCurrentIndex(found_idx)
        elif self.combo_box.count() > 0:
            self.combo_box.setCurrentIndex(0)
        self.combo_box.blockSignals(False)

    def current_selected_state_key(self):
        if not hasattr(self, "combo_box"):
            return None
        idx = self.combo_box.currentIndex()
        if idx >= 0:
            data = self.combo_box.itemData(idx)
            if data:
                return str(data)
        txt = self.combo_box.currentText()
        for k in self.states_dict:
            if state_label(k) == txt or k == txt:
                return k
        return None

    def _style_mode_btn(self):
        if not hasattr(self, "btn_mode_simple") or not hasattr(self, "btn_mode_expert"):
            return
        is_light = (self.theme == "light")
        if self.expert_mode:
            self.btn_mode_simple.setChecked(False)
            self.btn_mode_expert.setChecked(True)
            if is_light:
                self.btn_mode_simple.setStyleSheet(
                    "QPushButton { background-color: #ffffff; color: #64748b; border: 1px solid #cbd5e1; font-weight: 500; padding: 4px; border-radius: 4px; }"
                    "QPushButton:hover { background-color: #f1f5f9; color: #0f172a; }"
                )
                self.btn_mode_expert.setStyleSheet(
                    "QPushButton { background-color: #0284c7; color: #ffffff; border: 1px solid #0284c7; font-weight: 700; padding: 4px; border-radius: 4px; }"
                )
            else:
                self.btn_mode_simple.setStyleSheet(
                    "QPushButton { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; font-weight: 500; padding: 4px; border-radius: 4px; }"
                    "QPushButton:hover { background-color: #334155; color: #f8fafc; }"
                )
                self.btn_mode_expert.setStyleSheet(
                    "QPushButton { background-color: #38bdf8; color: #0f172a; border: 1px solid #38bdf8; font-weight: 700; padding: 4px; border-radius: 4px; }"
                )
        else:
            self.btn_mode_simple.setChecked(True)
            self.btn_mode_expert.setChecked(False)
            if is_light:
                self.btn_mode_simple.setStyleSheet(
                    "QPushButton { background-color: #16a34a; color: #ffffff; border: 1px solid #16a34a; font-weight: 700; padding: 4px; border-radius: 4px; }"
                )
                self.btn_mode_expert.setStyleSheet(
                    "QPushButton { background-color: #ffffff; color: #64748b; border: 1px solid #cbd5e1; font-weight: 500; padding: 4px; border-radius: 4px; }"
                    "QPushButton:hover { background-color: #f1f5f9; color: #0f172a; }"
                )
            else:
                self.btn_mode_simple.setStyleSheet(
                    "QPushButton { background-color: #22c55e; color: #0f172a; border: 1px solid #22c55e; font-weight: 700; padding: 4px; border-radius: 4px; }"
                )
                self.btn_mode_expert.setStyleSheet(
                    "QPushButton { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; font-weight: 500; padding: 4px; border-radius: 4px; }"
                    "QPushButton:hover { background-color: #334155; color: #f8fafc; }"
                )

    def toggle_expert_mode(self, enabled=None):
        if enabled is None:
            self.expert_mode = not self.expert_mode
        else:
            self.expert_mode = bool(enabled)

        print(f"[MODE] Mode switched to: {'Expert' if self.expert_mode else 'Simple'}")
        self.gui_settings["expert_mode"] = self.expert_mode
        save_gui_settings(self.gui_settings)

        self._style_mode_btn()
        if hasattr(self, "chk_expert_mode") and self.chk_expert_mode.isChecked() != self.expert_mode:
            self.chk_expert_mode.blockSignals(True)
            self.chk_expert_mode.setChecked(self.expert_mode)
            self.expert_mode = bool(enabled)

        print(f"[MODE] Mode switched to: {'Expert' if self.expert_mode else 'Simple'}")
        self.gui_settings["expert_mode"] = self.expert_mode
        save_gui_settings(self.gui_settings)

        self._style_mode_btn()
        if hasattr(self, "chk_expert_mode") and self.chk_expert_mode.isChecked() != self.expert_mode:
            self.chk_expert_mode.blockSignals(True)
            self.chk_expert_mode.setChecked(self.expert_mode)
            self.chk_expert_mode.blockSignals(False)

        if hasattr(self, "btn_reload_scripts"):
            self.btn_reload_scripts.setVisible(self.expert_mode)

        if hasattr(self, "adr_params_box"):
            self.adr_params_box.setVisible(self.expert_mode)
        if hasattr(self, "sep_adr"):
            self.sep_adr.setVisible(self.expert_mode)

        if self.expert_mode:
            if hasattr(self, "scripting_tab") and self.main_tabs.indexOf(self.scripting_tab) == -1:
                self.main_tabs.insertTab(1, self.scripting_tab, "Scripts")
        else:
            if hasattr(self, "scripting_tab"):
                idx = self.main_tabs.indexOf(self.scripting_tab)
                if idx != -1:
                    if self.main_tabs.currentIndex() == idx:
                        self.main_tabs.setCurrentWidget(self.graphs_tab)
                    self.main_tabs.removeTab(idx)

        self._populate_state_combo()

    def _on_log_interval_changed(self, val):
        self.world.target_tick_rate_s = float(val)
        self.gui_settings["log_interval_s"] = float(val)
        save_gui_settings(self.gui_settings)

    def _on_plot_cadence_changed(self, val):
        self.plot_timer.setInterval(int(val) * 1000)
        self.gui_settings["plot_refresh_s"] = int(val)
        save_gui_settings(self.gui_settings)

    def _on_text_logs_toggled(self, checked):
        import states
        states.ENABLE_TEXT_LOGGING = bool(checked)
        self.gui_settings["text_logs"] = bool(checked)
        save_gui_settings(self.gui_settings)

    def _on_default_range_changed(self, val):
        norm = "6 Hours"
        t_low = str(val).lower()
        if "month" in t_low or "30" in t_low:
            norm = "1 Month"
        elif "week" in t_low or "7" in t_low:
            norm = "1 Week"
        elif "day" in t_low or "24" in t_low:
            norm = "1 Day"
        elif "1" in t_low and "hour" in t_low:
            norm = "1 Hour"
        elif "6" in t_low and "hour" in t_low:
            norm = "6 Hours"
        elif "all" in t_low:
            norm = "1 Month"

        self.gui_settings["default_range"] = norm
        save_gui_settings(self.gui_settings)
        if hasattr(self, "combo_time_window") and self.combo_time_window.currentText() != norm:
            self.combo_time_window.blockSignals(True)
            self.combo_time_window.setCurrentText(norm)
            self.combo_time_window.blockSignals(False)
        if hasattr(self, "combo_default_range") and self.combo_default_range.currentText() != norm:
            self.combo_default_range.blockSignals(True)
            self.combo_default_range.setCurrentText(norm)
            self.combo_default_range.blockSignals(False)
        self.time_window = norm
        self.user_has_zoomed = False
        self.update_plot()

    def pin_to_dock(self):
        try:
            app_dir = Path.home() / ".local" / "share" / "applications"
            app_dir.mkdir(parents=True, exist_ok=True)
            desktop_path = app_dir / "2pac_gui.desktop"
            desktop_content = """[Desktop Entry]
Version=1.0
Type=Application
Name=2pac gui
Comment=Hardware Control GUI for 2pac ADR
Exec=/home/pcuser/qsp/src/2pac/launch_gui.sh
Path=/home/pcuser/qsp/src/2pac
Icon=/home/pcuser/qsp/src/2pac/adr_gui_icon.png
Terminal=false
StartupWMClass=2pac_gui
Categories=Science;Utility;
"""
            desktop_path.write_text(desktop_content)
            desktop_path.chmod(0o755)

            # Also install to Desktop folder
            desktop_desktop_path = Path.home() / "Desktop" / "2pac_gui.desktop"
            desktop_desktop_path.write_text(desktop_content)
            desktop_desktop_path.chmod(0o755)

            try:
                subprocess.run(["update-desktop-database", str(app_dir)], check=False)
            except Exception:
                pass

            res = subprocess.run(["gsettings", "get", "org.gnome.shell", "favorite-apps"],
                                 capture_output=True, text=True, check=True)
            cur_apps = res.stdout.strip()
            if "2pac_gui.desktop" not in cur_apps:
                import ast
                apps_list = ast.literal_eval(cur_apps) if cur_apps.startswith("[") else []
                if "2pac_gui.desktop" not in apps_list:
                    apps_list.append("2pac_gui.desktop")
                    apps_repr = str(apps_list).replace("'", '"')
                    subprocess.run(["gsettings", "set", "org.gnome.shell", "favorite-apps", apps_repr], check=True)
            QMessageBox.information(self, "Pinned", "2pac gui has been pinned to your GNOME dock / sidebar.")
        except Exception as e:
            QMessageBox.warning(self, "Pin Error", f"Could not pin launcher: {e}")

    def open_logs_directory(self):
        d = Path.home() / "2pac_logs"
        d.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(d)])
        except Exception as e:
            QMessageBox.warning(self, "Open Error", f"Could not open folder: {e}")

    def open_scripts_directory(self):
        d = Path.home() / "Desktop" / "custom_scripts"
        d.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(d)])
        except Exception as e:
            QMessageBox.warning(self, "Open Error", f"Could not open folder: {e}")

    def reload_desktop_scripts(self):
        try:
            from engine import load_all_desktop_scripts
            custom_states = load_all_desktop_scripts()
            self.states_dict.update(custom_states)
            if hasattr(self, "data_thread"):
                self.data_thread.states_dict.update(custom_states)
            
            cur_key = self.current_selected_state_key()
            self._populate_state_combo()
            if cur_key:
                idx = self.combo_box.findData(cur_key)
                if idx >= 0:
                    self.combo_box.setCurrentIndex(idx)

            QMessageBox.information(self, "Reloaded", f"Loaded {len(custom_states)} script(s) from ~/Desktop/custom_scripts/.")
        except Exception as e:
            QMessageBox.warning(self, "Reload Error", f"Failed to reload desktop scripts:\n\n{e}")

    # ------------- ADR Cycle Parameters & Temperature Regulation Methods ---------------
    def _on_adr_param_changed(self):
        """Called whenever any ADR recipe or regulation parameter spinbox is edited."""
        self._sync_adr_config_to_world()
        if hasattr(self, "world") and hasattr(self.world, "adr_config"):
            self.gui_settings["adr_config"] = dict(self.world.adr_config)
            save_gui_settings(self.gui_settings)
        # If actively regulating, push setpoint change to hardware immediately
        is_reg = (self.data_thread and self.data_thread.state and self.data_thread.state.name() == "regulate_temperature")
        if is_reg:
            self.hot_update_params(bypass_popup=True)

    def _sync_adr_config_to_world(self):
        """Synchronize UI spinbox values into world.adr_config."""
        if not hasattr(self, "spin_charcoal_sp"):
            return
        val_3k = float(self.spin_starting_temp_3k.value()) if hasattr(self, "spin_starting_temp_3k") else float(self.spin_pot_precool.value())
        val_launch = float(self.spin_launch_temp.value()) if hasattr(self, "spin_launch_temp") else 1.0
        val_launch_dwell = float(self.spin_launch_dwell.value()) if hasattr(self, "spin_launch_dwell") else 10.0
        cfg = {
            "charcoal_heat_sp": float(self.spin_charcoal_sp.value()),
            "flange_60k_heat_sp": float(self.spin_flange_sp.value()),
            "starting_temp_3k": val_3k,
            "pot_precool_limit_k": val_3k,
            "launch_temp_k": val_launch,
            "launch_dwell_min": val_launch_dwell,
            "he3_condense_dwell_h": float(self.spin_condense_dwell.value()),
            "magnet_max_hout": float(self.spin_mag_max_hout.value()),
            "magnet_ramp_up_min": float(self.spin_mag_ramp_up.value()),
            "magnet_ramp_down_min": float(self.spin_mag_ramp_down.value()),
            "demag_settle_min": float(self.spin_demag_settle.value()),
            "regulate_temp_mk": float(self.spin_reg_temp.value()),
            "regulate_temp_k": float(self.spin_reg_temp.value()) / 1000.0,
        }
        if hasattr(self, "world"):
            self.world.adr_config = cfg

    def reset_default_adr_params(self):
        """Restore all ADR cycle parameters to default recipe values."""
        import states
        defaults = states.DEFAULT_ADR_CONFIG
        val_3k_def = defaults.get("starting_temp_3k", defaults.get("pot_precool_limit_k", 3.2))
        def_reg_mk = defaults.get("regulate_temp_mk", defaults.get("regulate_temp_k", 0.050) * 1000.0)
        if def_reg_mk < 1.0:
            def_reg_mk *= 1000.0
        spins = [
            (self.spin_charcoal_sp, defaults["charcoal_heat_sp"]),
            (self.spin_flange_sp, defaults["flange_60k_heat_sp"]),
            (getattr(self, "spin_starting_temp_3k", self.spin_pot_precool), val_3k_def),
            (getattr(self, "spin_launch_temp", None), defaults.get("launch_temp_k", 1.0)),
            (getattr(self, "spin_launch_dwell", None), defaults.get("launch_dwell_min", 10.0)),
            (self.spin_condense_dwell, defaults["he3_condense_dwell_h"]),
            (self.spin_mag_max_hout, defaults["magnet_max_hout"]),
            (self.spin_mag_ramp_up, defaults["magnet_ramp_up_min"]),
            (self.spin_mag_ramp_down, defaults["magnet_ramp_down_min"]),
            (self.spin_demag_settle, defaults["demag_settle_min"]),
            (self.spin_reg_temp, def_reg_mk),
        ]
        for sp, val in spins:
            if sp is not None:
                sp.blockSignals(True)
                sp.setValue(val)
                sp.blockSignals(False)
        self._on_adr_param_changed()
        QMessageBox.information(self, "Defaults Restored", "ADR cycle recipe parameters restored to factory defaults.")

    def hot_update_params(self, bypass_popup=False):
        """
        Hot-updates active hardware setpoints and saves all parameter changes immediately.
        - Updates world.adr_config and saves to gui_settings.json.
        - If Lake Shore 370 is actively running regulate_temperature, updates LS370 setpoint live via write command (no queries).
        - If Cryo-con loops are active, updates loop setpoints live.
        """
        self._sync_adr_config_to_world()
        if hasattr(self, "world") and hasattr(self.world, "adr_config"):
            self.gui_settings["adr_config"] = dict(self.world.adr_config)
            save_gui_settings(self.gui_settings)

        target_mk = float(self.spin_reg_temp.value())
        target_k = target_mk / 1000.0 if target_mk >= 1.0 else target_mk
        disp_target = f"{target_mk:.1f} mK" if target_mk < 1000.0 else f"{target_k:.3f} K"

        def _apply_live_updates():
            try:
                if hasattr(self, "world") and hasattr(self.world, "station") and self.world.station:
                    st = self.world.station
                    # 1. Hot update the LS370 setpoint when regulating. Only SETP is written: the loop
                    #    configuration (CSET/PID/range/mode) belongs to regulate_temperature and Utils ->
                    #    Apply (CMODE/HTRRNG are kept honest by regulate_temperature), so nothing here
                    #    may re-send CMODE or a hard-coded PID based on a readback (P0-6).
                    if hasattr(st, "ls370") and st.ls370:
                        rc = st.ls370.heater
                        try:
                            is_reg = (self.data_thread and self.data_thread.state and self.data_thread.state.name() == "regulate_temperature")
                            lst = getattr(self, "_ls370_loop", None) or {}
                            is_closed = (getattr(rc, "commanded_mode", None) == "closed") or bool(lst.get("closed_loop"))
                            if is_reg or is_closed:
                                st.ls370.write(f"SETP {target_k:.4f}")
                                if hasattr(rc, "setpoint") and hasattr(rc.setpoint, "cache"):
                                    rc.setpoint.cache.set(target_k)
                                print(f"[HOT UPDATE] LS370 closed-loop setpoint hot-updated to {target_k:.4f} K ({disp_target})")
                        except Exception as e:
                            print(f"[HOT UPDATE] LS370 setpoint update error: {e}")

                    # 2. Hot update Cryo-con loops if loop control is active
                    if hasattr(st, "cryocon") and st.cryocon:
                        try:
                            flange_sp = float(self.spin_flange_sp.value())
                            charcoal_sp = float(self.spin_charcoal_sp.value())
                            st.cryocon.loop1_setpoint(flange_sp)
                            st.cryocon.loop2_setpoint(charcoal_sp)
                            print(f"[HOT UPDATE] Cryo-con loop setpoints updated: Flange={flange_sp:.1f} K, Charcoal={charcoal_sp:.1f} K")
                        except Exception as e:
                            print(f"[HOT UPDATE] Cryo-con update error: {e}")
            except Exception as e:
                print(f"[HOT UPDATE] Error applying live updates: {e}")

        threading.Thread(target=_apply_live_updates, daemon=True).start()

        # Visual feedback on button
        if hasattr(self, "btn_update_params"):
            self.btn_update_params.setText("✓ Updated")
            self.btn_update_params.setStyleSheet(
                "QPushButton#btn_update_params { background-color: #16a34a; color: #ffffff; border: 1px solid #15803d; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
            )
            QTimer.singleShot(1500, self._restore_update_btn_style)

    def _restore_update_btn_style(self):
        if hasattr(self, "btn_update_params"):
            self.btn_update_params.setText("Update Recipe")
            is_light = (self.theme == "light")
            if is_light:
                self.btn_update_params.setStyleSheet(
                    "QPushButton#btn_update_params { background-color: #475569; color: #ffffff; border: 1px solid #334155; font-weight: 600; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_update_params:hover { background-color: #334155; }"
                )
            else:
                self.btn_update_params.setStyleSheet(
                    "QPushButton#btn_update_params { background-color: #334155; color: #f8fafc; border: 1px solid #475569; font-weight: 600; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_update_params:hover { background-color: #475569; }"
                )

    def _restore_regulate_btn_style(self):
        if hasattr(self, "btn_regulate"):
            self.btn_regulate.setText("Regulate")
            is_light = (self.theme == "light")
            if is_light:
                self.btn_regulate.setStyleSheet(
                    "QPushButton#btn_regulate { background-color: #0284c7; color: #ffffff; border: 1px solid #0369a1; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_regulate:hover { background-color: #0369a1; }"
                )
            else:
                self.btn_regulate.setStyleSheet(
                    "QPushButton#btn_regulate { background-color: #0284c7; color: #ffffff; border: 1px solid #38bdf8; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
                    "QPushButton#btn_regulate:hover { background-color: #0ea5e9; }"
                )

    def start_or_update_regulation(self):
        """
        Engage or live-update closed-loop temperature regulation at the setpoint in spin_reg_temp.
        - Synchronizes spin_reg_temp to world.adr_config and saves to gui_settings.json.
        - If already in regulate_temperature state, hot-updates the LS370 setpoint live.
        - If not currently in regulate_temperature (e.g. idle in wait_forever), verifies magnet safety
          and transitions state machine directly to regulate_temperature.
        """
        self._sync_adr_config_to_world()
        if hasattr(self, "world") and hasattr(self.world, "adr_config"):
            self.gui_settings["adr_config"] = dict(self.world.adr_config)
            save_gui_settings(self.gui_settings)

        target_mk = float(self.spin_reg_temp.value())
        target_k = target_mk / 1000.0 if target_mk >= 1.0 else target_mk
        disp_target = f"{target_mk:.1f} mK" if target_mk < 1000.0 else f"{target_k:.3f} K"

        cur_st_name = ""
        if hasattr(self, "data_thread") and self.data_thread and self.data_thread.state:
            cur_st_name = self.data_thread.state.name()

        if cur_st_name == "regulate_temperature":
            self.hot_update_params(bypass_popup=True)
            if hasattr(self, "btn_regulate"):
                self.btn_regulate.setText(f"✓ {disp_target}")
                self.btn_regulate.setStyleSheet(
                    "QPushButton#btn_regulate { background-color: #16a34a; color: #ffffff; border: 1px solid #15803d; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
                )
                QTimer.singleShot(1500, self._restore_regulate_btn_style)
        else:
            cur_relay = None
            if hasattr(self, "world") and hasattr(self.world, "station") and hasattr(self.world.station, "labjack"):
                try:
                    cur_relay = self.world.station.labjack.relay.cache.get()
                except Exception:
                    cur_relay = None
            mag_I = abs(getattr(self, "_latest_magnet_current", 0.0))
            if cur_relay != "CONTROL" and mag_I > _states_mod.MAGNET_ENERGIZED_A:
                QMessageBox.warning(
                    self,
                    "Regulation Blocked",
                    f"Magnet current is elevated at {mag_I:.3f} A!\n\n"
                    "Cannot engage temperature regulation while magnet is energized.\n"
                    "Run 'Ramp Down Magnet' first."
                )
                return

            if "regulate_temperature" in self.states_dict:
                st = self.states_dict["regulate_temperature"]
                idx = self.combo_box.findData("regulate_temperature")
                if idx >= 0:
                    self.combo_box.blockSignals(True)
                    self.combo_box.setCurrentIndex(idx)
                    self.combo_box.blockSignals(False)
                self.data_thread.next_state = st
                self.data_thread.paused = False
                self._set_status_badge("RUNNING", "running")
                self.lbl_script_name.setText(f"Active Script: {state_label('regulate_temperature')}")
                if hasattr(self, "btn_regulate"):
                    self.btn_regulate.setText(f"✓ Regulating @ {disp_target}")
                    self.btn_regulate.setStyleSheet(
                        "QPushButton#btn_regulate { background-color: #16a34a; color: #ffffff; border: 1px solid #15803d; font-weight: 700; border-radius: 4px; padding: 4px 8px; }"
                    )
                    QTimer.singleShot(1500, self._restore_regulate_btn_style)

    def request_state_change(self, bypass_confirm=False):
        target_state = self.current_selected_state_key()
        if not target_state or target_state not in self.states_dict:
            return

        disp_name = state_label(target_state)
        if not bypass_confirm:
            if target_state in ("he3_adr_cycle", "he3_adr_resume_at_ramp", "he3_only_cycle", "autocool_he3_adr"):
                mag_I = abs(getattr(self, "_latest_magnet_current", 0.0))
                if mag_I > _states_mod.MAGNET_ENERGIZED_A:
                    QMessageBox.critical(
                        self,
                        f"🛑 Cannot Start {disp_name}",
                        f"Magnet current is currently elevated at {mag_I:.3f} A!\n\n"
                        f"Starting {disp_name} requires the magnet to be completely de-energized.\n\n"
                        "Please run 'Ramp Down Magnet' first to safely de-energize the magnet.",
                        QMessageBox.Ok
                    )
                    return
                if target_state == "autocool_he3_adr":
                    cycle_desc = (
                        "Autonomous full cooldown (300 K to base):\n"
                        "- Closes all heat switches for pre-cooling from 300 K.\n"
                        "- Safely waits ~29 hours for 3K stage to reach < 3.2 K using slow adaptive polling (60s/30s/10s).\n"
                        "- Automatically launches He-3 condensation, 9.5 A magnet ramp, demag, and regulation."
                    )
                elif target_state == "he3_adr_resume_at_ramp":
                    cycle_desc = (
                        "RESUME at magnet ramp: skips the heat-switch reset and 3K < 3.2 K check, "
                        "keeps the Cryo-con heating the charcoal, and ramps the magnet from 0 on the 10 mA range. "
                        "Is the KEPCO ON?"
                    )
                elif target_state == "he3_only_cycle":
                    cycle_desc = (
                        "Current procedure will verify 3K starting temp < 3.2 K, heat charcoal to 55 K, "
                        "condense He-3 (3.5 h), and cool charcoal to reach base temp (~300 mK). "
                        "The ADR heat switch remains connected (CLOSED) to the pot, and the magnet will not be used."
                    )
                else:
                    cycle_desc = (
                        "Current procedure will verify 3K starting temp < 3.2 K, heat charcoal to 55 K, "
                        "ramp ADR to full field, condense He-3 (3.5 h), and demag."
                    )
                reply = QMessageBox.question(
                    self,
                    f"⚠️ Pre-Flight Check: {disp_name}",
                    f"Please verify before starting:\n\n"
                    f"1. Is the GREEN He-3 valve on the cryostat CLOSED?\n"
                    f"2. {cycle_desc}\n\n"
                    "Has the green valve been closed and are you ready to proceed?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
            elif target_state == "ramp_down_magnet":
                cur_I = abs(getattr(self, "_latest_magnet_current", 0.0))
                reply = QMessageBox.question(
                    self,
                    "Confirm Magnet Ramp-Down",
                    f"Current magnet current is {cur_I:.3f} A.\n\n"
                    "This will safely ramp the Lake Shore 370 magnet output from its current "
                    "setting down to 0% at the standard controlled rate.\n\n"
                    "Do you want to begin ramp-down?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
            elif target_state == "warmup_300K":
                mag_I = abs(getattr(self, "_latest_magnet_current", 0.0))
                if mag_I > _states_mod.MAGNET_ENERGIZED_A:
                    QMessageBox.critical(
                        self,
                        "🛑 Cannot Start Warm Up to 300 K",
                        f"DANGER: Magnet is energized with current at {mag_I:.3f} A!\n\n"
                        "Warming the cryostat while the magnet is energized will trigger a violent "
                        "magnet quench as soon as the superconducting coils warm above ~9 K.\n\n"
                        "Please run 'Ramp Down Magnet' first to safely de-energize the magnet.",
                        QMessageBox.Ok
                    )
                    return
                reply = QMessageBox.warning(
                    self,
                    "⚠️ Confirm Cryostat Warm-Up to 300 K",
                    "WARNING: You are about to initiate Warm Up to 300 K!\n\n"
                    "1. Ensure the GREEN He-3 valve on the cryostat is OPEN so expanding gas "
                    "can vent safely into the room-temperature storage tank.\n"
                    "2. This will apply heat and warm the entire cryostat to 295 K, "
                    "which takes several hours and requires a complete cooldown cycle to recover.\n\n"
                    "Are you absolutely sure you want to proceed?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
            elif target_state == "regulate_temperature":
                target_mk = float(self.spin_reg_temp.value())
                target_k = target_mk / 1000.0
                disp_target = f"{target_mk:.1f} mK" if target_mk < 1000.0 else f"{target_k:.3f} K"
                reply = QMessageBox.question(
                    self,
                    'Confirm Temperature Regulation',
                    f'Switch to closed-loop temperature regulation at {disp_target}?',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
            else:
                reply = QMessageBox.question(self, 'Confirm Procedure',
                                             f'Switch to procedure: {disp_name}?',
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self._sync_adr_config_to_world()
        self.previewing_state = None
        self.dismiss_operator_banner()

        editor_text = self.text_output.toPlainText()
        lines = editor_text.split('\n')
        clean_lines = []
        for line in lines:
            if line.startswith('--> '):
                clean_lines.append(line[4:])
            elif line.startswith('    '):
                clean_lines.append(line[4:])
            else:
                clean_lines.append(line)
        clean_source = '\n'.join(clean_lines)

        orig_state = self.states_dict.get(target_state)
        # If running via external command / bypass, or standard state in states_dict, run orig_state directly
        if bypass_confirm or (target_state in self.states_dict and not getattr(self, "_editor_user_modified", False)):
            if hasattr(self, "data_thread"):
                self.data_thread.next_state = orig_state
                self.data_thread.paused = False
            self.btn_pause.setText("Pause")
            self._set_status_badge("RUNNING", "running")
            self.lbl_script_name.setText(f"Active Script: {disp_name}")
            return

        try:
            from engine import State, insert_line_number_yields, collect_exits, remove_decorators, parse_txt_to_python
            import states as states_module

            py_source = parse_txt_to_python(target_state, clean_source)
            source = remove_decorators(py_source)
            new_source = insert_line_number_yields(source)
            exits = collect_exits(source)

            exec_globals = dict(states_module.__dict__)
            new_code = compile(new_source, f"<edited {target_state}>", "exec")
            exec(new_code, exec_globals)

            func_name = None
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("def "):
                    func_name = stripped.split("(")[0].replace("def ", "").strip()
                    break

            if not func_name and target_state in exec_globals:
                func_name = target_state

            if func_name and func_name in exec_globals:
                has_def_in_clean = any(l.strip().startswith("def ") for l in clean_source.splitlines())
                display_src = clean_source if not has_def_in_clean else None
                dynamic_state = State(exits, source, new_source, exec_globals[func_name], display_source=display_src)
                self.states_dict[target_state] = dynamic_state
                if hasattr(self, "data_thread"):
                    self.data_thread.states_dict[target_state] = dynamic_state
                    self.data_thread.next_state = dynamic_state
                    self.data_thread.paused = False
                self.btn_pause.setText("Pause")
                self._set_status_badge("RUNNING", "running")
                self.lbl_script_name.setText(f"Active Script: {disp_name} (modified)")
            else:
                QMessageBox.warning(self, "Error", f"Could not find function for '{disp_name}'.")
        except SyntaxError as se:
            QMessageBox.warning(self, "Syntax Error", f"Syntax error in '{disp_name}' (line {se.lineno}):\n\n{se.text or ''}\n{se}")
        except Exception as e:
            QMessageBox.warning(self, "Compile Error", f"Failed to compile script '{disp_name}':\n\n{e}")

    def on_combo_changed(self, index=None):
        state_key = self.current_selected_state_key()
        if state_key and state_key in self.states_dict:
            state = self.states_dict[state_key]
            self.text_output.setReadOnly(False)
            self.text_output.setText(state.code_highlighted(0))
            self.previewing_state = state_key
            self.lbl_script_name.setText(f"Preview: {state_label(state_key)}")

    def toggle_pause(self):
        if self.data_thread.paused:
            self.data_thread.paused = False
            self.btn_pause.setText("Pause")
            self._set_status_badge("RUNNING", "running")
        else:
            self.data_thread.paused = True
            self.btn_pause.setText("Resume")
            self._set_status_badge("PAUSED", "paused")

    def stop_state(self, bypass_confirm=False):
        is_reg = bool(getattr(self, "data_thread", None) and self.data_thread.state
                      and self.data_thread.state.name() == "regulate_temperature")
        zero_ls370_output = False
        if not bypass_confirm:
            current = abs(getattr(self, "_latest_magnet_current", 0.0))
            if is_reg and current <= _states_mod.MAGNET_ENERGIZED_A:
                # The PID runs inside the LS370 and keeps running when the software stops. Never send CMODE 4:
                # on this unit it only blanks the front panel ("off") while the output keeps regulating.
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle("Stop regulation")
                box.setText(
                    "The PID runs inside the Lake Shore 370.\n\n"
                    "Keep regulating: the LS370 keeps holding the setpoint on its own (front panel shows closed loop); "
                    "the software just stops supervising.\n"
                    "Output to 0 %: open loop at 0 %; the remaining magnet current decays through the 12 Ohm in seconds.")
                btn_keep = box.addButton("Keep LS370 regulating", QMessageBox.AcceptRole)
                btn_zero = box.addButton("Output to 0 %", QMessageBox.DestructiveRole)
                btn_cancel = box.addButton("Cancel", QMessageBox.RejectRole)
                box.setDefaultButton(btn_keep)
                box.exec_()
                clicked = box.clickedButton()
                if clicked == btn_cancel or clicked is None:
                    return
                zero_ls370_output = (clicked == btn_zero)
            elif current > _states_mod.MAGNET_ENERGIZED_A:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Warning)
                box.setWindowTitle("⚠️ Elevated Magnet Current Warning")
                box.setText(
                    f"Magnet current is currently elevated at {current:.3f} A!\n\n"
                    "Stopping the procedure now will leave the magnet energized.\n"
                    "What would you like to do?"
                )
                btn_ramp = box.addButton("Ramp Down Safely", QMessageBox.AcceptRole)
                btn_hold = box.addButton("Hold Current & Idle", QMessageBox.DestructiveRole)
                btn_cancel = box.addButton("Cancel", QMessageBox.RejectRole)
                box.setDefaultButton(btn_ramp)
                box.exec_()
                clicked = box.clickedButton()
                if clicked == btn_cancel:
                    return
                elif clicked == btn_ramp:
                    self.previewing_state = None
                    self.dismiss_operator_banner()
                    idx = self.combo_box.findData("ramp_down_magnet")
                    if idx >= 0:
                        self.combo_box.blockSignals(True)
                        self.combo_box.setCurrentIndex(idx)
                        self.combo_box.blockSignals(False)
                    self.data_thread.set_combo_value("ramp_down_magnet")
                    self._set_status_badge("RUNNING", "running")
                    self.lbl_script_name.setText(f"Active Script: {state_label('ramp_down_magnet')}")
                    return
                # If btn_hold was clicked, proceed to idle below
            else:
                reply = QMessageBox.question(self, 'Confirm Stop',
                                             'Stop current procedure and switch to Idle?',
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return
        if zero_ls370_output:
            def _zero():
                try:
                    self.world.station.ls370.heater.output_off()
                    print("[STOP] LS370 output set to 0 % (open loop).")
                except Exception as e:
                    print(f"[STOP] could not zero the LS370 output: {e}")
            threading.Thread(target=_zero, daemon=True).start()
        elif is_reg:
            print("[STOP] Regulation supervision stopped; the LS370 keeps regulating (closed loop).")

        self.previewing_state = None
        self.dismiss_operator_banner()
        idx = self.combo_box.findData(IDLE_STATE)
        if idx >= 0 and self.combo_box.currentIndex() != idx:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(idx)
            self.combo_box.blockSignals(False)
        self.data_thread.set_combo_value(IDLE_STATE)
        self._set_status_badge("STOPPED", "stopped")
        self.lbl_script_name.setText(f"Active Script: {state_label(IDLE_STATE)}")

    def return_to_live(self):
        self.displaying_historical = False
        self.historical_dataset = None
        self._set_data_source_badge(True, "● Live")
        self.btn_live_data.setEnabled(False)
        self.user_has_zoomed = False
        self.update_plot()

    # ------------- Plot Interaction ---------------
    def _on_plot_tab_index_changed(self, index):
        if hasattr(self, 'plot_view_tabs') and 0 <= index < self.plot_view_tabs.count():
            tab_name = self.plot_view_tabs.tabText(index)
            self.on_view_changed(tab_name)

    def on_view_changed(self, text):
        self.active_plot_tab = text
        if hasattr(self, 'plot_view_tabs'):
            for i in range(self.plot_view_tabs.count()):
                t = self.plot_view_tabs.tabText(i).lower()
                req = text.lower()
                if t == req or (req in ("pressures", "pressure") and t in ("pressures", "pressure")):
                    if self.plot_view_tabs.currentIndex() != i:
                        self.plot_view_tabs.blockSignals(True)
                        self.plot_view_tabs.setCurrentIndex(i)
                        self.plot_view_tabs.blockSignals(False)
                    break
        self.user_has_zoomed = False
        self.update_plot()

    def on_time_window_changed(self, text):
        norm = "6 Hours"
        t_low = str(text).lower()
        if "month" in t_low or "30" in t_low:
            norm = "1 Month"
        elif "week" in t_low or "7" in t_low:
            norm = "1 Week"
        elif "day" in t_low or "24" in t_low:
            norm = "1 Day"
        elif "1" in t_low and "hour" in t_low:
            norm = "1 Hour"
        elif "6" in t_low and "hour" in t_low:
            norm = "6 Hours"
        elif "all" in t_low:
            norm = "1 Month"

        self.time_window = norm
        self.gui_settings["default_range"] = norm
        save_gui_settings(self.gui_settings)
        if hasattr(self, "combo_default_range") and self.combo_default_range.currentText() != norm:
            self.combo_default_range.blockSignals(True)
            self.combo_default_range.setCurrentText(norm)
            self.combo_default_range.blockSignals(False)
        if hasattr(self, "combo_time_window") and self.combo_time_window.currentText() != norm:
            self.combo_time_window.blockSignals(True)
            self.combo_time_window.setCurrentText(norm)
            self.combo_time_window.blockSignals(False)
        self.user_has_zoomed = False
        self.update_plot()

    def toggle_temp_scale(self):
        self.temp_scale = "linear" if self.temp_scale == "log" else "log"
        self._style_temp_scale_btn()
        self.user_has_zoomed = False
        self.update_plot()

    def _on_main_tab_changed(self, idx):
        if hasattr(self, "graphs_tab") and hasattr(self, "main_tabs") and self.main_tabs.currentWidget() == self.graphs_tab:
            self.update_plot()

    def _update_readout_status_only(self):
        """Updates metric readout cards in header without triggering expensive Matplotlib redraw."""
        dataset = self.historical_dataset if self.displaying_historical else self.live_dataset
        if dataset is None or not hasattr(dataset, "cache"):
            return
        data = dataset.cache.data()
        data_mr = {}
        for key in data.keys():
            if key in data and key in data[key] and len(data[key][key]) > 0:
                data_mr[key] = data[key][key][-1]
        from plot_utils import get_dataset_units
        units = get_dataset_units(dataset)
        self._update_latest_status(data_mr, units, list(data_mr.keys()))

    def _on_plot_timer(self):
        try:
            self._apply_wiring_r_to_plot()
        except Exception:
            pass
        self._on_plot_timer_inner()

    def _on_plot_timer_inner(self):
        self.sync_heatswitch_states_from_hardware()
        if self._drag_active:
            return
        if not self.displaying_historical:
            # If minimized, hidden, or user is browsing another tab, update metric cards only and skip Matplotlib draw
            is_plots_tab = hasattr(self, "main_tabs") and hasattr(self, "graphs_tab") and (self.main_tabs.currentWidget() == self.graphs_tab)
            if self.isMinimized() or not self.isVisible() or not is_plots_tab:
                self._update_readout_status_only()
                return
            self.update_plot()

    # ------------- Core Update ---------------
    def state_update(self, s1, s2):
        running_state = s1.split(" ")[0].replace("state=", "") if s1.startswith("state=") else ""
        
        # Update badge
        if "PAUSED" in s1:
            self._set_status_badge("PAUSED", "paused")
        elif running_state == IDLE_STATE:
            self._set_status_badge("IDLE", "idle")
        else:
            self._set_status_badge("RUNNING", "running")

        disp_title = state_label(running_state)
        self.setWindowTitle(f"2pac gui — {disp_title}")

        # Update procedure phase progress widget
        phase_name = getattr(self.world, "current_phase", "Holding steady")
        step = getattr(self.world, "phase_step", 1)
        tot_steps = getattr(self.world, "total_steps", 1)

        if running_state == IDLE_STATE or not running_state:
            self.lbl_phase_name.setText("Idle — Holding Steady")
            self.lbl_phase_time.setText("Standing by")
            self.phase_progress_bar.setValue(100)
        else:
            # Strip any redundant prefix like "Step X/Y:" or "X/Y:" if present
            clean_phase = re.sub(r'^(?:Step\s+)?\d+/\d+:\s*', '', phase_name).strip()
            # Strip any trailing timer annotations in parentheses, e.g. (2700s), (Remaining: 2h), (3.5h)
            clean_phase = re.sub(r'\s*\((?:Remaining:\s*)?[\d\.]+\s*(?:s|m|h|min|sec|hours?|minutes?)[^\)]*\)$', '', clean_phase, flags=re.IGNORECASE).strip()
            if tot_steps > 1:
                self.lbl_phase_name.setText(f"Step {step}/{tot_steps}: {clean_phase}")
            else:
                self.lbl_phase_name.setText(clean_phase)
            rem_s = getattr(self.world, "to_wait_for_process_line", 0.0)
            wait_dur = getattr(self.world, "wait_duration_s", 0.0)
            if rem_s > 0 and wait_dur > 0:
                pct = int(max(0, min(100, ((wait_dur - rem_s) / wait_dur) * 100)))
                if rem_s >= 3600:
                    time_str = f"Remaining: {int(rem_s // 3600)}h {int((rem_s % 3600) // 60)}m"
                elif rem_s >= 60:
                    time_str = f"Remaining: {int(rem_s // 60)}m {int(rem_s % 60)}s"
                else:
                    time_str = f"Remaining: {int(rem_s)}s"
                self.lbl_phase_time.setText(time_str)
                self.phase_progress_bar.setValue(pct)
            else:
                self.lbl_phase_time.setText("Active step executing...")
                self.phase_progress_bar.setValue(int((step / max(1, tot_steps)) * 100))

        if self.previewing_state is None or self.previewing_state == running_state:
            self.previewing_state = None
            if running_state in self.states_dict:
                idx = self.combo_box.findData(running_state)
                if idx >= 0 and self.combo_box.currentIndex() != idx:
                    self.combo_box.blockSignals(True)
                    self.combo_box.setCurrentIndex(idx)
                    self.combo_box.blockSignals(False)

            self.lbl_script_name.setText(f"Active Script: {disp_title}")
            # Only update and recolor code text editor if visible in Expert mode and changed
            if self.expert_mode and hasattr(self, "text_output"):
                if getattr(self, "_last_rendered_s2", None) != s2:
                    self._last_rendered_s2 = s2
                    self.text_output.setReadOnly(False)
                    self.text_output.setText(s2)
                    textCursor = self.text_output.textCursor()
                    textCursor.setPosition(get_arrow_char_index(s2, plus=100))
                    color_line(self.text_output, get_arrow_linenum(s2), theme=self.theme)
                    self.text_output.setTextCursor(textCursor)

    def update_plot(self):
        dataset = self.historical_dataset if self.displaying_historical else self.live_dataset
        xloc_for_vals = self.on_mouse_move_event.xdata if self.on_mouse_move_event and self.on_mouse_move_event.inaxes else None

        saved_xlim = self.axes_list[0].get_xlim() if (self.user_has_zoomed and self.axes_list) else None
        saved_ylims = [ax.get_ylim() for ax in self.axes_list] if (self.user_has_zoomed and self.axes_list) else []

        active_tw = "All Time" if (self.user_has_zoomed or self.displaying_historical) else self.time_window
        result = plot_dataset(self.figure, dataset, xloc_for_vals, filter_tab=self.active_plot_tab,
                              temp_scale=self.temp_scale, time_window=active_tw, theme=self.theme,
                              custom_xlim=saved_xlim, hidden_channels=self.hidden_channels)
        data_mr, data_xloc, units, keys, self.axes_list = result

        if self.axes_list:
            if self.user_has_zoomed and saved_xlim is not None:
                self.axes_list[0].set_xlim(saved_xlim)
                for idx, ax in enumerate(self.axes_list):
                    if idx < len(saved_ylims):
                        ax.set_ylim(saved_ylims[idx])

        self._update_latest_status(data_mr, units, keys)
        self.canvas.draw_idle()
