# 2PAC: Fixes to Make After the 2026-11-16 Cycle, and the Hand-off Checklist

Written 2026-11-16 during a live He-3 + ADR cycle. **Do not edit code while a cycle is running.**
The GUI holds its code in memory, so edits only take effect after a restart, and a restart is safe
only in Idle or Regulate. Work through P0 before the next magnet cycle.

---

## Status 2026-11-18: implemented (verify on the next cycle)

Implemented while cold and regulating at 60 mK (GUI closed; the LS370 kept regulating on its own).
Fake-instrument tests: `.venv/bin/python tests/test_state_machine.py` (16 pass).

| Item | Status | Where |
|---|---|---|
| P0-1 readback during ramps | Scheduler floor back to 0.1 s; LS370 driver enforces 0.15 s after writes / 0.05 s after queries under its lock | `engine/world.py`, `instruments/lakeshore370_base.py` |
| P0-2 lag-aware ramp guard | `MagnetRampGuard`: τ-lagged expectation (`magnet_tau_s` 250), low after 60 s, high after 3 s, elapsed time not iterations | `states.py` |
| P0-3 ramp down without readback | Starts from last commanded output → HTR? (3 tries) → I/(A per %); holds + banner if unknown at field; A/s rate; relay only at < 10 mA | `states.ramp_down_magnet` |
| P0-4 launch criterion | FAA < `launch_temp_k` **and** \|dT/dt\| ≤ `launch_max_rate_mk_min` (1) over 5 min; `launch_timeout_h` (4) → banner + confirm; dwell default 1 min | `states.he3_adr_cycle` |
| P0-5 full field | `magnet_max_hout` 59.2 %, `MAGNET_AMPS_PER_PCT` = 9.33/58.1 | `states.py` (saved settings already 59.2) |
| P0-6 hard-coded PID | Hot update writes only SETP; regulation uses `pid_config` with `REGULATION_DEFAULTS` (P 7, I 80, 10 mA, limit 7) | `gui.py`, `states.py` |
| P0-7 setpoint vs base | FAA minimum tracked during demag settle; banner if setpoint < min + 2 mK | `states.he3_adr_cycle` |
| P0-8 commit | see git log on `test-avi` | |
| P1-1 wait guard | `world.wait()` raises if called twice without a yield | `engine/world.py` |
| P1-2 @state transform | AST-based (multi-line statements OK); old text transform kept as `_legacy` | `engine/imperative_statemachine.py` |
| P1-3 tests | `tests/test_state_machine.py` (lag, nan readback, launch, adopt, relay current, guard) | |
| P1-4 alerting | Banners/errors/watchdog → `alerts.py` (webhook / ntfy, configure `alerts` in gui_settings.json; off until set). Watchdog: no update > 60 s, NaN > 5 min | `alerts.py`, `gui.py` |
| P1-5 bounded waits | Pre-cool (`precool_timeout_h`), launch, demag settle, He-3-only base, autocool (48 h): banner, keep holding | `states.py` |
| P1-6 config | GUI defaults come from `states.DEFAULT_ADR_CONFIG` / `REGULATION_DEFAULTS`; each run writes `~/2pac_logs/<date>/config_<proc>_<time>.json` | |
| P1-7 legacy modules | Moved to `legacy/` with README | |
| P1-8 desktop scripts | Loader refuses scripts that drive the magnet/relay; exporter deprecated. `custom_scripts/he3_*.txt` still in the repo (now clean; `git rm` them, the loader refuses them anyway) | `engine/custom_script_loader.py` |
| P1-9 command channel | `~/.2pac/ipc` (mode 700); `query_ls370` (read-only) and validated `set_pid`; `exec:` only with Expert Mode + `PAC2_ALLOW_EXEC=1` | `gui.py`, `pid_autotuner.py` |
| P1-9b front panel "off" | **Not a readback quirk** (found 11/19). The old Stop button wrote `CMODE 4`: on this unit that sets CMODE?/HTRRNG? and the front panel to "off" but the PID output keeps running. Stop no longer writes CMODE 4 (asks: keep regulating / output 0 %); `mode("off")` raises; mode/range writes are read back; Regulate re-writes stale registers on adopt and every 5 min; GUI polls `loop_status()` every 30 s (red relay tile + banner). Re-writing HTRRNG is bumpless; re-writing CMODE 1 resets the integrator (~2 mK dip once) | `instruments/lakeshore370.py`, `states.sync_ls370_loop_registers`, `gui.py` |
| P1-10 thresholds | `MAGNET_ENERGIZED_A` 0.2, `CONTROL_MAX_A` 0.6, `RELAY_SWITCH_MAX_A` 0.01 used by states and GUI; Kepco-V logic removed | |
| P1-11 docs | Kepco notes corrected; PID library true-CONTROL table; `docs/OPERATOR_RUNBOOK.md` | |
| P1-12 split gui.py | Done 11/19: `gui_common.py` (imports, constants, settings helpers) + mixins `gui_status`, `gui_utils_tab`, `gui_hardware`, `gui_ipc`, `gui_plot_interaction`; methods moved verbatim (checked), offscreen smoke test with fakes | `gui*.py` |
| P1-13 wiring R | Utils row `RAMP [ ] CONTROL [ ] ☐ Modify? [Measure]`; inductive V plotted on the Utils Kepco V axis | `gui.py`, `plot_utils.py` |
| 2b relay V/I check | During ramp (I > 1 A) and regulation (I > 30 mA) | `states.relay_vi_mismatch` |
| 2c settle / starved output | Relay switches only at < 10 mA everywhere; banner if output > 20 % for 10 min with < 10 mA | |

Also fixed on the way:
- `instruments/lakeshore370.py` CSET group hard-coded heater limit 4 (1 mA): now read-modify-write.
- GUI close always saved relay = CONTROL, and wrote its stale in-memory `pid_config` over the file (P 3.5/I 60
  replaced the applied P 7/I 80 on 11/18). Close now saves the cached relay and merges geometry into the file.
- "Read from Instrument" no longer loads the bogus "off" range while the loop runs (a later Apply would have
  switched the heater off).
- `regulate_temperature` adopts a running loop after a GUI restart (no relay pulse, no zeroing, writes only differences).

---

## 0. Context: what happened on 2026-11-16

- 09:38: He-3 + ADR cycle started with the **Kepco off**. Stopped 09:46 at 7.5 % output; magnet stayed at 0 A.
- Review found three problems (fixed in the working tree, **not committed**, see section 3):
  1. `wait_for_precool_temperature()` looped on `world.wait()` inside a plain helper. Waits only take effect
     at the `yield`s that `@state` inserts into the state's own source, so the helper spun forever:
     telemetry stopped and Stop could not interrupt it. Latent this morning because Ch C was already < 3.2 K.
  2. `regulate_temperature` writes `CSET … limit 2` (100 µA regulation profile), and the cycle asked for the
     `10mA` range without raising the limit. The LS370 likely caps the range at the limit, so the magnet
     would have reached ~1 % of full field.
  3. Nothing checked that the magnet current follows the command (Kepco off went unnoticed).
- 10:01: GUI restarted with the fixes; cycle restarted (3K start point temporarily 5 K, since restored to 3.2 K).
- First full-field ramp on the **10 mA range with the 100 Ω shunt: 58.1 % → 9.25–9.42 A** (peak 9.42 A at 11:11).
- 13:32: launch began. 15:59: FAA reached 1.0 K and the ADR heat switch opened → **FAA jumped 1.00 → 1.77 K**.
  Demag started ~16:05.

### Measurements worth keeping

| Quantity | Value | Notes |
|---|---|---|
| Magnet current at 58.1 % (10 mA range, 100 Ω shunt) | 9.25–9.42 A | 10/14 (pre-shunt, 100 µA range): 9.57 A |
| Kepco output voltage at full field | 1.12–1.13 V | flat while current drifts ±1 % |
| Magnet-circuit lag (first-order fit, ramp-up) | τ ≈ 250–300 s | current trails the command |
| Implied lead resistance | ≈ 0.12 Ω | V/I at plateau |
| ADR heat switch opening, FAA jump | 10/14: 1.00 → 1.43 K; 11/16: 1.00 → 1.77 K | then flat within ~40 s |
| Base after demag from 1.43 K (10/14) | 46–50 mK | expect ~60 mK from 1.77 K |

The Kepco behaves as **voltage-programmed**: current = V_out / R_leads, which explains both the lag
(L/R) and the ±1 % drift at constant command.

---

## 1. P0: fix before the next magnet cycle

### P0-1 Heater-output readback fails during every ramp
- **Symptom:** the `out` log reads `nan` on ~100 % of samples while the output is being stepped (ramp-up after
  10:06:45, demag); 0 % during the 5 h hold; 0 % on 10/14. Telemetry slows from 2.0 s to 5.5 s per sample.
- **Likely cause:** uncommitted change in `engine/world.py` `process_command_and_decide_execution()`. The
  minimum sleep before a telemetry update dropped from `max(0.1, …)` to `max(0.01, …)`. Updates take ~2 s,
  longer than the 1 s target, so the floor always applies, and `HTR?` lands ~10 ms after the `MOUT` write. The
  LS370 misses it, the read times out (~3.5 s), and the next tick is late again, so it stays locked in.
  Unexplained: the first 5 min of the ramp failed only ~15 %.
- **Fix:** restore a ≥ 0.1 s floor (keep the 0.5 s cap for responsiveness), and/or sleep ~0.1–0.2 s after each
  LS370 write. Better: give `LakeshoreModel370` a lock and post-write delay like `LabjackU3._io_lock`, because
  GUI threads (PID read/apply, hot update) also talk to the LS370 concurrently with the state thread.
- **Verify:** on the next ramp, the `out` log shows no `nan`, and samples come every 1–2 s.

### P0-2 Ramp-tracking check must account for the magnet lag
- `magnet_ramp_fault()` (states.py) compares the measured current to `hout × 9.5/58.1` with no lag. With
  τ ≈ 250 s, the measured/expected ratio at 3 % output was ~0.30–0.33, right at the 0.3 trip threshold.
  It nearly aborted a healthy ramp, and **Resume at Magnet Ramp** would hit the same condition.
- **Fix:** compare against a lagged expectation (first-order filter of the command with τ ≈ 250 s,
  configurable), or only judge "low" once `hout` has been above ~5 % for > 2τ. Keep the "high" check
  unfiltered (it must trip fast). Also: the fault counter counts loop iterations, not seconds, so use elapsed
  time instead. Re-run the simulation (section 4) with a lag in the fake Kepco.

### P0-3 Make Ramp Down Magnet independent of LS370 readback
- `ramp_down_magnet` starts from `rc.mode()` and `rc.out()` read back from the LS370.
  - A failed read (the P0-1 situation) raises, and the procedure drops to Idle with the magnet held at field.
  - A `nan` or wrong `mode` reply takes the branch that sets the output to 0 **immediately**. From full field
    that is an abrupt discharge.
- **Fix:**
  - Start from the last *commanded* output (track it in `world`), falling back to measured current ÷
    (9.5/58.1). Never step to 0 when the measured current is > 0.2 A.
  - Retry reads; if they still fail, hold and raise an operator banner.
  - Express the ramp rate in A/s from the measured current.

### P0-4 Launch criterion: open the ADR switch only when the pill has cooled
- The FAA jump after opening is mostly the thermometer settling to the **pill's real temperature**, not heat
  from the switch. Evidence: on 10/14 the FAA read 1.0 K while the pot was at 0.40 K across a closed switch,
  and the jump was larger today, when the system was further from equilibrium.
- **Fix** (new `adr_config` keys, defaults in `DEFAULT_ADR_CONFIG` and the GUI):
  - `launch_max_rate_mk_min` (≈1): require |dT/dt| of the FAA below this, in addition to `launch_temp_k`,
    with `launch_timeout_h` as a backstop.
  - Consider `launch_temp_k` 0.6–0.7 K (the pot reaches ~0.4 K).
  - `launch_dwell_min` → 0–1. After opening, the pill warms ~10 mK/min at full field and that is not recovered.
    Keep a short dwell only if the switch needs time to come apart mechanically.
- The `while faa >= launch_temp_k` loop also has **no timeout** today (2.5 h on 11/16). Add one, plus a banner.

### P0-5 Full-field calibration
- 58.1 % now gives ~9.3 A. Set `magnet_max_hout` ≈ **59.2 %** for 9.5 A. Expect ±1 % drift with lead
  temperature (voltage-mode Kepco). Update `MAGNET_AMPS_PER_PCT` / docs to match.

### P0-6 Hard-coded PID/CSET in the GUI live-update path
- `gui.py` `hot_update_params()` (~line 3592): when regulating but the cached LS370 mode isn't `closed`
  (e.g. right after a GUI restart), it writes `CSET 4,…,6,100` and `PID 0.05, 12, 0`. That overwrites the tuned
  100 µA profile (P=1.2, I=280, limit 2). Use `pid_config` from settings, as `regulate_temperature` does.

### P0-7 Regulation setpoint vs. achievable base
- After a demag from 1.77 K, base is ~60 mK, so a 50 mK setpoint just pins the heater at 0 %.
- Consider: after the demag, record the minimum FAA over ~10 min and warn (banner) if the setpoint is below
  it plus a margin.

### P0-8 Commit the working tree
- Branch `test-avi` carries large uncommitted changes (states.py, gui.py, engine/world.py, docs, new
  pid_autotuner.py). Commit in logical pieces *after* P0-1 (the scheduler change needs to be fixed or reverted
  in the same commit), so there is a known-good revision to hand off.

---

## 2. P1: robustness for hand-off

1. **Guard against waits that silently do nothing.** Make `World.wait()` raise if it is not called from a
   running `@state` generator (check the calling frame, or set a flag in `state_runner`). The 11/16 deadlock
   class then fails loudly in testing instead of hanging a cooldown.
2. **`@state` transform limitations.** It inserts a `yield` after every physical line, so multi-line
   statements (wrapped call arguments) are a SyntaxError at import. Either document this prominently in
   `states.py` or rewrite the transform with `ast` (insert yields after each statement node).
3. **Automated tests.** Move the fake-instrument simulation into `tests/` (pytest) and run it before every
   commit. It covers Kepco off, LS370 limit clamp, missing shunt, 3K too warm, the full cycle from 4.1 K, and
   resume. Add: magnet lag (τ), readback `nan` during ramps, the launch criterion, and ramp-down from nan.
4. **Unattended-run alerting.** Banners only help if someone is at the screen. Add a remote alert (email or
   chat webhook) for: state error → Idle, operator action required, telemetry stale > N s, He-3 interlock.
   Also add a telemetry watchdog (FAA/Kepco readings unchanged or `nan` for minutes).
5. **Bounded waits everywhere.** Pre-cool, FAA < launch, and demag settle should all have timeouts that
   raise a banner and hold safely (never an abrupt output change).
6. **One source of truth for config.** Defaults live in `states.DEFAULT_ADR_CONFIG`, the `gui.py` defaults
   (~line 136), and `~/2pac_logs/gui_settings.json`. Saved GUI values silently override code defaults (e.g.
   flange setpoint 45 K saved vs. 65 K default). Log the full effective config at the start of every cycle.
7. **Remove duplicate and legacy modules.** The live path is `main.py` → `engine/`, `instruments/`. Root-level
   `world.py`, `imperative_statemachine.py`, `custom_script_loader.py`, `lakeshore370.py`,
   `station_2pac.py`, `world_no_mpl.py`, `log_data.py` and `older/` duplicate or diverge from it (e.g.
   `world.py` ≠ `engine/world.py`). Delete or clearly mark them legacy.
8. **Desktop custom scripts drift from the built-ins.** `custom_scripts/*.txt` and
   `export_states_to_desktop.py` hold copies of the cycle without today's fixes (no CSET limit, no ramp
   check). Built-ins take precedence by name, but a renamed copy would run the old logic. Generate them from
   `states.py` or drop them.
9. **External command channel (security, high priority).** `/tmp/2pac_gui_command.txt` accepts `exec: <python>`
   and runs it inside the GUI with the live instrument station (`gui.py` `_check_external_commands`). It can
   also switch procedures with `bypass_confirm=True` and toggle heat switches. Anything that can write to
   `/tmp` gets arbitrary code execution on the cryostat controller. `pid_autotuner.py` depends on `exec:`.
   Replace it with a small set of named, validated commands (e.g. `set_pid p i d`, `query_ls370`) in a
   user-owned directory (mode 700), and disable it unless Expert Mode is on.
9b. **LS370 `HTRRNG?` reads 0 ("off") in closed loop** (11/17, three consecutive queries) while the output is
   live (65.8 % → 0.107 A, i.e. the 10 mA range). In open loop on 11/16 the readback was correct (the ramp
   check passed). Don't trust `HTRRNG?` in closed loop. Track the commanded range in software, and check the
   ramp check's readback is done in open loop (it is today).
10. **Unify safety thresholds.** Magnet-energized limits differ: GUI start check 0.2 A, regulation button
    0.5 A, `check_magnet_deenergized` 0.2/0.6 A depending on Kepco V. Note that with the Kepco off,
    `kepco_voltage` reads ~0.89 V (offset), which flips that logic. Use one constant.
11. **Docs.** `docs/KEPCO_SHUNT_AND_PID_NOTES.md` has contradictions: relay routing still says "10 kΩ unshunted
    on 2PAC", and CONTROL is described both as "isolates the Kepco" and "scales sensitivity 10×". Add the
    measurements table from section 0. Write a one-page operator runbook: Kepco ON check, what each banner
    means, how to Resume at Magnet Ramp, what is safe to touch mid-cycle (not Utilities → Apply/Read).
12. **gui.py is ~4,650 lines.** Lower priority: split the hardware-control actions (relay, heat switch, PID
    apply, hot update) out of the widget code so they can be tested without Qt.
13. **Wiring-resistance correction for the magnet voltage (user request, 2026-11-18).** The logged
    `labjack_kepco_voltage` is the Kepco output, i.e. `I·R_wiring + L·dI/dt`. Subtract the resistive part so
    the plot shows only the inductive voltage. That makes ramp rate, the end of a ramp, and quench/short
    signatures readable directly.
    - **GUI:** in the Utils tab (`_build_utils_tab`, `gui.py` ~line 2365), add a small "Wiring resistance (Ω)"
      spin box (default 0.000, resolution 0.001 Ω, range 0–50). Put a **"Modify?"** checkbox next to it. The
      box stays read-only until the checkbox is ticked, and unticking it locks the box again. Save the value in
      `gui_settings.json` (e.g. `magnet_config.wiring_r_ramp_ohm` / `wiring_r_control_ohm`) and log every
      change. The single box is replaced by the two-box row below.
    - **Derived channel:** `magnet_inductive_voltage = kepco_voltage − kepco_current · R_wiring`. Plot it
      next to "Kepco V" (`plot_utils.py` Utils subplot ~line 910, labels/colours ~lines 45/81/136). Keep the
      raw `kepco_voltage` log unchanged so the correction can be redone with a better R later.
    - **Relay-mode dependence (decided, 2026-11-18): two boxes, no clutter.** The series resistance differs
      by relay position: RAMP is ≈ 0.12 Ω total circuit (section 0), and CONTROL adds ~12 Ω (section 2b). Lay
      it out as one compact row in an existing Utils group, not a new group box:
      `Wiring R (Ω):  RAMP [0.120]  CONTROL [12.00]  ☐ Modify?`
      The two spin boxes share the one Modify? lock. Keep labels short and the spin boxes narrow (~70 px).
      Put details (formula, how to measure) in tooltips, not on-screen text. Pick the active value
      automatically from the relay state; if the relay is UNKNOWN, show the raw voltage only.
    - **Calibrating R:** at a constant current plateau (dI/dt = 0, e.g. the 9.3 A hold), `R = V/I`. Add a
      "Measure" button that does this from the last 60 s, active only when |dI/dt| is about 0. Note the
      ~0.89 V `kepco_voltage` offset seen with the Kepco off (item 10). Fit `V = V0 + I·R` across two
      plateaus, or subtract V0, otherwise R comes out wrong.
    - **Optional:** show the inferred inductance `L = V_ind / (dI/dt)` during ramps as a sanity check. Expected
      ≈ τ·R ≈ 250 s × 0.12 Ω ≈ 30 H. The ~10 Ω Dale resistor in parallel with the magnet carries
      `V_ind/10 Ω`, which is small at normal ramp rates.

---

## 2b. What the RAMP/CONTROL relay actually switches (log analysis, 2026-11-16, corrected 19:10)

**In CONTROL the relay puts ~12 Ω in series with the magnet on the Kepco *output* side.** Mechanism (user, 2026-11-18): the 12 Ω is in parallel with the relay contact; RAMP closes the contact (12 Ω shorted), CONTROL opens it (all current through 12 Ω + wiring). Consequence: never switch with output applied (CONTROL → RAMP at ~1 V output would drive the magnet toward ~8 A); relay switching now requires |I| < 10 mA and LS370 output ≈ 0 % (procedures, Utils buttons and `set_relay:`). A ~10 Ω Dale
resistor is permanently in parallel with the magnet; since the magnet branch is ~0.12 Ω, the magnet still
carries almost all of the current. Evidence (steady CONTROL periods, Kepco V ÷ magnet current):

| Period | Relay | I | Kepco V | V/I |
|---|---|---|---|---|
| 10/14 evening | CONTROL | 0.163 A | 1.96 V | 12.0 Ω |
| 10/15 | CONTROL | 0.132 A | 1.58 V | 11.9 Ω |
| 10/16 evening | CONTROL (per software) | 0.096 A | 0.004 V | 0.04 Ω ← anomalous |
| 10/17 | CONTROL (per software) | 0.068 A | 0.001 V | 0.01 Ω ← anomalous |
| 11/16 19:00 | CONTROL | 0.102 A | 1.21 V | 11.9 Ω |
| RAMP, any day | RAMP | 9.3 A | 1.13 V | 0.12 Ω |

Consequences:
- CONTROL is ~100× less sensitive than RAMP because the circuit resistance goes from 0.12 Ω to ~12 Ω. Before
  the shunt: RAMP 164,700 A/A vs CONTROL 1,600 A/A (ratio 103). The Kepco notes' "10×" is wrong.
- The L/R time constant drops from ~250 s (RAMP) to ~2.5 s (CONTROL). That's why the current falls in seconds
  at each relay switch. This is normal, not a disconnection.
- The 12 Ω caps CONTROL current: Kepco output of a few V gives only a few hundred mA. No 10 A runaway risk.
- The programming side (LS370 → [100 Ω shunt ∥ Kepco input ~10 kΩ]) is the same in both positions. So after
  the shunt, real CONTROL gives ≈ 1,606 / 100 ≈ **15.6 A/A**. Measured 11/16 on 31.6 mA: 0.081 A at 17 %
  (5.4 mA) = 15 A/A. ✓
- **10/16–10/18 were anomalous:** CONTROL behaved like RAMP (no 12 Ω), most likely because the latching relay
  stayed physically in RAMP after the 10/16 shunt work while software logged CONTROL. **The 100 µA PID tuning
  (P 1.2, I 280; PID library #3/#4) was done in that state** and is ~120× too weak for real CONTROL.
- The relay has no position feedback. Add a check: after switching, apply a small output and confirm V/I ≈ 12 Ω
  (CONTROL) or ≈ 0.12 Ω with slow rise (RAMP); raise a banner on mismatch.

Regulation settings for real CONTROL (100 Ω shunt installed):

| Range | Full-scale magnet I | CSET limit | Use |
|---|---|---|---|
| 10 mA | ≈ 0.16 A | 6 | Only for setpoints just above base. 60 mK right after demag needs ~0.13–0.15 A (85–95 %, near saturation). |
| 31.6 mA | ≈ 0.49 A | 7 | **Use this** for 55–70 mK. |

**Tuning for real CONTROL (11/16 evening attempts):**

| Segment | Settings | Result |
|---|---|---|
| 18:57–19:04 | 31.6 mA, P 1.2, I 280 | FAA rose only ~0.2 mK/min toward 60 mK |
| 19:10–19:16 | 10 mA, P 1.5, I 280 | Output 10 → 31 % (0.05 A); FAA still fell 56.4 → 54.5 mK |

- The **I ≥ 200 s rule in the PID library comes from the stuck-relay period** (RAMP-like 250 s magnet lag).
  Real CONTROL lag is ~2.5 s.
- Measured plant: ~0.07 A → +2.7 mK within ~40 s. On 31.6 mA, 1 % ≈ 5 mA ≈ 0.2 mK. LS370 proportional:
  ≈ 1.8·P % per mK of error (from the 19:10 step).
- Starting point: **31.6 mA, limit 7, P 2–3, I ≈ 60 s, D 0, setpoint ramp off or ~1 mK/min.** Then re-tune with
  `pid_autotuner.py` and record the results in the PID library as "true CONTROL (12 Ω series)".
- `ramp_down_magnet` from closed loop zeroes the output instantly (harmless in CONTROL thanks to the 12 Ω,
  but see P0-3).

Update `pid_config` defaults, the PID library, and KEPCO_SHUNT_AND_PID_NOTES.md accordingly. To confirm the
12 Ω by meter (magnet at 0 A, Kepco off): ohmmeter across the Kepco output terminals in RAMP vs CONTROL.

### 2c. 2026-11-16 evening regulation episode (resolved: range/gain, not hardware)

- 17:40–18:47: regulating on 100 µA (limit 2) with the 10/17 gains, the output went to 100 % with ~0 A visible.
  In real CONTROL, 100 % of 100 µA ≈ 1.6 mA of magnet current, below the LabJack resolution. FAA drifted to
  54.4 mK (good demag; base lower than the ~60 mK estimate).
- 18:51: "10 mA" attempt still gave nothing, probably because the CSET limit was still code 2, clamping the
  range to 100 µA.
- 18:53+: 31.6 mA (limit 7) → 0.08–0.16 A, and the FAA responded (55.4 → 58.1 mK when I = 0.16 A; rising
  toward the 60 mK setpoint 18:59–19:04). Regulation works. It was stopped at 19:04:56 on my mistaken advice;
  restart it.
- I briefly misdiagnosed this as an open CONTROL contact, then as a disconnected magnet. Both were wrong; see 2b.
- The relay switched with **0.081 A** still in the magnet: the demag-settle fallback (`demag_settle_s + 900`
  with |I| < 0.10 A) fired. Tighten it to |I| < 0.01 A and never switch the relay with current flowing.
- Software follow-ups:
  - Regulation defaults for real CONTROL (table above). Remove `10mA`/limit-6 fallbacks that assume the
    anomalous gain.
  - Banner if output > ~20 % for > 10 min while |I| < 10 mA (wrong range/limit, or actuator not responding).
  - Log Kepco V/I and check it against the expected value for the relay position.

## 3. Already done in the working tree (2026-11-16, uncommitted)

- `states.py`:
  - `precool_poll_interval()` replaces the deadlocking helper; the wait loops now live in the state bodies
    (he3_adr_cycle, autocool_he3_adr, he3_only_cycle).
  - `prepare_ls370_for_magnet_ramp()`: open loop at 0 %, `CSET … limit 6`, `10mA` range, read back
    `HTRRNG?`/`CSET?`, raise if not confirmed.
  - `magnet_ramp_fault()` + guard in the ramp-up loop: "low" → ramp output back to 0; "high" → hold. The
    Cryo-con is left on in both cases. (Needs P0-2.)
  - New state `he3_adr_resume_at_ramp` (sets `world.resume_at_ramp` and hands off to `he3_adr_cycle`, skipping
    the heat-switch reset and 3.2 K gate; refuses if Ch C > 5 K).
- `gui.py`: label, description, Simple-mode entry and pre-flight dialog for the resume state.

## 4. Simulation harness

Replaced by `tests/test_state_machine.py` (2026-11-18): fake clock, fake LS370 (CSET-limit clamping and the
closed-loop CMODE?/HTRRNG? quirk), fake Kepco with τ = 250 s (RAMP) / 2.5 s (CONTROL), fake LabJack. Run with
`.venv/bin/python tests/test_state_machine.py` (no hardware access; also works under pytest if installed).
Run it after every change to `states.py` or `engine/`.
