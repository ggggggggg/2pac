"""
The Utils tab: LS370 PID/heater settings (apply/read/reset), wiring resistance, logging and plot options.

Mixin for gui.MyApp (split out of gui.py, P1-12). Methods are unchanged; they use the
MyApp instance (self) and the shared names in gui_common.
"""
from gui_common import *  # noqa: F401,F403
from gui_common import _states_mod  # noqa: F401


class UtilsTabMixin:

    def _build_utils_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # 1. Lake Shore 370 Closed-Loop PID & Temperature Control
        grp_pid = QGroupBox("Lake Shore 370 Closed-Loop PID and Heater Settings")
        pid_main_layout = QVBoxLayout(grp_pid)
        pid_main_layout.setSpacing(10)
        pid_main_layout.setContentsMargins(12, 14, 12, 12)

        lbl_pid_desc = QLabel(
            "Configure active closed-loop PID control gains, heater resistance (R), "
            "setpoint ramping, and excitation range for sub-Kelvin temperature regulation on the FAA stage (Channel 4)."
        )
        lbl_pid_desc.setWordWrap(True)
        lbl_pid_desc.setObjectName("muted_label")
        pid_main_layout.addWidget(lbl_pid_desc)

        pid_cfg = self.gui_settings.get("pid_config", {})

        # Grid of parameters (3 columns)
        pid_grid = QGridLayout()
        pid_grid.setHorizontalSpacing(16)
        pid_grid.setVerticalSpacing(8)

        # --- Column 1: PID Gains ---
        lbl_gain_hdr = QLabel("PID Gains")
        lbl_gain_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        pid_grid.addWidget(lbl_gain_hdr, 0, 0, 1, 2)

        pid_grid.addWidget(QLabel("Proportional Gain (P):"), 1, 0)
        self.spin_pid_p = QDoubleSpinBox()
        self.spin_pid_p.setRange(0.001, 1000.0)
        self.spin_pid_p.setDecimals(3)
        self.spin_pid_p.setSingleStep(0.01)
        self.spin_pid_p.setValue(float(pid_cfg.get("p", _states_mod.REGULATION_DEFAULTS["p"])))
        self.spin_pid_p.setToolTip("Lake Shore 370 closed loop Proportional gain. Best measured in true CONTROL: 7 (2026-11-17).")
        pid_grid.addWidget(self.spin_pid_p, 1, 1)

        pid_grid.addWidget(QLabel("Integral Reset (I):"), 2, 0)
        self.spin_pid_i = QDoubleSpinBox()
        self.spin_pid_i.setRange(0.1, 1000.0)
        self.spin_pid_i.setDecimals(1)
        self.spin_pid_i.setSingleStep(1.0)
        self.spin_pid_i.setSuffix(" s")
        self.spin_pid_i.setValue(float(pid_cfg.get("i", _states_mod.REGULATION_DEFAULTS["i"])))
        self.spin_pid_i.setToolTip("Lake Shore 370 closed loop Integral reset time (s). Best measured: 80 s (120 s recovers slowly from heat pulses).")
        pid_grid.addWidget(self.spin_pid_i, 2, 1)

        pid_grid.addWidget(QLabel("Derivative Rate (D):"), 3, 0)
        self.spin_pid_d = QDoubleSpinBox()
        self.spin_pid_d.setRange(0.0, 200.0)
        self.spin_pid_d.setDecimals(1)
        self.spin_pid_d.setSingleStep(1.0)
        self.spin_pid_d.setSuffix(" s")
        self.spin_pid_d.setValue(float(pid_cfg.get("d", 0.0)))
        self.spin_pid_d.setToolTip("Lake Shore 370 closed loop Derivative rate in seconds. Default: 0.0 s")
        pid_grid.addWidget(self.spin_pid_d, 3, 1)

        # --- Column 2: Heater & Loop Setup (CSET) ---
        lbl_cset_hdr = QLabel("Heater Setup (CSET)")
        lbl_cset_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        pid_grid.addWidget(lbl_cset_hdr, 0, 2, 1, 2)

        pid_grid.addWidget(QLabel("Heater Resistance (R):"), 1, 2)
        self.spin_pid_r = QDoubleSpinBox()
        self.spin_pid_r.setRange(1.0, 2000.0)
        self.spin_pid_r.setDecimals(1)
        self.spin_pid_r.setSingleStep(1.0)
        self.spin_pid_r.setSuffix(" Ω")
        self.spin_pid_r.setValue(float(pid_cfg.get("heater_resistance", 100.0)))
        self.spin_pid_r.setToolTip("Stage control resistor resistance in Ohms (CSET resistance parameter). Default: 100.0 Ω")
        pid_grid.addWidget(self.spin_pid_r, 1, 3)

        pid_grid.addWidget(QLabel("Control Channel:"), 2, 2)
        self.spin_pid_channel = QSpinBox()
        self.spin_pid_channel.setRange(1, 16)
        self.spin_pid_channel.setValue(int(pid_cfg.get("channel", 4)))
        self.spin_pid_channel.setToolTip("Sensor channel used for closed-loop control. Channel 4 = FAA stage.")
        pid_grid.addWidget(self.spin_pid_channel, 2, 3)

        pid_grid.addWidget(QLabel("Current Limit:"), 3, 2)
        self.combo_pid_limit = QComboBox()
        limits = [
            ("1: 31.6 µA", 1),
            ("2: 100 µA", 2),
            ("3: 316 µA", 3),
            ("4: 1 mA", 4),
            ("5: 3.16 mA", 5),
            ("6: 10 mA", 6),
            ("7: 31.6 mA", 7),
            ("8: 100 mA", 8),
        ]
        for txt, val in limits:
            self.combo_pid_limit.addItem(txt, val)
        cur_lim = int(pid_cfg.get("heater_limit", _states_mod.REGULATION_DEFAULTS["heater_limit"]))
        idx_lim = self.combo_pid_limit.findData(cur_lim)
        if idx_lim >= 0:
            self.combo_pid_limit.setCurrentIndex(idx_lim)
        self.combo_pid_limit.setToolTip("Maximum heater output current limit setting (CSET max range code).")
        pid_grid.addWidget(self.combo_pid_limit, 3, 3)

        # --- Column 3: Setpoint Ramping & Excitation Range ---
        lbl_ramp_hdr = QLabel("Setpoint Ramping and Range")
        lbl_ramp_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        pid_grid.addWidget(lbl_ramp_hdr, 0, 4, 1, 2)

        self.chk_pid_ramp_enable = QCheckBox("Enable Setpoint Ramping")
        self.chk_pid_ramp_enable.setChecked(bool(pid_cfg.get("ramp_enable", False)))
        self.chk_pid_ramp_enable.setToolTip("Enable or disable continuous setpoint ramping on the Lake Shore 370 (RAMP command).")
        pid_grid.addWidget(self.chk_pid_ramp_enable, 1, 4, 1, 2)

        pid_grid.addWidget(QLabel("Ramp Speed / Rate:"), 2, 4)
        self.spin_pid_ramp_rate = QDoubleSpinBox()
        self.spin_pid_ramp_rate.setRange(0.1, 5000.0)
        self.spin_pid_ramp_rate.setDecimals(1)
        self.spin_pid_ramp_rate.setSingleStep(1.0)
        self.spin_pid_ramp_rate.setSuffix(" mK/min")
        self.spin_pid_ramp_rate.setValue(float(pid_cfg.get("ramp_rate_mk_min", 10.0)))
        self.spin_pid_ramp_rate.setToolTip("Setpoint ramp rate in mK/min (e.g. 10.0 mK/min = 0.010 K/min on Lake Shore 370 RAMP).")
        pid_grid.addWidget(self.spin_pid_ramp_rate, 2, 5)

        pid_grid.addWidget(QLabel("Excitation Range:"), 3, 4)
        self.combo_pid_range = QComboBox()
        self.combo_pid_range.addItems(["off", "31.6uA", "100uA", "316uA", "1mA", "3.16mA", "10mA", "31.6mA", "100mA"])
        self.combo_pid_range.setCurrentText(str(pid_cfg.get("heater_range", "10mA")))
        self.combo_pid_range.setToolTip("Lake Shore 370 heater excitation output range (HTRRNG). Default: 10mA (with 100Ω Kepco shunt).")
        pid_grid.addWidget(self.combo_pid_range, 3, 5)

        pid_main_layout.addLayout(pid_grid)

        # Action Buttons Row
        pid_btns_row = QHBoxLayout()
        pid_btns_row.setSpacing(8)

        self.btn_apply_pid = QPushButton("Update and Apply Settings")
        self.btn_apply_pid.setObjectName("btn_apply_pid")
        self.btn_apply_pid.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_apply_pid.setCursor(Qt.PointingHandCursor)
        self.btn_apply_pid.setToolTip("Write PID gains, CSET (R value), RAMP rate, and heater range directly to the Lake Shore 370 and save to settings.")
        self.btn_apply_pid.clicked.connect(self.apply_pid_settings)
        pid_btns_row.addWidget(self.btn_apply_pid)

        self.btn_read_pid = QPushButton("Read from Instrument")
        self.btn_read_pid.setFont(QFont("Segoe UI", 9))
        self.btn_read_pid.setCursor(Qt.PointingHandCursor)
        self.btn_read_pid.setToolTip("Query live registers (PID?, CSET?, RAMP?, HTRRNG?) directly from Lake Shore 370 and update controls.")
        self.btn_read_pid.clicked.connect(self.read_pid_from_instrument)
        pid_btns_row.addWidget(self.btn_read_pid)

        self.btn_reset_pid_defaults = QPushButton("Reset Recipe Defaults")
        self.btn_reset_pid_defaults.setFont(QFont("Segoe UI", 9))
        self.btn_reset_pid_defaults.setCursor(Qt.PointingHandCursor)
        self.btn_reset_pid_defaults.setToolTip("Reset controls to the measured-best true-CONTROL values: P=7, I=80 s, D=0, R=100 Ω, 10 mA range, limit 7.")
        self.btn_reset_pid_defaults.clicked.connect(self.reset_pid_defaults)
        pid_btns_row.addWidget(self.btn_reset_pid_defaults)

        pid_btns_row.addStretch()
        pid_main_layout.addLayout(pid_btns_row)

        # Latching Relay Control Row
        relay_ctrl_row = QHBoxLayout()
        relay_ctrl_row.setSpacing(8)
        lbl_r_hdr = QLabel("Latching Relay (Pins 16/18):")
        lbl_r_hdr.setFont(QFont("Segoe UI", 9, QFont.Bold))
        relay_ctrl_row.addWidget(lbl_r_hdr)

        self.btn_relay_ctrl_mode = QPushButton("Set to CONTROL (Pin 18)")
        self.btn_relay_ctrl_mode.setCursor(Qt.PointingHandCursor)
        self.btn_relay_ctrl_mode.setToolTip("Pulse CIO2 (Pin 18) for 1.0 s: relay contact OPENS, putting the 12 Ω resistor in series with the magnet (regulation). Needs ~0 A and LS370 output 0 %.")
        self.btn_relay_ctrl_mode.clicked.connect(lambda: self._switch_relay_mode_direct("CONTROL"))
        relay_ctrl_row.addWidget(self.btn_relay_ctrl_mode)

        self.btn_relay_ramp_mode = QPushButton("Set to RAMP (Pin 16)")
        self.btn_relay_ramp_mode.setCursor(Qt.PointingHandCursor)
        self.btn_relay_ramp_mode.setToolTip("Pulse CIO0 (Pin 16) for 1.0 s: relay contact CLOSES, shorting the 12 Ω resistor (full-field ramps, ~0.12 Ω circuit). Needs ~0 A and LS370 output 0 %.")
        self.btn_relay_ramp_mode.clicked.connect(lambda: self._switch_relay_mode_direct("RAMP"))
        relay_ctrl_row.addWidget(self.btn_relay_ramp_mode)

        self.lbl_relay_mode_status = QLabel("State: —")
        self.lbl_relay_mode_status.setObjectName("muted_label")
        relay_ctrl_row.addWidget(self.lbl_relay_mode_status)
        relay_ctrl_row.addStretch()
        pid_main_layout.addLayout(relay_ctrl_row)

        self.lbl_pid_status = QLabel("Ready")
        self.lbl_pid_status.setObjectName("muted_label")
        pid_main_layout.addWidget(self.lbl_pid_status)

        layout.addWidget(grp_pid)

        # 2. Telemetry and Hardware Loop Group
        grp_telemetry = QGroupBox("Hardware Telemetry and Logging")
        telemetry_form = QFormLayout(grp_telemetry)
        telemetry_form.setLabelAlignment(Qt.AlignLeft)
        telemetry_form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        telemetry_form.setSpacing(10)
        telemetry_form.setContentsMargins(12, 16, 12, 12)

        self.spin_log_interval = QDoubleSpinBox()
        self.spin_log_interval.setRange(0.1, 60.0)
        self.spin_log_interval.setSingleStep(0.1)
        self.spin_log_interval.setDecimals(1)
        self.spin_log_interval.setSuffix(" s")
        self.spin_log_interval.setValue(float(getattr(self.world, "target_tick_rate_s", 1.0)))
        self.spin_log_interval.valueChanged.connect(self._on_log_interval_changed)
        telemetry_form.addRow("Hardware Log Interval:", self.spin_log_interval)

        self.spin_plot_cadence = QSpinBox()
        self.spin_plot_cadence.setRange(1, 30)
        self.spin_plot_cadence.setSingleStep(1)
        self.spin_plot_cadence.setSuffix(" s")
        cadence_val = int(self.gui_settings.get("plot_refresh_s", 1))
        self.spin_plot_cadence.setValue(cadence_val)
        self.spin_plot_cadence.valueChanged.connect(self._on_plot_cadence_changed)
        telemetry_form.addRow("Plot Refresh Cadence:", self.spin_plot_cadence)

        self.chk_text_logging = QCheckBox("Record per-channel CSV text logs (~/2pac_logs/<date>/*.log)")
        self.chk_text_logging.setChecked(bool(self.gui_settings.get("text_logs", True)))
        self.chk_text_logging.toggled.connect(self._on_text_logs_toggled)
        telemetry_form.addRow("Text Log Files:", self.chk_text_logging)

        self.combo_default_range = QComboBox()
        self.combo_default_range.addItems(["1 Hour", "6 Hours", "1 Day", "1 Week", "1 Month"])
        self.combo_default_range.setCurrentText(self.time_window)
        self.combo_default_range.currentTextChanged.connect(self._on_default_range_changed)
        telemetry_form.addRow("Default Time Range:", self.combo_default_range)

        # Wiring resistance per relay position for the inductive-voltage plot (Kepco V - I*R). Locked
        # unless "Modify?" is ticked, so it can't be changed by accident (P1-13).
        mag_cfg = self.gui_settings.get("magnet_config", {})
        wr_row = QHBoxLayout()
        wr_row.setSpacing(6)
        self.spin_wire_r = {}
        for key, label, default, dec in (("RAMP", "RAMP", 0.120, 3), ("CONTROL", "CONTROL", 12.0, 2)):
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 50.0)
            sp.setDecimals(dec)
            sp.setSingleStep(0.001 if dec == 3 else 0.01)
            sp.setFixedWidth(72)
            sp.setValue(float(mag_cfg.get(f"wiring_r_{key.lower()}_ohm", default)))
            sp.setReadOnly(True)
            sp.setButtonSymbols(QDoubleSpinBox.NoButtons)
            sp.setToolTip(
                f"Series resistance of the Kepco circuit with the relay in {key} (Ohm). The Utils plot shows "
                f"Kepco V - I*R, i.e. only L*dI/dt. Measure at a steady current (dI/dt = 0): R = V/I. "
                f"Expected ~0.12 Ohm (RAMP: contact shorts the 12 Ohm) and ~12.1 Ohm (CONTROL: contact open, 12 Ohm + wiring).")
            sp.valueChanged.connect(lambda v, k=key: self._on_wiring_r_changed(k, v))
            self.spin_wire_r[key] = sp
            lbl = QLabel(label)
            lbl.setObjectName("muted_label")
            wr_row.addWidget(lbl)
            wr_row.addWidget(sp)
        self.chk_wire_r_modify = QCheckBox("Modify?")
        self.chk_wire_r_modify.setToolTip("Unlock the wiring resistance boxes. Untick to lock them again.")
        self.chk_wire_r_modify.toggled.connect(self._on_wiring_r_lock_toggled)
        wr_row.addWidget(self.chk_wire_r_modify)
        self.btn_wire_r_measure = QPushButton("Measure")
        self.btn_wire_r_measure.setEnabled(False)
        self.btn_wire_r_measure.setToolTip(
            "Fill the box for the current relay position from the last 60 s of Kepco V and I. Only works at a "
            "steady current (|dI/dt| ~ 0, |I| > 50 mA). Needs Modify? ticked.")
        self.btn_wire_r_measure.clicked.connect(self._measure_wiring_r)
        wr_row.addWidget(self.btn_wire_r_measure)
        wr_row.addStretch()
        telemetry_form.addRow("Wiring R (Ω):", wr_row)
        self._apply_wiring_r_to_plot()

        layout.addWidget(grp_telemetry)

        # 2. Operating Mode and Shortcuts Group
        grp_mode = QGroupBox("Operating Mode and Shortcuts")
        mode_layout = QVBoxLayout(grp_mode)
        mode_layout.setSpacing(10)
        mode_layout.setContentsMargins(12, 16, 12, 12)

        self.chk_expert_mode = QCheckBox("Expert Mode (show Scripts tab and desktop script loader)")
        self.chk_expert_mode.setChecked(self.expert_mode)
        self.chk_expert_mode.toggled.connect(self.toggle_expert_mode)
        mode_layout.addWidget(self.chk_expert_mode)

        lbl_mode_hint = QLabel("Simple Mode provides standard procedures (Idle, Ready for Cooldown, He-3 / ADR Cycle, Warm Up) with a clean, foolproof interface. Expert Mode exposes Python code execution and custom desktop scripts.")
        lbl_mode_hint.setWordWrap(True)
        lbl_mode_hint.setObjectName("muted_label")
        mode_layout.addWidget(lbl_mode_hint)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)

        self.btn_pin_launcher = QPushButton("Pin to Dock / Sidebar")
        self.btn_pin_launcher.clicked.connect(self.pin_to_dock)
        actions_row.addWidget(self.btn_pin_launcher)

        self.btn_open_logs = QPushButton("Open Logs Folder")
        self.btn_open_logs.clicked.connect(self.open_logs_directory)
        actions_row.addWidget(self.btn_open_logs)

        self.btn_open_scripts = QPushButton("Open Desktop Scripts")
        self.btn_open_scripts.clicked.connect(self.open_scripts_directory)
        actions_row.addWidget(self.btn_open_scripts)

        actions_row.addStretch()
        mode_layout.addLayout(actions_row)
        layout.addWidget(grp_mode)

        # 3. Hardware and Environment Status Group
        grp_status = QGroupBox("Hardware and Environment Status")
        status_form = QFormLayout(grp_status)
        status_form.setSpacing(8)
        status_form.setContentsMargins(12, 16, 12, 12)

        self.lbl_diag_log_dir = QLabel(str(Path.home() / "2pac_logs"))
        self.lbl_diag_log_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_form.addRow("Logs Directory:", self.lbl_diag_log_dir)

        db_path_str = self.db_file_path or "Auto-detect on live run"
        self.lbl_diag_db_path = QLabel(db_path_str)
        self.lbl_diag_db_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_form.addRow("QCoDeS Database:", self.lbl_diag_db_path)

        instruments = []
        if hasattr(self.world, "station") and self.world.station:
            st = self.world.station
            if hasattr(st, "cryocon") and st.cryocon is not None:
                instruments.append("Cryocon 24C (Active)")
            if hasattr(st, "ls370") and st.ls370 is not None:
                instruments.append("Lake Shore 370 (Active)")
            if hasattr(st, "labjack") and st.labjack is not None:
                instruments.append("LabJack U6 (Active)")
        if not instruments:
            instruments_str = "Simulated / Live station"
        else:
            instruments_str = " • ".join(instruments)

        self.lbl_diag_instruments = QLabel(instruments_str)
        status_form.addRow("Instruments:", self.lbl_diag_instruments)

        layout.addWidget(grp_status)
        layout.addStretch()

        scroll.setWidget(content)
        self._utils_wheel_forwarder = forward_child_wheel_events(scroll, content)
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return tab

    # ---- wiring resistance (P1-13) ----
    def _on_wiring_r_lock_toggled(self, unlocked):
        for sp in self.spin_wire_r.values():
            sp.setReadOnly(not unlocked)
            sp.setButtonSymbols(QDoubleSpinBox.UpDownArrows if unlocked else QDoubleSpinBox.NoButtons)
        self.btn_wire_r_measure.setEnabled(bool(unlocked))

    def _on_wiring_r_changed(self, key, value):
        mc = self.gui_settings.setdefault("magnet_config", {})
        old = mc.get(f"wiring_r_{key.lower()}_ohm")
        mc[f"wiring_r_{key.lower()}_ohm"] = round(float(value), 4)
        save_gui_settings(self.gui_settings)
        print(f"[Wiring R] {key}: {old} -> {value:.4f} Ohm (saved to gui_settings.json magnet_config)")
        self._apply_wiring_r_to_plot()

    def _apply_wiring_r_to_plot(self):
        import plot_utils
        for key, sp in getattr(self, "spin_wire_r", {}).items():
            plot_utils.WIRING_R_OHM[key] = float(sp.value())
        rel = self._cached_relay_state()
        plot_utils.ACTIVE_RELAY = rel if rel in ("RAMP", "CONTROL") else None

    def _measure_wiring_r(self):
        """R = V/I from the last 60 s of the text logs, if the current was steady."""
        rel = self._cached_relay_state()
        if rel not in ("RAMP", "CONTROL"):
            QMessageBox.information(self, "Measure Wiring R", "Relay position unknown; can't tell which box to fill.")
            return
        day = Path.home() / "2pac_logs" / datetime.now().strftime("%Y-%m-%d")

        def tail(name):
            try:
                rows = (day / f"{name}.log").read_text().splitlines()[-200:]
                out = []
                for r in rows:
                    a = r.split(",", 2)
                    out.append((float(a[0]), float(a[2])))
                return out
            except Exception:
                return []
        now = time.time()
        V = [(t, v) for t, v in tail("kepco_voltage") if now - t < 60 and np.isfinite(v)]
        I = [(t, v) for t, v in tail("kepco_current") if now - t < 60 and np.isfinite(v)]
        if len(V) < 10 or len(I) < 10:
            QMessageBox.information(self, "Measure Wiring R", "Not enough recent Kepco V/I samples (need 60 s of logging).")
            return
        ti = np.array([t for t, _ in I]); iv = np.array([v for _, v in I]); vv = np.array([v for _, v in V])
        didt = np.polyfit(ti - ti[0], iv, 1)[0] if len(ti) > 2 else 0.0
        i_mean = float(np.mean(iv))
        if abs(i_mean) < 0.05 or abs(didt) * 60 > 0.02 * abs(i_mean) + 0.002:
            QMessageBox.information(self, "Measure Wiring R",
                                    f"Current not steady enough: I = {i_mean:.3f} A, dI/dt = {didt*60*1000:.1f} mA/min.\n"
                                    "Measure at a constant plateau with |I| > 50 mA.")
            return
        r = float(np.mean(vv)) / i_mean
        reply = QMessageBox.question(self, "Measure Wiring R",
                                     f"Relay {rel}: V = {np.mean(vv):.4f} V, I = {i_mean:.4f} A -> R = {r:.4f} Ohm.\n"
                                     f"(Kepco V reads ~0.89 V with the Kepco OFF; only use this with it ON.)\n\nSave as {rel} wiring R?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.spin_wire_r[rel].setValue(r)

    def _handle_pid_status(self, msg):
        """Thread-safe handler for PID status message updates."""
        if hasattr(self, "lbl_pid_status") and self.lbl_pid_status:
            self.lbl_pid_status.setText(msg)
        if msg.startswith("✓ Applied") and hasattr(self, "btn_apply_pid"):
            orig_text = "Update and Apply Settings"
            self.btn_apply_pid.setText("✓ Settings Applied!")
            self.btn_apply_pid.setStyleSheet("background-color: #16a34a; color: #ffffff; font-weight: bold; border-radius: 4px; padding: 6px 12px;")
            QTimer.singleShot(1500, lambda: self._restore_apply_pid_btn(orig_text))

    def _restore_apply_pid_btn(self, orig_text):
        if hasattr(self, "btn_apply_pid"):
            self.btn_apply_pid.setText(orig_text)
            self.btn_apply_pid.setStyleSheet("")

    def _handle_pid_read(self, data):
        """Thread-safe handler for populating UI controls with readback data."""
        pid_parts = data.get("pid_parts", [])
        cset_parts = data.get("cset_parts", [])
        ramp_parts = data.get("ramp_parts", [])
        range_str = data.get("range_str", "100uA")
        pid_raw = data.get("pid_raw", "")

        if len(pid_parts) >= 3:
            self.spin_pid_p.setValue(pid_parts[0])
            self.spin_pid_i.setValue(pid_parts[1])
            self.spin_pid_d.setValue(pid_parts[2])
        if len(cset_parts) >= 7:
            try:
                self.spin_pid_channel.setValue(int(cset_parts[0]))
                lim = int(cset_parts[5])
                idx = self.combo_pid_limit.findData(lim)
                if idx >= 0:
                    self.combo_pid_limit.setCurrentIndex(idx)
                self.spin_pid_r.setValue(float(cset_parts[6]))
            except Exception:
                pass
        if len(ramp_parts) >= 2:
            try:
                self.chk_pid_ramp_enable.setChecked(ramp_parts[0] == "1")
                self.spin_pid_ramp_rate.setValue(float(ramp_parts[1]) * 1000.0)
            except Exception:
                pass
        self.combo_pid_range.setCurrentText(range_str)
        ramp_txt = f"Ramp {'ON (' + str(round(float(ramp_parts[1])*1000.0, 1)) + ' mK/min)' if (len(ramp_parts) >= 2 and ramp_parts[0] == '1') else 'OFF'}"
        r_val = cset_parts[6] if len(cset_parts) >= 7 else "100"
        self.lbl_pid_status.setText(f"✓ Read from hardware: PID ({pid_raw}) | R={r_val}Ω | {ramp_txt} | Range={range_str}")

    def apply_pid_settings(self):
        """Write user-configured PID, CSET (resistance R), RAMP, and heater range to Lake Shore 370."""
        p = float(self.spin_pid_p.value())
        i = float(self.spin_pid_i.value())
        d = float(self.spin_pid_d.value())
        r = float(self.spin_pid_r.value())
        ch = int(self.spin_pid_channel.value())
        limit = int(self.combo_pid_limit.currentData() if self.combo_pid_limit.currentData() is not None else _states_mod.REGULATION_DEFAULTS["heater_limit"])
        htr_range = str(self.combo_pid_range.currentText())
        ramp_en = 1 if self.chk_pid_ramp_enable.isChecked() else 0
        ramp_rate_mk = float(self.spin_pid_ramp_rate.value())
        ramp_rate_k = ramp_rate_mk / 1000.0

        # Save to gui_settings
        self.gui_settings["pid_config"] = {
            "p": p,
            "i": i,
            "d": d,
            "heater_resistance": r,
            "channel": ch,
            "heater_limit": limit,
            "heater_range": htr_range,
            "ramp_enable": bool(ramp_en),
            "ramp_rate_mk_min": ramp_rate_mk,
        }
        save_gui_settings(self.gui_settings)

        self.lbl_pid_status.setText("Writing parameters to Lake Shore 370...")

        def _do_apply():
            try:
                st = getattr(self.world, "station", None) if hasattr(self, "world") else None
                ls = getattr(st, "ls370", None) if st else None
                rc = getattr(ls, "heater", None) if ls else None
                if ls:
                    ls.write(f"CSET {ch}, 1, 1, 1, 1, {limit}, {r:.1f}")
                    import time
                    time.sleep(0.15)
                    ls.write(f"PID {p:.4f}, {i:.1f}, {d:.1f}")
                    time.sleep(0.15)
                    ls.write(f"RAMP {ramp_en}, {ramp_rate_k:.4f}")
                    time.sleep(0.15)
                    if rc:
                        try:
                            rc.range(htr_range)
                        except Exception:
                            range_map = {"off": 0, "31.6uA": 1, "100uA": 2, "316uA": 3, "1mA": 4, "3.16mA": 5, "10mA": 6, "31.6mA": 7, "100mA": 8}
                            if htr_range in range_map:
                                ls.write(f"HTRRNG {range_map[htr_range]}")
                    ramp_desc = f"Ramp On ({ramp_rate_mk:.1f} mK/min)" if ramp_en else "Ramp Off"
                    msg = f"✓ Applied to Lake Shore 370: P={p}, I={i:.1f}s, D={d:.1f}s | R={r:.1f}Ω | Range={htr_range} | {ramp_desc}"
                else:
                    msg = "✓ Settings saved to profile (Instrument offline)"
                self.sig_pid_status.emit(msg)
            except Exception as ex:
                err_msg = f"⚠️ Error applying settings: {ex}"
                self.sig_pid_status.emit(err_msg)

        threading.Thread(target=_do_apply, daemon=True).start()

    def read_pid_from_instrument(self):
        """Query registers directly from the Lake Shore 370 and populate the UI controls."""
        self.lbl_pid_status.setText("Querying Lake Shore 370 registers (PID?, CSET?, RAMP?, HTRRNG?)...")

        def _do_read():
            try:
                st = getattr(self.world, "station", None) if hasattr(self, "world") else None
                ls = getattr(st, "ls370", None) if st else None
                if not ls:
                    self.sig_pid_status.emit("Lake Shore 370 instrument not available.")
                    return

                pid_raw = ls.ask("PID?").strip()
                import time
                time.sleep(0.15)
                cset_raw = ls.ask("CSET?").strip()
                time.sleep(0.15)
                ramp_raw = ls.ask("RAMP?").strip()
                time.sleep(0.15)
                htrrng_raw = ls.ask("HTRRNG?").strip()

                pid_parts = [float(x.strip()) for x in pid_raw.split(",") if x.strip()]
                cset_parts = [x.strip() for x in cset_raw.split(",") if x.strip()]
                ramp_parts = [x.strip() for x in ramp_raw.split(",") if x.strip()]
                range_code = int(htrrng_raw) if htrrng_raw.isdigit() else 2

                inv_ranges = {0: "off", 1: "31.6uA", 2: "100uA", 3: "316uA", 4: "1mA", 5: "3.16mA", 6: "10mA", 7: "31.6mA", 8: "100mA"}
                range_str = inv_ranges.get(range_code, "100uA")
                # A stale CMODE 4 write leaves HTRRNG? at 0/"off" while the PID keeps running. Don't put
                # "off" into the form (a later Apply would write it): use the commanded / configured range.
                if range_str == "off":
                    rc = getattr(ls, "heater", None)
                    try:
                        running = bool(rc.closed_loop_active()) if rc is not None else False
                    except Exception:
                        running = False
                    if running:
                        range_str = (getattr(rc, "commanded_range", None)
                                     or self.gui_settings.get("pid_config", {}).get("heater_range")
                                     or _states_mod.REGULATION_DEFAULTS["heater_range"])

                self.sig_pid_read.emit({
                    "pid_parts": pid_parts,
                    "cset_parts": cset_parts,
                    "ramp_parts": ramp_parts,
                    "range_str": range_str,
                    "pid_raw": pid_raw,
                })
            except Exception as e:
                err = f"⚠️ Could not read from Lake Shore 370: {e}"
                self.sig_pid_status.emit(err)

        threading.Thread(target=_do_read, daemon=True).start()

    def reset_pid_defaults(self):
        """Restore the measured-best regulation settings for true CONTROL (states.REGULATION_DEFAULTS)."""
        d = _states_mod.REGULATION_DEFAULTS
        self.spin_pid_p.setValue(d["p"])
        self.spin_pid_i.setValue(d["i"])
        self.spin_pid_d.setValue(d["d"])
        self.spin_pid_r.setValue(d["heater_resistance"])
        self.spin_pid_channel.setValue(d["channel"])
        idx = self.combo_pid_limit.findData(d["heater_limit"])
        if idx >= 0:
            self.combo_pid_limit.setCurrentIndex(idx)
        self.combo_pid_range.setCurrentText(d["heater_range"])
        self.chk_pid_ramp_enable.setChecked(bool(d["ramp_enable"]))
        self.spin_pid_ramp_rate.setValue(d["ramp_rate_mk_min"])
        self.lbl_pid_status.setText(
            f"Reset to true-CONTROL defaults (P={d['p']}, I={d['i']:.0f}s, D={d['d']:.0f}, {d['heater_range']} range, "
            f"limit {d['heater_limit']}; ~25 uK rms at 60 mK on 11/17). Click 'Update and Apply Settings' to write.")
