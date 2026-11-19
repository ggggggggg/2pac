"""
Operator banners, remote alerts, telemetry watchdog, LS370 register check, status tiles and FAA RMS.

Mixin for gui.MyApp (split out of gui.py, P1-12). Methods are unchanged; they use the
MyApp instance (self) and the shared names in gui_common.
"""
from gui_common import *  # noqa: F401,F403
from gui_common import _states_mod  # noqa: F401


class StatusAlertsMixin:

    def show_operator_banner(self, text):
        self.lbl_operator_action.setText(text)
        self.operator_banner.setVisible(True)

    def dismiss_operator_banner(self):
        self.operator_banner.setVisible(False)

    def _on_operator_action(self, state_name, text):
        self.show_operator_banner(text)
        self._send_remote_alert(f"{state_label(state_name)}: {text}", key=f"banner:{text[:50]}")

    def _send_remote_alert(self, text, key=None):
        """Forward to alerts.send_alert (no-op unless an endpoint is set in gui_settings.json 'alerts')."""
        try:
            import alerts
            alerts.send_alert(text, key=key)
        except Exception as e:
            print(f"[alerts] not sent: {e}")

    def _check_telemetry_watchdog(self):
        """
        Telemetry watchdog (P1-4): the state thread updates world.last_update_time_s on every telemetry
        tick. If that stops for > 60 s (hung serial read, deadlocked procedure) or the FAA / Kepco
        readings are NaN for > 5 min, show a banner and send an alert. Runs on a GUI timer, so it still
        works when the state thread is stuck.
        """
        now = time.time()
        last = getattr(self.world, "last_update_time_s", None)
        stale_s = (now - last) if last else 0.0
        if stale_s > 60:
            if not getattr(self, "_watchdog_stale_flag", False):
                self._watchdog_stale_flag = True
                msg = f"⚠️ Telemetry stalled: no instrument update for {stale_s:.0f} s (state: {getattr(self.world, 'current_phase', '?')}). The procedure may be hung on a serial read."
                self.show_operator_banner(msg)
                self._send_remote_alert(msg, key="watchdog_stale")
        else:
            self._watchdog_stale_flag = False
        try:
            mr = _states_mod.most_recent_measurements()
            bad = [k for k in ("faa_temperature", "labjack_kepco_current") if k in mr and not np.isfinite(mr[k])]
        except Exception:
            bad = []
        if bad:
            self._watchdog_nan_since = getattr(self, "_watchdog_nan_since", None) or now
            if now - self._watchdog_nan_since > 300 and not getattr(self, "_watchdog_nan_flag", False):
                self._watchdog_nan_flag = True
                msg = f"⚠️ Telemetry: {', '.join(bad)} reading NaN for > 5 min. Check the instrument connection."
                self.show_operator_banner(msg)
                self._send_remote_alert(msg, key="watchdog_nan")
        else:
            self._watchdog_nan_since = None
            self._watchdog_nan_flag = False
        self._check_ls370_loop_registers(now)

    def _check_ls370_loop_registers(self, now):
        """
        Every 30 s read the LS370 loop registers on a worker thread (rc.loop_status()). If the PID is driving the
        output while CMODE?/HTRRNG? (= the front panel) say otherwise, banner + alert once. That state came from the
        old Stop button writing CMODE 4, which blanks the front panel without stopping the output.
        """
        st = getattr(self, "_ls370_loop", None)
        if st and st.get("stale"):
            if not getattr(self, "_ls370_stale_flag", False):
                self._ls370_stale_flag = True
                dt = getattr(self, "data_thread", None)
                is_reg = bool(dt and dt.state and dt.state.name() == "regulate_temperature")
                msg = (f"⚠️ LS370 front panel says mode {st.get('mode')}, range {st.get('range')}, but its PID is driving the "
                       f"output ({st.get('htr', float('nan')):.1f} %). "
                       + ("Regulation re-writes the registers within 5 min." if is_reg else
                          "Press Regulate: it adopts the running loop and fixes the front panel without disturbing it."))
                self.show_operator_banner(msg)
                self._send_remote_alert(msg, key="ls370_stale_regs")
        else:
            self._ls370_stale_flag = False
        if now - getattr(self, "_ls370_loop_t", 0.0) < 30 or getattr(self, "_ls370_poll_busy", False):
            return
        rc = getattr(getattr(getattr(self.world, "station", None), "ls370", None), "heater", None)
        if rc is None or not hasattr(rc, "loop_status"):
            return
        self._ls370_loop_t = now
        self._ls370_poll_busy = True

        def _poll():
            try:
                self._ls370_loop = dict(rc.loop_status(), t=time.time())
            except Exception as e:
                print(f"[LS370] loop status poll failed: {e}")
            finally:
                self._ls370_poll_busy = False
        threading.Thread(target=_poll, daemon=True).start()

    def _on_procedure_finished(self, state_name):
        self._set_status_badge("IDLE", "idle")
        idx = self.combo_box.findData(IDLE_STATE)
        if idx >= 0:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(idx)
            self.combo_box.blockSignals(False)
        self.lbl_script_name.setText(f"Active Script: {state_label(IDLE_STATE)}")

    def _on_procedure_error(self, state_name, err_msg):
        self._set_status_badge("ERROR", "error")
        idx = self.combo_box.findData(IDLE_STATE)
        if idx >= 0:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(idx)
            self.combo_box.blockSignals(False)
        self.lbl_script_name.setText(f"Active Script: {state_label(IDLE_STATE)}")
        mag_I = abs(getattr(self, "_latest_magnet_current", 0.0))
        if mag_I > _states_mod.MAGNET_ENERGIZED_A:
            self.show_operator_banner(
                f"⚠️ Error in {state_label(state_name)}: {err_msg}. "
                f"WARNING: Magnet current is held at {mag_I:.3f} A! Run 'Ramp Down Magnet' to de-energize safely."
            )
        else:
            self.show_operator_banner(f"⚠️ Error in {state_label(state_name)}: {err_msg}. Reverted safely to Idle.")
        self._send_remote_alert(f"ERROR in {state_label(state_name)}: {err_msg} (magnet {mag_I:.3f} A). Now Idle.", key=f"error:{state_name}")


    def _compute_faa_window_rms_uk(self):
        """Compute FAA temperature RMS (standard deviation around mean, in uK) for the currently displayed time window."""
        dataset = self.historical_dataset if self.displaying_historical else self.live_dataset
        if dataset is None or not hasattr(dataset, "cache"):
            return None
        try:
            data = dataset.cache.data()
            if not data or "time" not in data or "time" not in data["time"]:
                return None
            t = data["time"]["time"]
            if len(t) < 2:
                return None

            faa_arr = None
            for k in ("faa_temperature", "faa"):
                if k in data and k in data[k] and len(data[k][k]) > 0:
                    faa_arr = data[k][k]
                    break
            if faa_arr is None or len(faa_arr) < 2:
                return None

            n = min(len(t), len(faa_arr))
            t = np.asarray(t[:n], dtype=float)
            faa_arr = np.asarray(faa_arr[:n], dtype=float)

            x0, x1 = None, None
            if self.user_has_zoomed and self.axes_list:
                try:
                    xlim = self.axes_list[0].get_xlim()
                    if xlim[0] < xlim[1]:
                        x0, x1 = float(xlim[0]), float(xlim[1])
                except Exception:
                    pass

            if x0 is None or x1 is None:
                tw_str = str(self.time_window or "6 Hours").lower()
                if self.displaying_historical or "all" in tw_str:
                    x0, x1 = float(t[0]), float(t[-1])
                else:
                    if "15" in tw_str or "min" in tw_str:
                        window_s = 900.0
                    elif "month" in tw_str or "30" in tw_str:
                        window_s = 30.0 * 86400.0
                    elif "week" in tw_str or "7" in tw_str:
                        window_s = 7.0 * 86400.0
                    elif "day" in tw_str or "24" in tw_str:
                        window_s = 86400.0
                    elif "1" in tw_str and "hour" in tw_str:
                        window_s = 3600.0
                    elif "6" in tw_str and "hour" in tw_str:
                        window_s = 21600.0
                    else:
                        window_s = 21600.0
                    x1 = float(t[-1])
                    x0 = x1 - window_s

            i0 = int(np.searchsorted(t, x0, side="left"))
            i1 = int(np.searchsorted(t, x1, side="right"))
            if i1 - i0 < 2:
                return None

            sub = faa_arr[i0:i1]
            valid = sub[np.isfinite(sub) & (sub > 0)]
            if len(valid) < 2:
                return None

            return float(np.std(valid)) * 1e6
        except Exception:
            return None

    def _update_faa_card_rms_title(self, control_engaged=None):
        """Update the FAA STAGE metric card title with (xx.x uK rms) when control is engaged."""
        if "faa_temperature" not in self.metric_tiles:
            return
        faa_spec = self.metric_tiles["faa_temperature"]
        if control_engaged is None:
            control_engaged = getattr(self, "_last_control_engaged", False)
        else:
            self._last_control_engaged = bool(control_engaged)

        if control_engaged:
            rms_uk = self._compute_faa_window_rms_uk()
            if rms_uk is not None and np.isfinite(rms_uk):
                faa_spec["lbl_t"].setText(f"FAA STAGE ({rms_uk:.1f} uK rms)")
                return
        faa_spec["lbl_t"].setText("FAA STAGE")

    # ------------- Dual-Row Status Bar ---------------
    def _format_val(self, key, val, units):
        alias = display_name(key)
        unit = units.get(key, "")
        if isinstance(val, (int, float)):
            if np.isnan(val):
                return f"{alias}: NaN"
            if "vac" in key.lower() or "torr" in str(unit).lower() or "torr" in key.lower():
                if val < 0.1:
                    return f"{alias}: {val*1000.0:.2f} mTorr"
                elif val < 10.0:
                    return f"{alias}: {val:.3f} Torr"
                else:
                    return f"{alias}: {val:.2f} Torr"
            if "temp" in key.lower() or str(unit).upper() == "K":
                return f"{alias}: {format_cryo_temp(val)}"
            if "current" in key.lower() or str(unit).upper() == "A":
                return f"{alias}: {format_magnet_current(val)}"
            return f"{alias}: {val:.3f} {unit}".strip()
        return f"{alias}: {val}"

    def _update_latest_status(self, data_mr, units, keys):
        if not data_mr:
            self.lbl_latest_vals.setText("LATEST  Waiting for telemetry...")
            return

        is_light = (self.theme == "light")
        key_fallbacks = {
            "cryocon_chB_temperature": ["cryocon_chB_temperature", "chB_temperature", "chB", "charcoal"],
            "cryocon_chC_temperature": ["cryocon_chC_temperature", "chC_temperature", "chC", "4k_flange", "4k"],
            "cryocon_chD_temperature": ["cryocon_chD_temperature", "chD_temperature", "chD", "pot"],
            "cryocon_chA_temperature": ["cryocon_chA_temperature", "chA_temperature", "chA", "60k_flange", "60k", "40k_flange", "40k"],
            "faa_temperature": ["faa_temperature", "faa"],
            "labjack_he3_pressure": ["labjack_he3_pressure", "he3_pressure"],
            "labjack_kepco_current": ["labjack_kepco_current", "kepco_current"],
        }
        for key, spec in self.metric_tiles.items():
            if key == "relay_heater_status":
                continue
            raw_val = None
            for candidate in key_fallbacks.get(key, [key]):
                if candidate in data_mr:
                    raw_val = data_mr[candidate]
                    break
            if raw_val is not None:
                val = float(raw_val) if isinstance(raw_val, (int, float)) and np.isfinite(raw_val) else None

                if key in ("faa_temperature", "cryocon_chD_temperature", "cryocon_chC_temperature", "cryocon_chB_temperature"):
                    if val is not None:
                        spec["val"].setText(format_cryo_temp(val))
                    else:
                        spec["val"].setText("NaN")
                elif key == "labjack_he3_pressure":
                    if val is not None:
                        spec["val"].setText(f"{val:.2f} bar")
                    else:
                        spec["val"].setText("—")
                elif key == "labjack_kepco_current":
                    if val is not None:
                        spec["val"].setText(format_magnet_current(val))
                        self._latest_magnet_current = val
                    else:
                        spec["val"].setText("0.0 mA")
                        self._latest_magnet_current = 0.0

                # Visual watchdogs and solid theme styling
                acc = spec["accent"]
                card_style = None
                val_style = None

                if key == "labjack_he3_pressure" and val is not None and val > 9.5:
                    card_style = "QFrame#metric_tile { background-color: #991b1b; border: 2px solid #ef4444; border-radius: 6px; }"
                    val_style = "color: #ffffff; font-weight: 800; font-size: 18px; background: transparent;"
                elif key == "labjack_he3_pressure" and val is not None and val > 9.0:
                    card_style = "QFrame#metric_tile { background-color: #b45309; border: 2px solid #f59e0b; border-radius: 6px; }"
                    val_style = "color: #ffffff; font-weight: 800; font-size: 18px; background: transparent;"
                elif key == "labjack_kepco_current" and val is not None and abs(val) > 0.5:
                    card_style = f"QFrame#metric_tile {{ background-color: {acc}; border: 2px solid #38bdf8; border-radius: 6px; }}"
                    val_style = "color: #ffffff; font-weight: 800; font-size: 18px; background: transparent;"
                else:
                    card_style = f"QFrame#metric_tile {{ background-color: {acc}; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.18); }}"
                    val_style = "color: #ffffff; font-weight: 800; font-size: 18px; background: transparent;"

                if card_style:
                    spec["card"].setStyleSheet(card_style)
                if val_style:
                    spec["val"].setStyleSheet(val_style)
                if "lbl_t" in spec:
                    spec["lbl_t"].setStyleSheet("color: rgba(255, 255, 255, 0.92); font-weight: 700; font-size: 11px; background: transparent;")

        # Update Grey Relay State & Heater Status Card
        if "relay_heater_status" in self.metric_tiles:
            spec = self.metric_tiles["relay_heater_status"]
            rel_val = None
            if hasattr(self.world, "station") and hasattr(self.world.station, "labjack") and self.world.station.labjack:
                try:
                    rel_val = self.world.station.labjack.relay.cache.get()
                except Exception:
                    pass
            if not rel_val or rel_val == "UNKNOWN":
                rel_val = data_mr.get("labjack_relay")
            if not rel_val or rel_val == "UNKNOWN":
                rel_val = "CONTROL"
            rel_str = str(rel_val).upper()

            htr_pct = 0.0
            if "ls370_heater_out" in data_mr and data_mr["ls370_heater_out"] is not None:
                try:
                    htr_pct = float(data_mr["ls370_heater_out"])
                except Exception:
                    pass

            rc = None
            if hasattr(self.world, "station") and hasattr(self.world.station, "ls370") and self.world.station.ls370:
                rc = getattr(self.world.station.ls370, "heater", None)

            mode_name = "Closed loop" if rel_str == "CONTROL" else "Open loop"
            sp_disp = None
            loop_stale = False
            if rc:
                try:
                    # Show what the LS370 itself reports (= its front panel), polled every 30 s.
                    lst = getattr(self, "_ls370_loop", None)
                    if lst and time.time() - lst.get("t", 0) < 120:
                        m, r = str(lst.get("mode", "")), str(lst.get("range", ""))
                        loop_stale = bool(lst.get("stale"))
                    else:
                        m = str(getattr(rc, "commanded_mode", None) or "").lower()
                        r = str(getattr(rc, "commanded_range", None) or "").lower()
                    sp = rc.setpoint.cache.get()
                    if loop_stale:
                        mode_name = "PID running, LS370 panel says OFF"
                    elif r == "off":
                        mode_name = "OFF"
                    elif "closed" in m:
                        mode_name = "Closed loop"
                    elif "open" in m:
                        mode_name = "Open loop"
                    if sp is not None:
                        sp_k = float(sp)
                        sp_disp = f"{sp_k*1000.0:.1f} mK" if sp_k < 1.0 else f"{sp_k:.3f} K"
                except Exception:
                    pass

            spec["lbl_t"].setText(f"RELAY STATE: {rel_str}")
            sp_txt = f", SP {sp_disp}" if (sp_disp and mode_name.startswith(("Closed loop", "PID running"))) else ""
            spec["val"].setText(f"output {htr_pct:.2f}% ({mode_name}{sp_txt})")
            card_bg = "#b91c1c" if loop_stale else "#475569"
            card_style = f"QFrame#metric_tile {{ background-color: {card_bg}; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.18); }}"
            val_style = "color: #ffffff; font-weight: 700; font-size: 12px; background: transparent;"
            spec["card"].setStyleSheet(card_style)
            spec["val"].setStyleSheet(val_style)
            spec["lbl_t"].setStyleSheet("color: rgba(255, 255, 255, 0.92); font-weight: 700; font-size: 11px; background: transparent;")
            if hasattr(self, "lbl_relay_mode_status"):
                self.lbl_relay_mode_status.setText(f"State: {rel_str}")

            dt = getattr(self, "data_thread", None)
            is_reg_state = bool(dt and getattr(dt, "state", None) and dt.state.name() == "regulate_temperature")
            control_engaged = (rel_str == "CONTROL") and (is_reg_state or mode_name == "Closed loop" or htr_pct > 0.0)
            self._update_faa_card_rms_title(control_engaged=control_engaged)

        shown_keys = [k for k in PRIMARY_STATUS_KEYS if k in data_mr]
        other_keys = [k for k in keys if k in data_mr and k not in PRIMARY_STATUS_KEYS and k not in ("time", "elapsed_time")]
        all_status_keys = shown_keys + other_keys[:3]

        parts = [self._format_val(k, data_mr[k], units) for k in all_status_keys]
        self.lbl_latest_vals.setText("LATEST   " + "   │   ".join(parts))

    def _update_cursor_status(self):
        event = self.on_mouse_move_event
        if event is None or not event.inaxes or event.xdata is None:
            self.lbl_cursor_vals.setText("CURSOR  [Hover over plot to inspect point]")
            return

        dataset = self.historical_dataset if self.displaying_historical else self.live_dataset
        if dataset is None:
            return

        try:
            data = dataset.cache.data()
            if not data or "time" not in data or "time" not in data["time"]:
                return
            t = data["time"]["time"]
            if len(t) == 0:
                return
            # Fast O(log N) binary search with zero array allocations
            xloc_ind = int(np.searchsorted(t, event.xdata))
            if xloc_ind >= len(t):
                xloc_ind = len(t) - 1
            elif xloc_ind > 0 and abs(t[xloc_ind - 1] - event.xdata) < abs(t[xloc_ind] - event.xdata):
                xloc_ind = xloc_ind - 1

            from plot_utils import get_dataset_units, epoch_to_local_str
            units = get_dataset_units(dataset)

            shown_keys = [k for k in PRIMARY_STATUS_KEYS if k in data]
            other_keys = [k for k in data.keys() if k not in PRIMARY_STATUS_KEYS and k not in ("time", "elapsed_time")]
            all_status_keys = shown_keys + other_keys[:3]

            parts = []
            t_str = epoch_to_local_str(t[xloc_ind], include_seconds=True)
            parts.append(f"t={t_str}")
            for key in all_status_keys:
                if key in data and key in data[key] and len(data[key][key]) > xloc_ind:
                    val = data[key][key][xloc_ind]
                    parts.append(self._format_val(key, val, units))
            self.lbl_cursor_vals.setText("CURSOR   " + "   │   ".join(parts))
        except Exception:
            pass
