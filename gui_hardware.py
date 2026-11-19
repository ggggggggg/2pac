"""
Heat switch and relay controls (with the relay-switch safety check).

Mixin for gui.MyApp (split out of gui.py, P1-12). Methods are unchanged; they use the
MyApp instance (self) and the shared names in gui_common.
"""
from gui_common import *  # noqa: F401,F403
from gui_common import _states_mod  # noqa: F401


class HardwareControlsMixin:

    # ------------- Heat Switches Control ---------------
    def _update_heatswitch_ui(self):
        if not hasattr(self, "btn_hs_pot") or not hasattr(self, "btn_hs_adr") or not hasattr(self, "btn_hs_charcoal"):
            return
        is_light = (self.theme == "light")
        switches = [
            ("pot", "Pot", self.btn_hs_pot),
            ("adr", "ADR", self.btn_hs_adr),
            ("charcoal", "Charcoal", self.btn_hs_charcoal),
        ]
        for key, name, btn in switches:
            st = self._hs_states.get(key, "CLOSED")
            if st == "CLOSED":
                # Lit = Closed (Conductive thermal link engaged)
                btn.setText(f"● {name}: CLOSED")
                if is_light:
                    btn.setStyleSheet(
                        "QPushButton {"
                        "  background-color: #16a34a;"
                        "  color: #ffffff;"
                        "  border: 1px solid #15803d;"
                        "  border-radius: 4px;"
                        "  font-weight: 700;"
                        "  font-size: 11px;"
                        "  padding: 6px 4px;"
                        "}"
                        "QPushButton:hover {"
                        "  background-color: #15803d;"
                        "}"
                    )
                else:
                    btn.setStyleSheet(
                        "QPushButton {"
                        "  background-color: #15803d;"
                        "  color: #f0fdf4;"
                        "  border: 1px solid #4ade80;"
                        "  border-radius: 4px;"
                        "  font-weight: 700;"
                        "  font-size: 11px;"
                        "  padding: 6px 4px;"
                        "}"
                        "QPushButton:hover {"
                        "  background-color: #16a34a;"
                        "}"
                    )
            elif st == "OPEN":
                # Unlit = Open (Thermally isolated)
                btn.setText(f"○ {name}: OPEN")
                if is_light:
                    btn.setStyleSheet(
                        "QPushButton {"
                        "  background-color: #f1f5f9;"
                        "  color: #64748b;"
                        "  border: 1px solid #cbd5e1;"
                        "  border-radius: 4px;"
                        "  font-weight: 600;"
                        "  font-size: 11px;"
                        "  padding: 6px 4px;"
                        "}"
                        "QPushButton:hover {"
                        "  background-color: #e2e8f0;"
                        "  color: #0f172a;"
                        "}"
                    )
                else:
                    btn.setStyleSheet(
                        "QPushButton {"
                        "  background-color: #1e293b;"
                        "  color: #94a3b8;"
                        "  border: 1px solid #334155;"
                        "  border-radius: 4px;"
                        "  font-weight: 600;"
                        "  font-size: 11px;"
                        "  padding: 6px 4px;"
                        "}"
                        "QPushButton:hover {"
                        "  background-color: #334155;"
                        "  color: #f8fafc;"
                        "}"
                    )
            else:
                # Unknown state
                btn.setText(f"❓ {name}: UNKNOWN")
                if is_light:
                    btn.setStyleSheet(
                        "QPushButton {"
                        "  background-color: #fef3c7;"
                        "  color: #92400e;"
                        "  border: 1px solid #f59e0b;"
                        "  border-radius: 4px;"
                        "  font-weight: 700;"
                        "  font-size: 11px;"
                        "  padding: 6px 4px;"
                        "}"
                        "QPushButton:hover {"
                        "  background-color: #fde68a;"
                        "}"
                    )
                else:
                    btn.setStyleSheet(
                        "QPushButton {"
                        "  background-color: #78350f;"
                        "  color: #fef3c7;"
                        "  border: 1px solid #d97706;"
                        "  border-radius: 4px;"
                        "  font-weight: 700;"
                        "  font-size: 11px;"
                        "  padding: 6px 4px;"
                        "}"
                        "QPushButton:hover {"
                        "  background-color: #92400e;"
                        "}"
                    )

    def is_script_running(self):
        """Returns True if an active procedure (not idle/wait_forever) is currently executing."""
        if hasattr(self, "data_thread") and self.data_thread and self.data_thread.state:
            cur_name = self.data_thread.state.name()
            if cur_name and cur_name not in (IDLE_STATE, "wait_forever"):
                return True
        return getattr(self, "current_badge_state", "idle") in ("running", "paused")

    def on_heatswitch_clicked(self, switch_key, display_label, bypass_confirm=False):
        """
        Operator clicked a heat switch button. Toggles between OPEN and CLOSED.
        If a procedure is running or magnet is energized, requires explicit confirmation.
        """
        current_state = self._hs_states.get(switch_key, "CLOSED")
        target_state = "OPEN" if current_state == "CLOSED" else "CLOSED"

        mag_I = abs(getattr(self, "_latest_magnet_current", 0.0))
        if switch_key == "adr" and mag_I > _states_mod.MAGNET_ENERGIZED_A and not bypass_confirm:
            reply = QMessageBox.warning(
                self,
                "⚠️ High Magnet Current — ADR Heat Switch Warning",
                f"DANGER: Magnet current is currently elevated at {mag_I:.3f} A!\n\n"
                f"Toggling the ADR heat switch while magnet current is flowing can cause severe "
                f"thermal shock, rapid stage heating, or a magnet quench.\n\n"
                f"Are you absolutely certain you want to toggle the ADR heat switch to {target_state}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        elif not bypass_confirm and self.is_script_running():
            cur_script = (
                state_label(self.data_thread.state.name())
                if (self.data_thread and self.data_thread.state)
                else "Active Procedure"
            )
            action_word = "OPEN" if target_state == "OPEN" else "CLOSE"
            consequence = (
                "Opening this switch breaks thermal contact and thermally isolates the stage."
                if target_state == "OPEN" else
                "Closing this switch establishes a direct thermal conduction path."
            )
            msg = (
                f"⚠️ Active Procedure Running: '{cur_script}'\n\n"
                f"Do you really want to {action_word} the {display_label} heat switch?\n\n"
                f"{consequence}\n\n"
                f"Warning: Manually overriding heat switches during an active cycle "
                f"can disrupt the temperature profile or cooldown process."
            )
            reply = QMessageBox.question(
                self,
                f"Confirm Heat Switch Override — {display_label}",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.set_heatswitch_state(switch_key, target_state)

    def set_heatswitch_state(self, switch_key, target_state):
        """Update switch state, refresh UI button immediately, and pulse physical relay."""
        if switch_key in self._hs_pulsing:
            print(f"[HeatSwitch] {switch_key} is currently pulsing, ignoring duplicate trigger.")
            return

        self._hs_states[switch_key] = target_state
        self._update_heatswitch_ui()

        # Update QCoDeS parameter cache immediately for instant telemetry reflection
        param_name = f"heatswitch_{switch_key}"
        if hasattr(self.world, "station") and hasattr(self.world.station, "labjack"):
            param = getattr(self.world.station.labjack, param_name, None)
            if param and hasattr(param, "cache"):
                param.cache.set(target_state)

        # Pulse hardware latching relay in background daemon thread
        def _pulse_hardware():
            self._hs_pulsing.add(switch_key)
            try:
                if hasattr(self.world, "station") and hasattr(self.world.station, "labjack"):
                    param = getattr(self.world.station.labjack, param_name, None)
                    if param:
                        param(target_state)
                        print(f"[HeatSwitch] Physical pulse executed: {param_name} -> {target_state}")
            except Exception as e:
                print(f"[HeatSwitch] Error pulsing hardware relay for {switch_key}: {e}")
            finally:
                self._hs_pulsing.discard(switch_key)

        threading.Thread(target=_pulse_hardware, daemon=True).start()

        # Persist updated switch state to disk
        from daily_logger import save_hardware_state
        try:
            cur_state = self.current_selected_state_key() or IDLE_STATE
            save_hardware_state(
                magnet_current=abs(getattr(self, "_latest_magnet_current", 0.0)),
                he3_pressure=getattr(self, "_latest_he3_pressure", 0.0),
                active_procedure=cur_state,
                phase_name=getattr(self.world, "current_phase", "Holding steady"),
                heatswitches=self._hs_states,
                relay=self._cached_relay_state(),
            )
        except Exception:
            pass

    def sync_heatswitch_states_from_hardware(self):
        """Synchronize button states if an automated procedure modifies them in the background."""
        changed = False
        for key in ("pot", "adr", "charcoal"):
            param_name = f"heatswitch_{key}"
            if hasattr(self.world, "station") and hasattr(self.world.station, "labjack"):
                param = getattr(self.world.station.labjack, param_name, None)
                if param:
                    val = str(param.cache.get() if hasattr(param, "cache") else (param.raw_value if hasattr(param, "raw_value") else ""))
                    if val in ("OPEN", "CLOSED") and val != self._hs_states.get(key):
                        self._hs_states[key] = val
                        changed = True
        if changed:
            self._update_heatswitch_ui()

    def _switch_relay_mode_direct(self, mode: str):
        """Directly pulse latching relay to CONTROL (Pin 18) or RAMP (Pin 16) with safety checks."""
        st = getattr(self.world, "station", None)
        lj = getattr(st, "labjack", None) if st else None
        if not lj or not hasattr(lj, "relay"):
            QMessageBox.information(self, "Relay Control", "LabJack relay instrument is not available.")
            return

        reason = self._relay_switch_blocked_reason()
        if reason:
            QMessageBox.warning(self, "Relay Safety Lockout", reason)
            return

        def _do_switch():
            try:
                print(f"[Relay Control] Pulsing LabJack latching relay to {mode}...")
                lj.relay(mode)
                print(f"[Relay Control] Finished pulsing latching relay to {mode}.")
                self.sig_pid_status.emit(f"✓ Relay switched to {mode} mode")
                from daily_logger import save_hardware_state
                cur_state = self.current_selected_state_key() or IDLE_STATE
                save_hardware_state(
                    magnet_current=abs(getattr(self, "_latest_magnet_current", 0.0)),
                    he3_pressure=getattr(self, "_latest_he3_pressure", 0.0),
                    active_procedure=cur_state,
                    phase_name=getattr(self.world, "current_phase", "Holding steady"),
                    heatswitches=self._hs_states,
                    relay=mode
                )
            except Exception as ex:
                print(f"[Relay Control] Error switching relay to {mode}: {ex}")
                self.sig_pid_status.emit(f"⚠️ Error switching relay: {ex}")

        threading.Thread(target=_do_switch, daemon=True).start()

    def _relay_switch_blocked_reason(self):
        """
        The 12 Ohm resistor sits in parallel with the relay contact: RAMP closes the contact (shorts it),
        CONTROL opens it (all current through 12 Ohm + wiring). The Kepco is voltage-programmed, so:
        - CONTROL -> RAMP with output applied: R drops 12 -> 0.12 Ohm and the magnet current climbs toward
          V/0.12 Ohm (~8 A from a 1 V regulation output) over a few hundred seconds.
        - RAMP -> CONTROL at field: the contact opens and the magnet current is forced through 12 Ohm / the
          Dale resistor (fast discharge, voltage spike).
        So the relay may only switch with ~no current AND the LS370 output at ~0 %.
        Returns a message if switching is unsafe now, else None.
        """
        cur_mag_i = abs(getattr(self, "_latest_magnet_current", 0.0))
        if cur_mag_i > _states_mod.RELAY_SWITCH_MAX_A:
            return (f"Cannot switch the relay while {cur_mag_i:.3f} A flows in the magnet circuit "
                    f"(limit {_states_mod.RELAY_SWITCH_MAX_A*1000:.0f} mA).\n\n"
                    f"Bring the current to zero first: 'Ramp Down Magnet' (RAMP), or stop regulation and set the "
                    f"LS370 output to 0 % (CONTROL).")
        try:
            htr = float(_states_mod.most_recent_measurements().get("ls370_heater_out", float("nan")))
        except Exception:
            htr = float("nan")
        if not np.isfinite(htr) or htr > 0.5:
            return (f"Cannot switch the relay while the LS370 output is {htr:.1f} % (must be ~0 %).\n\n"
                    "The Kepco is voltage-programmed: switching CONTROL -> RAMP with output applied shorts the "
                    "12 Ohm resistor and the magnet current climbs toward ~8 A. Stop regulation / ramp down and "
                    "set the output to 0 % first.")
        return None

    def _on_relay_tile_clicked(self, event=None):
        """Allow user to toggle or switch latching relay between CONTROL and RAMP with confirmation."""
        st = getattr(self.world, "station", None)
        lj = getattr(st, "labjack", None) if st else None
        if not lj or not hasattr(lj, "relay"):
            QMessageBox.information(self, "Relay Control", "LabJack relay instrument is not available.")
            return

        # Safety check: never pulse the latching relay with current flowing (2026-11-16 it switched at 0.081 A)
        cur_mag_i = abs(getattr(self, "_latest_magnet_current", 0.0))
        if cur_mag_i > _states_mod.RELAY_SWITCH_MAX_A:
            QMessageBox.warning(
                self,
                "Relay Safety Lockout",
                f"Cannot switch the relay while {cur_mag_i:.3f} A flows in the magnet circuit "
                f"(limit {_states_mod.RELAY_SWITCH_MAX_A*1000:.0f} mA).\n\n"
                f"Bring the current to zero first: 'Ramp Down Magnet' (RAMP), or stop regulation and set the "
                f"LS370 output to 0 % (CONTROL)."
            )
            return

        cur_rel = "UNKNOWN"
        try:
            cur_rel = str(lj.relay.cache.get() or "UNKNOWN").upper()
        except Exception:
            pass

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Switch Latching Relay Mode")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setText(
            f"<h3>Latching Relay Hardware Mode</h3>"
            f"The latching relay is currently set to: <b>{cur_rel}</b>.<br><br>"
            f"Select which hardware latching coil to pulse:<br><br>"
            f"The 12 Ω resistor is in parallel with the relay contact; the LS370 always programs the Kepco.<br><br>"
            f"• <b>CONTROL (Pin 18 / CIO2)</b>: contact OPEN, all magnet current flows through 12 Ω + wiring (~12 Ω total). "
            f"~100× less current per % output: used for FAA temperature regulation.<br>"
            f"• <b>RAMP (Pin 16 / CIO0)</b>: contact CLOSED, 12 Ω shorted (~0.12 Ω wiring). Used for full-field magnet ramps.<br><br>"
            f"Only switch with ~0 A and the LS370 output at 0 %.<br>"
        )
        btn_control = msg_box.addButton("Switch to CONTROL", QMessageBox.ActionRole)
        btn_ramp = msg_box.addButton("Switch to RAMP", QMessageBox.ActionRole)
        btn_cancel = msg_box.addButton("Cancel", QMessageBox.RejectRole)
        if cur_rel == "CONTROL":
            msg_box.setDefaultButton(btn_ramp)
        else:
            msg_box.setDefaultButton(btn_control)

        msg_box.exec_()
        clicked = msg_box.clickedButton()
        if clicked == btn_control:
            target_rel = "CONTROL"
        elif clicked == btn_ramp:
            target_rel = "RAMP"
        else:
            return

        self._switch_relay_mode_direct(target_rel)
