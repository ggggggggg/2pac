"""
Private command channel (~/.2pac/ipc/gui_command.txt): validated named commands, read-only LS370 queries.

Mixin for gui.MyApp (split out of gui.py, P1-12). Methods are unchanged; they use the
MyApp instance (self) and the shared names in gui_common.
"""
from gui_common import *  # noqa: F401,F403
from gui_common import _states_mod  # noqa: F401


class IpcCommandsMixin:

    # ------------- State Control ---------------
    def _check_external_commands(self):
        # Private command channel (P1-9): ~/.2pac/ipc (mode 700), not world-writable /tmp.
        cmd_file = IPC_DIR / "gui_command.txt"
        if not cmd_file.exists():
            return
        try:
            content = cmd_file.read_text().strip()
            cmd_file.unlink()
            if not content:
                return
            for cmd in content.splitlines():
                cmd = cmd.strip()
                if not cmd:
                    continue
                if cmd.startswith("switch_state:"):
                    name = cmd.split("switch_state:")[1].strip()
                    found_key = None
                    for k in self.states_dict:
                        if k.lower() == name.lower() or state_label(k).lower() == name.lower():
                            found_key = k
                            break
                    if found_key:
                        idx = self.combo_box.findData(found_key)
                        if idx >= 0:
                            self.combo_box.setCurrentIndex(idx)
                            self.on_combo_changed(idx)
                        self.request_state_change(bypass_confirm=True)
                elif cmd.startswith("select_state:"):
                    name = cmd.split("select_state:")[1].strip()
                    found_key = None
                    for k in self.states_dict:
                        if k.lower() == name.lower() or state_label(k).lower() == name.lower():
                            found_key = k
                            break
                    if found_key:
                        idx = self.combo_box.findData(found_key)
                        if idx >= 0:
                            self.combo_box.setCurrentIndex(idx)
                elif cmd.startswith("select_tab:"):
                    tab_name = cmd.split("select_tab:")[1].strip()
                    for i in range(self.main_tabs.count()):
                        if tab_name.lower() in self.main_tabs.tabText(i).lower():
                            self.main_tabs.setCurrentIndex(i)
                            break
                elif cmd.startswith("mode:"):
                    m = cmd.split("mode:")[1].strip().lower()
                    if m in ("simple", "0", "false"):
                        self.toggle_expert_mode(False)
                    elif m in ("expert", "1", "true"):
                        self.toggle_expert_mode(True)
                elif cmd.startswith("view:"):
                    v_name = cmd.split("view:")[1].strip()
                    if hasattr(self, 'plot_view_tabs'):
                        for i in range(self.plot_view_tabs.count()):
                            if v_name.lower() in self.plot_view_tabs.tabText(i).lower():
                                self.plot_view_tabs.setCurrentIndex(i)
                                break
                elif cmd.startswith("range:"):
                    r_name = cmd.split("range:")[1].strip().lower()
                    target_text = None
                    if "month" in r_name or "30" in r_name:
                        target_text = "1 Month"
                    elif "week" in r_name or "7" in r_name:
                        target_text = "1 Week"
                    elif "day" in r_name or "24" in r_name:
                        target_text = "1 Day"
                    elif "1" in r_name and "hour" in r_name:
                        target_text = "1 Hour"
                    elif "6" in r_name and "hour" in r_name:
                        target_text = "6 Hours"

                    if target_text:
                        for i in range(self.combo_time_window.count()):
                            if self.combo_time_window.itemText(i) == target_text:
                                self.combo_time_window.setCurrentIndex(i)
                                break
                    else:
                        for i in range(self.combo_time_window.count()):
                            if r_name in self.combo_time_window.itemText(i).lower():
                                self.combo_time_window.setCurrentIndex(i)
                                break
                elif cmd == "pause":
                    self.toggle_pause()
                elif cmd == "stop":
                    self.stop_state(bypass_confirm=True)
                elif cmd == "dismiss_banner":
                    self.dismiss_operator_banner()
                elif cmd.startswith("operator_action:"):
                    act_txt = cmd.split("operator_action:")[1].strip()
                    self._on_operator_action("procedure", act_txt)
                elif cmd.startswith("subkelvin:"):
                    val = cmd.split("subkelvin:")[1].strip().lower() in ("true", "1", "yes")
                    self.btn_subkelvin_filter.setChecked(val)
                    self.toggle_subkelvin_filter()
                elif cmd == "snapshot":
                    self.export_plot_snapshot(bypass_popup=True)
                elif cmd.startswith("theme:"):
                    new_theme = cmd.split("theme:")[1].strip()
                    if new_theme in ("light", "dark"):
                        self.theme = new_theme
                        self.apply_theme()
                elif cmd.startswith("toggle_heatswitch:"):
                    hs_key = cmd.split("toggle_heatswitch:")[1].strip().lower()
                    lbl = {"pot": "Pot", "adr": "ADR", "charcoal": "Charcoal"}.get(hs_key, hs_key.upper())
                    self.on_heatswitch_clicked(hs_key, lbl, bypass_confirm=True)
                elif cmd.startswith("click_heatswitch:"):
                    hs_key = cmd.split("click_heatswitch:")[1].strip().lower()
                    lbl = {"pot": "Pot", "adr": "ADR", "charcoal": "Charcoal"}.get(hs_key, hs_key.upper())
                    self.on_heatswitch_clicked(hs_key, lbl, bypass_confirm=False)
                elif cmd.startswith("set_heatswitch:"):
                    parts = cmd.split("set_heatswitch:")[1].strip().split(":")
                    if len(parts) == 2:
                        hs_key = parts[0].strip().lower()
                        val = parts[1].strip().upper()
                        if val in ("OPEN", "CLOSED"):
                            self.set_heatswitch_state(hs_key, val)
                elif cmd.startswith("regulate:"):
                    temp_str = cmd.split("regulate:")[1].strip()
                    try:
                        self.spin_reg_temp.setValue(float(temp_str))
                        self.start_or_update_regulation()
                    except Exception as e:
                        print(f"Error executing external regulate command: {e}")
                elif cmd == "regulate":
                    self.start_or_update_regulation()
                elif cmd in ("update", "update_params", "hot_update"):
                    self.hot_update_params(bypass_popup=True)
                elif cmd == "reset_adr_params":
                    self.reset_default_adr_params()
                elif cmd.startswith("set_relay:"):
                    rel_target = cmd.split("set_relay:")[1].strip().upper()
                    reason = self._relay_switch_blocked_reason()
                    if rel_target not in ("RAMP", "CONTROL") or reason:
                        print(f"[EXTERNAL CMD] set_relay:{rel_target} refused: {reason or 'unknown target'}")
                    elif hasattr(self.world, "station") and hasattr(self.world.station, "labjack"):
                        self.world.station.labjack.relay(rel_target)
                elif cmd.startswith("exec:"):
                    # Arbitrary code execution: only in Expert Mode AND with PAC2_ALLOW_EXEC=1 set when the
                    # GUI was started. Use query_ls370 / set_pid instead.
                    if not (self.expert_mode and os.environ.get("PAC2_ALLOW_EXEC") == "1"):
                        print("[EXTERNAL CMD] exec: refused (needs Expert Mode and PAC2_ALLOW_EXEC=1).")
                        continue
                    py_code = cmd.split("exec:", 1)[1].strip()
                    print(f"[EXTERNAL CMD] exec: {py_code[:200]}")
                    try:
                        exec(py_code, {"self": self, "world": self.world, "st": getattr(self.world, "station", None)})
                    except Exception as exc:
                        print(f"[EXEC ERROR] {exc}")
                elif cmd.startswith("query_ls370"):
                    # Read-only LS370 queries. "query_ls370" alone = standard set; "query_ls370:PID?,FILTER? 4".
                    qs = cmd.split(":", 1)[1].split(",") if ":" in cmd else list(LS370_STANDARD_QUERIES)
                    threading.Thread(target=self._ipc_query_ls370, args=([q.strip() for q in qs if q.strip()],), daemon=True).start()
                elif cmd.startswith("set_pid:"):
                    self._ipc_set_pid(cmd.split("set_pid:", 1)[1])
                elif cmd.startswith("set_adr_param:"):
                    parts = cmd.split("set_adr_param:")[1].strip().split(":")
                    if len(parts) == 2:
                        pk, pv = parts[0].strip(), float(parts[1].strip())
                        spin_map = {
                            "charcoal_heat_sp": getattr(self, "spin_charcoal_sp", None),
                            "flange_60k_heat_sp": getattr(self, "spin_flange_sp", None),
                            "starting_temp_3k": getattr(self, "spin_starting_temp_3k", getattr(self, "spin_pot_precool", None)),
                            "pot_precool_limit_k": getattr(self, "spin_starting_temp_3k", getattr(self, "spin_pot_precool", None)),
                            "launch_temp_k": getattr(self, "spin_launch_temp", None),
                            "launch_dwell_min": getattr(self, "spin_launch_dwell", None),
                            "he3_condense_dwell_h": getattr(self, "spin_condense_dwell", None),
                            "magnet_max_hout": getattr(self, "spin_mag_max_hout", None),
                            "magnet_ramp_up_min": getattr(self, "spin_mag_ramp_up", None),
                            "magnet_ramp_down_min": getattr(self, "spin_mag_ramp_down", None),
                            "demag_settle_min": getattr(self, "spin_demag_settle", None),
                            "regulate_temp_k": getattr(self, "spin_reg_temp", None),
                        }
                        sp = spin_map.get(pk)
                        if sp is not None:
                            sp.setValue(pv)
                elif cmd in ("resync_ls370", "flush_ls370"):
                    try:
                        if hasattr(self, "world") and hasattr(self.world, "station") and self.world.station:
                            st = self.world.station
                            if hasattr(st, "ls370") and hasattr(st.ls370, "visa_handle"):
                                vh = st.ls370.visa_handle
                                if hasattr(vh, "flush"):
                                    import pyvisa.constants as pv_const
                                    vh.flush(pv_const.VI_READ_BUF_DISCARD)
                                elif hasattr(vh, "read_raw"):
                                    vh.read_raw()
                                print("[EXTERNAL CMD] Flushed LS370 VISA read buffer.")
                    except Exception as fe:
                        print(f"Error flushing LS370: {fe}")
                elif cmd.startswith("scroll_sidebar:"):
                    s_val = cmd.split("scroll_sidebar:")[1].strip()
                    if hasattr(self, "sidebar_scroll") and self.sidebar_scroll:
                        vsb = self.sidebar_scroll.verticalScrollBar()
                        if s_val == "bottom":
                            vsb.setValue(vsb.maximum())
                        elif s_val == "top":
                            vsb.setValue(0)
                        else:
                            try:
                                vsb.setValue(int(s_val))
                            except Exception:
                                pass
                elif cmd.startswith("screenshot:"):
                    shot_path = cmd.split("screenshot:")[1].strip()
                    try:
                        self.grab().save(shot_path)
                        print(f"Direct widget screenshot saved to {shot_path}")
                    except Exception as se:
                        print(f"Error saving screenshot: {se}")
        except Exception as e:
            print(f"Error handling external command: {e}")

    def _ipc_query_ls370(self, queries):
        """Run read-only LS370 queries (each must end in '?') and write JSON to ~/.2pac/ipc/ls370_state.json."""
        out = {"time": time.time()}
        ls = getattr(getattr(self.world, "station", None), "ls370", None)
        for q in queries:
            if not re.fullmatch(r"[A-Z*]{2,8}\?( ?[0-9]{1,2})?", q):
                out[q] = "REFUSED (not a read-only query)"
                continue
            try:
                out[q] = ls.ask(q).strip() if ls else "no LS370"
            except Exception as e:
                out[q] = f"ERR {e}"
        rc = getattr(ls, "heater", None)
        out["commanded_mode"] = getattr(rc, "commanded_mode", None)
        out["commanded_range"] = getattr(rc, "commanded_range", None)
        try:
            tmp = IPC_DIR / "ls370_state.json.tmp"
            tmp.write_text(json.dumps(out))
            tmp.replace(IPC_DIR / "ls370_state.json")
        except Exception as e:
            print(f"[EXTERNAL CMD] query_ls370 write failed: {e}")

    def _ipc_set_pid(self, arg):
        """set_pid:P,I,D[,RANGE] with validation; updates the Utils controls and pid_config, then writes PID (and HTRRNG)."""
        try:
            parts = [x.strip() for x in arg.split(",")]
            p, i, d = float(parts[0]), float(parts[1]), float(parts[2])
            rng = parts[3] if len(parts) > 3 else None
            if not (0.001 <= p <= 100 and 1.0 <= i <= 1000 and 0.0 <= d <= 200):
                raise ValueError(f"out of range P={p} I={i} D={d} (P 0.001-100, I 1-1000 s, D 0-200 s)")
            if rng is not None and rng not in ("10mA", "31.6mA", "3.16mA", "1mA"):
                raise ValueError(f"range {rng} not allowed for regulation")
        except Exception as e:
            print(f"[EXTERNAL CMD] set_pid refused: {e}")
            return
        self.spin_pid_p.setValue(p)
        self.spin_pid_i.setValue(i)
        self.spin_pid_d.setValue(d)
        pc = self.gui_settings.setdefault("pid_config", {})
        pc.update({"p": p, "i": i, "d": d})
        if rng:
            self.combo_pid_range.setCurrentText(rng)
            pc["heater_range"] = rng
        save_gui_settings(self.gui_settings)

        def _write():
            ls = getattr(getattr(self.world, "station", None), "ls370", None)
            if not ls:
                return
            ls.write(f"PID {p:.4f}, {i:.1f}, {d:.1f}")
            if rng:
                ls.heater.range(rng)
            print(f"[EXTERNAL CMD] set_pid applied P={p} I={i} D={d}" + (f" range={rng}" if rng else ""))
        threading.Thread(target=_write, daemon=True).start()
