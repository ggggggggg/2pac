import time
import numpy as np
import qcodes
import typing
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from engine import state, World

# Initialize globals to be populated by main.py
st = None
elapsed_time = None
datasaver_global = None
log_dir = None  # Set by main.py
ENABLE_TEXT_LOGGING = True

def _get_log_dir():
    """Get or create today's log directory."""
    global log_dir
    today = datetime.now().strftime("%Y-%m-%d")
    d = Path.home() / "2pac_logs" / today
    d.mkdir(parents=True, exist_ok=True)
    log_dir = d
    return d

_open_log_handles = {}
_current_log_day = None

def _log_to_file(results_list):
    """Append each channel value to its own .log file with persistent line-buffered file handles."""
    global _open_log_handles, _current_log_day
    d = _get_log_dir()
    today = d.name
    if today != _current_log_day:
        for h in _open_log_handles.values():
            try:
                h.close()
            except Exception:
                pass
        _open_log_handles.clear()
        _current_log_day = today

    now = time.time()
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in results_list:
        if isinstance(item, tuple) and len(item) == 2:
            param, value = item
            if isinstance(param, str):
                name = param
            else:
                name = getattr(param, 'name', str(param))
            
            handle = _open_log_handles.get(name)
            if handle is None or handle.closed:
                log_file = d / f"{name}.log"
                handle = open(log_file, "a", buffering=1, encoding="utf-8")
                _open_log_handles[name] = handle
            try:
                handle.write(f"{now},{local_time},{value}\n")
            except Exception:
                try:
                    log_file = d / f"{name}.log"
                    handle = open(log_file, "a", buffering=1, encoding="utf-8")
                    _open_log_handles[name] = handle
                    handle.write(f"{now},{local_time},{value}\n")
                except Exception:
                    pass

def retry(f, n=3):
    # try cryocon is being unreliable on returning temp, so try a few times then return nan
    for i in range(n):
        try:
            return f()
        except: 
            pass
    return np.nan

def update(datasaver, state):
    global st
    if st is None and hasattr(datasaver, "station") and datasaver.station is not None:
        st = datasaver.station
    if st is None:
        return
    ls370_out = retry(st.ls370.heater.out, n=1) if hasattr(st, "ls370") and st.ls370 is not None else np.nan
    faa_val = retry(st.ls370.ch04.temperature, n=2) if hasattr(st, "ls370") and st.ls370 is not None else np.nan

    # Auto-resync guard: detect if LS370 heater output (%) and FAA temperature (K) were swapped by serial FIFO collision
    if np.isfinite(faa_val) and np.isfinite(ls370_out):
        if faa_val > 20.0 and ls370_out < 2.0:
            faa_val, ls370_out = ls370_out, faa_val
            try:
                if hasattr(st, "ls370") and hasattr(st.ls370, "visa_handle"):
                    vh = st.ls370.visa_handle
                    if hasattr(vh, "flush"):
                        import pyvisa.constants as pv_const
                        vh.flush(pv_const.VI_READ_BUF_DISCARD)
                    elif hasattr(vh, "read_raw"):
                        vh.read_raw()
                    elif hasattr(vh, "read"):
                        vh.read()
            except Exception:
                pass

    cryo_params = [elapsed_time, st.cryocon.chA_temperature, st.cryocon.chB_temperature,
                   st.cryocon.chC_temperature, st.cryocon.chD_temperature,
                   st.labjack.kepco_current, st.labjack.kepco_voltage]
    lj_params = [st.labjack.relay, st.labjack.heatswitch_adr, st.labjack.heatswitch_charcoal,
                 st.labjack.heatswitch_pot, st.labjack.he3_pressure, st.labjack.vac_can_pressure_torr]

    l = [(param, retry(param, n=1)) for param in cryo_params] + [
        (st.ls370.heater.out, ls370_out),
    ] + [(param, retry(param, n=1)) for param in lj_params] + [
        ("state", state.name()),
        ("faa_temperature", faa_val),
        ("time", time.time())
    ]
    try:
        datasaver.add_result(*l)
    except Exception as e:
        print(f"Warning: datasaver.add_result error: {e}")
    if ENABLE_TEXT_LOGGING:
        try:
            _log_to_file(l)
        except Exception as e:
            print(f"Warning: _log_to_file error: {e}")

def most_recent_measurements():
    if datasaver_global is None:
        return {}
    try:
        data = datasaver_global.dataset.cache.data()
        ret = {}
        for key in data.keys():
            if key in data and key in data[key] and len(data[key][key]) > 0:
                v = data[key][key][-1]
                ret[key] = v
        return ret
    except Exception as e:
        print(f"Error reading recent measurements: {e}")
        return {}

def pretty_str_dict(d: dict):
    s = ""
    for key, value in d.items():
        s+= f"{key} {value}\n"
    return s

# Default ADR cycle and regulation configuration parameters
DEFAULT_ADR_CONFIG = {
    "charcoal_heat_sp": 55.0,        # Charcoal heater setpoint (K)
    "flange_60k_heat_sp": 65.0,      # 60K flange heater setpoint (K)
    "starting_temp_3k": 3.2,         # 3K stage starting temperature threshold (Channel C) before cycle starts (K)
    "pot_precool_limit_k": 3.2,      # Alias for starting_temp_3k
    "he3_condense_dwell_h": 3.5,     # Condensation dwell duration (hours)
    "launch_temp_k": 1.0,            # Launch temperature: FAA temp threshold before opening ADR heat switch and ramping down magnet (K)
    "launch_max_rate_mk_min": 1.0,   # ...and the FAA must have settled: |dT/dt| below this over the last 5 min (mK/min)
    "launch_timeout_h": 4.0,         # Backstop for the launch wait: banner + operator confirmation after this (h)
    "launch_dwell_min": 1.0,         # Post-ADR-switch-open dwell before ramping down (min). The pill warms at full field, so keep short.
    "magnet_max_hout": 59.2,         # LS370 open-loop output (%) at full field: 58.1 % gave 9.25-9.42 A on 11/16, so 59.2 % ~ 9.5 A
    "magnet_ramp_up_min": 45.0,      # Magnet ramp up duration (minutes)
    "magnet_ramp_down_min": 60.0,    # Magnet ramp down duration (minutes) - slower ramp avoids inductive lag and eddy heating
    "magnet_tau_s": 250.0,           # RAMP-circuit L/R lag of the magnet current behind the command (s), used by the ramp guard
    "demag_settle_min": 20.0,        # Post-demag current settle wait (minutes) before zero-current interlock check
    "precool_timeout_h": 12.0,       # Pre-cool (3K stage) wait: banner after this long (keeps waiting)
    "regulate_temp_mk": 60.0,        # Closed-loop PID regulation setpoint (mK). Base after demag from ~1.8 K is ~55-60 mK.
    "regulate_temp_k": 0.060,        # Closed-loop PID regulation setpoint (K)
}

def get_adr_config(world=None):
    """Retrieve active ADR configuration dict from world or defaults."""
    cfg = dict(DEFAULT_ADR_CONFIG)
    if world is not None and hasattr(world, "adr_config") and isinstance(world.adr_config, dict):
        cfg.update(world.adr_config)
    return cfg

def get_adr_regulation_setpoint(world=None):
    """
    Retrieve regulation setpoint in (Kelvin, mK) safely handling mK vs K formats.
    Guarantees target_k is strictly in Kelvin (e.g. 0.050) and target_mk is in mK (e.g. 50.0).
    """
    cfg = get_adr_config(world)
    if "regulate_temp_mk" in cfg:
        target_mk = float(cfg["regulate_temp_mk"])
        target_k = target_mk / 1000.0 if target_mk >= 1.0 else target_mk
        if target_mk < 1.0:
            target_mk = target_k * 1000.0
    elif "regulate_temp_k" in cfg:
        val = float(cfg["regulate_temp_k"])
        if val >= 1.0:  # Value was saved in mK (e.g. 50.0)
            target_mk = val
            target_k = val / 1000.0
        else:  # Value was saved in K (e.g. 0.050)
            target_k = val
            target_mk = val * 1000.0
    else:
        target_k = 0.050
        target_mk = 50.0
    return target_k, target_mk

# ---------------------------------------------------------------------------------------------
# Magnet / relay constants (single source of truth; gui.py imports these). See docs/POST_CYCLE_FIXES.md.
# ---------------------------------------------------------------------------------------------
MAGNET_FULL_FIELD_A = 9.5
MAGNET_MAX_HOUT = 59.2           # LS370 open-loop output (%) for ~9.5 A (10 mA range, 100 Ohm shunt)
MAGNET_RAMP_TIME_S = 30*60       # full-scale ramp duration (legacy)
# Magnet energized threshold (RAMP or unknown relay): refuse cycles / regulation / relay changes above this.
MAGNET_ENERGIZED_A = 0.2
MAGNET_START_LIMIT_A = MAGNET_ENERGIZED_A   # legacy name
# In CONTROL the relay puts ~12 Ohm in series, so the Kepco can push at most a few hundred mA.
CONTROL_MAX_A = 0.6
# Never pulse the latching relay with more than this flowing (2026-11-16 it switched at 0.081 A).
RELAY_SWITCH_MAX_A = 0.01
# Expected Kepco V/I by relay position (Ohm). The 12 Ohm resistor is wired in PARALLEL with the relay contact:
# RAMP = contact closed, 12 Ohm shorted -> ~0.12 Ohm (wiring); CONTROL = contact open -> 12 Ohm + wiring.
# The Kepco is voltage-programmed, so switching with output applied changes the current ~100x: always zero the
# LS370 output and wait for |I| < RELAY_SWITCH_MAX_A before pulsing the relay.
RELAY_R_OHM = {"RAMP": (0.0, 1.0), "CONTROL": (8.0, 16.0)}
# Closed-loop regulation defaults for true CONTROL (12 Ohm series), measured best on 2026-11-17:
# P 7, I 80 s, D 0 on the 10 mA range with CSET limit 7 -> ~25 uK rms at 60 mK.
REGULATION_DEFAULTS = {
    "p": 7.0, "i": 80.0, "d": 0.0,
    "heater_resistance": 100.0, "channel": 4,
    "heater_limit": 7, "heater_range": "10mA",
    "ramp_enable": False, "ramp_rate_mk_min": 10.0,
}


def _read_magnet(world):
    """(current A, voltage V) from the LabJack, NaN on failure."""
    lj = world.station.labjack
    try:
        mag_I = float(lj.kepco_current())
    except Exception:
        mag_I = float("nan")
    try:
        mag_V = float(lj.kepco_voltage())
    except Exception:
        mag_V = float("nan")
    return mag_I, mag_V


def _relay_cached(world):
    try:
        return world.station.labjack.relay.cache.get()
    except Exception:
        return None


def check_magnet_deenergized(world):
    """
    Raise if the magnet is (or may be) energized. NaN / read failure counts as unsafe.
    RAMP or unknown relay: |I| must be below MAGNET_ENERGIZED_A.
    CONTROL: the 12 Ohm series resistor caps the current, so up to CONTROL_MAX_A is normal (regulation);
    callers that switch the relay must still zero the output first (see wait_relay_switch_safe).
    """
    mag_I, _ = _read_magnet(world)
    if not np.isfinite(mag_I):
        raise RuntimeError("Refusing to start: cannot read magnet current.")
    limit = CONTROL_MAX_A if _relay_cached(world) == "CONTROL" else MAGNET_ENERGIZED_A
    if abs(mag_I) > limit:
        raise RuntimeError(
            f"Refusing to start: magnet current is {mag_I:.3f} A (limit {limit:.2f} A with relay "
            f"{_relay_cached(world)}). Run 'Ramp Down Magnet' first.")
    return mag_I


def relay_vi_mismatch(relay, volts, amps, min_amps=0.03):
    """
    Check Kepco V/I against the expected circuit resistance for the relay position (the relay has no
    position feedback). Returns a message if it doesn't match, else None. Needs |I| >= min_amps.
    """
    if relay not in RELAY_R_OHM or not (np.isfinite(volts) and np.isfinite(amps)) or abs(amps) < min_amps:
        return None
    r = abs(volts / amps)
    lo, hi = RELAY_R_OHM[relay]
    if lo <= r <= hi:
        return None
    return (f"Relay reported {relay} but Kepco V/I = {r:.2f} Ohm (expected {lo:g}-{hi:g} Ohm). "
            "The latching relay may not have switched. Check before ramping.")


def notify(world, message, key=None):
    """
    Banner for the operator (non-blocking). The GUI forwards every banner to alerts.send_alert()
    (remote alert, if configured), so it is not sent from here too.
    """
    try:
        world.request_operator_action(message)
    except Exception:
        print(message)


def log_effective_config(world, procedure):
    """Write the full effective config (adr_config with defaults filled in + pid_config) for this run."""
    try:
        import json
        eff = {"procedure": procedure, "time": datetime.now().isoformat(timespec="seconds"),
               "adr_config": get_adr_config(world), "pid_config": load_pid_config(),
               "relay_cached": _relay_cached(world)}
        p = _get_log_dir() / f"config_{procedure}_{datetime.now().strftime('%H%M%S')}.json"
        p.write_text(json.dumps(eff, indent=2, default=str))
        print(f"[{procedure}] effective config written to {p}")
    except Exception as e:
        print(f"[{procedure}] could not log effective config: {e}")


def faa_rate_mk_min(samples, window_s=300.0):
    """Least-squares slope (mK/min) of FAA temperature over the last window_s of (t, T_K) samples."""
    if len(samples) < 5:
        return None
    t_end = samples[-1][0]
    pts = [(t, T) for t, T in samples if t >= t_end - window_s and T is not None and np.isfinite(T)]
    if len(pts) < 5 or pts[-1][0] - pts[0][0] < 0.8 * window_s:
        return None
    t = np.array([p[0] for p in pts]); T = np.array([p[1] for p in pts])
    slope_k_s = np.polyfit(t - t[0], T, 1)[0]
    return float(slope_k_s * 1000.0 * 60.0)

MAX_HE3_PRESSURE_BAR = 9.5

@dataclass
class StationWorld(World):
    station: qcodes.station.Station = None
    datasaver: typing.Any = None
    adr_config: dict = None
    resume_at_ramp: bool = False  # set by he3_adr_resume_at_ramp, consumed by he3_adr_cycle
    last_commanded_hout: float = None  # last open-loop LS370 output (%) written by a procedure (for ramp_down_magnet)

    def __post_init__(self):
        if self.adr_config is None:
            self.adr_config = dict(DEFAULT_ADR_CONFIG)

    def update(self, state):
        update(self.datasaver, state)
        # Continuous hardware safety interlock: if He-3 pressure exceeds limit,
        # immediately cut Cryocon heaters and abort the procedure safely.
        if self.station and hasattr(self.station, "labjack"):
            try:
                p_param = getattr(self.station.labjack, "he3_pressure", None)
                if p_param:
                    p = p_param.cache.get()
                    if p is None:
                        p = float(p_param())
                    if p > MAX_HE3_PRESSURE_BAR:
                        if hasattr(self.station, "cryocon"):
                            try:
                                self.station.cryocon.control_enabled(False)
                            except Exception:
                                pass
                        raise RuntimeError(
                            f"CRITICAL SAFETY INTERLOCK: He-3 pressure reached {p:.2f} bar (exceeds {MAX_HE3_PRESSURE_BAR} bar limit)! "
                            "Cryocon heaters shut off immediately."
                        )
            except RuntimeError:
                raise
            except Exception:
                pass

def safe_set_heatswitch(world, hs_name: str, target_state: str):
    """Set heatswitch only if its cached state is not already target_state, avoiding redundant relay pulses."""
    try:
        if world and hasattr(world, "station") and hasattr(world.station, "labjack"):
            param = getattr(world.station.labjack, f"heatswitch_{hs_name}", None)
            if param is not None:
                cur = param.cache.get()
                if cur != target_state:
                    param(target_state)
    except Exception as e:
        print(f"Warning: safe_set_heatswitch({hs_name}, {target_state}) error: {e}")

def precool_poll_interval(world: StationWorld, limit_3k: float, phase_name: str = "Pre-cooling Check", step: int = 1, total_steps: int = 6):
    """
    One non-blocking check of the 3K stage (Cryocon Channel C) against limit_3k.
    Returns None when the stage is cold enough, otherwise the poll interval (s) to wait
    before checking again (60 s > 20 K or unknown, 30 s for 5-20 K, 10 s below 5 K).

    NOTE: world.wait() only *schedules* a wait; it takes effect at the next yield, and
    yields exist only in @state bodies. So the wait loop must live in the state body:
        while True:
            poll_s = precool_poll_interval(world, ...)
            if poll_s is None:
                break
            world.wait(poll_s)
    A loop calling world.wait() inside a plain helper never yields: it spins on stale
    data, stops telemetry logging, and cannot be aborted from the GUI.
    """
    mr = most_recent_measurements()
    c_temp = mr.get("cryocon_chC_temperature")
    if c_temp is not None and np.isfinite(c_temp) and float(c_temp) < limit_3k:
        return None
    if c_temp is None or not np.isfinite(c_temp) or float(c_temp) > 20.0:
        poll_interval = 60.0
    elif float(c_temp) > 5.0:
        poll_interval = 30.0
    else:
        poll_interval = 10.0
    c_disp = f"{float(c_temp):.1f} K" if (c_temp is not None and np.isfinite(c_temp)) else "measuring..."
    world.set_phase(
        f"{phase_name} (3K = {c_disp} -> < {limit_3k:.1f}K, poll {int(poll_interval)}s)",
        step, total_steps
    )
    return poll_interval


def load_pid_config():
    """Read pid_config from ~/2pac_logs/gui_settings.json ({} if missing/unreadable)."""
    try:
        import json
        cfg_p = Path.home() / "2pac_logs" / "gui_settings.json"
        if cfg_p.exists():
            with open(cfg_p) as f:
                return json.load(f).get("pid_config", {}) or {}
    except Exception:
        pass
    return {}


# Magnet ramp on the LS370 10 mA range with the 100 Ohm Kepco programming shunt.
# Measured 2026-11-16: 58.1 % -> 9.25-9.42 A (Kepco is voltage-programmed, so +-1 % drift with lead temperature).
MAGNET_RAMP_RANGE = "10mA"
MAGNET_RAMP_RANGE_CODE = 6
MAGNET_AMPS_PER_PCT = 9.33 / 58.1
# Max 3K-stage (Ch C) temperature at which he3_adr_resume_at_ramp may start ramping.
RESUME_MAX_3K_K = 5.0


def set_magnet_output(world, pct):
    """Open-loop LS370 output (%), remembering the commanded value for ramp_down_magnet (P0-3)."""
    world.station.ls370.heater.out(float(pct))
    world.last_commanded_hout = float(pct)


def ls370_output_to_zero(world):
    """Open loop at 0 %. MOUT is written before CMODE so the switch from closed loop doesn't jump elsewhere."""
    rc = world.station.ls370.heater
    rc.out(0.0)
    time.sleep(0.2)
    rc.mode("open_loop")
    time.sleep(0.2)
    rc.out(0.0)
    world.last_commanded_hout = 0.0


def prepare_ls370_for_magnet_ramp(world):
    """
    Put the LS370 heater in open loop at 0 % and select the 10 mA range for the magnet ramp.

    regulate_temperature writes CSET with the *regulation* current limit, and the LS370 will not run
    a heater range above the CSET limit. So the limit must be at least code 6 before every ramp,
    otherwise 59 % on a clamped range commands ~1 % of full field. Reads HTRRNG? and CSET? back
    (both verified) and raises, with the output still at 0 %,
    if the 10 mA range / limit cannot be confirmed.
    """
    ls = world.station.ls370
    rc = ls.heater
    ls370_output_to_zero(world)
    time.sleep(0.3)
    pid_cfg = load_pid_config()
    ch = int(pid_cfg.get("channel", 4))
    r = float(pid_cfg.get("heater_resistance", 100.0))
    ls.write(f"CSET {ch}, 1, 1, 1, 1, {MAGNET_RAMP_RANGE_CODE}, {r:.1f}")
    time.sleep(0.5)
    rc.range(MAGNET_RAMP_RANGE)
    time.sleep(0.5)

    last = ""
    for _ in range(3):
        try:
            rng = int(float(ls.ask("HTRRNG?").strip()))
            time.sleep(0.2)
            cset = [s.strip() for s in ls.ask("CSET?").split(",")]
            limit = int(float(cset[5])) if len(cset) >= 6 else -1
            last = f"HTRRNG?={rng}, CSET limit={limit}"
            if rng == MAGNET_RAMP_RANGE_CODE and limit >= MAGNET_RAMP_RANGE_CODE:
                print(f"LS370 ready for magnet ramp: {last} (open loop, 0 %)")
                return
        except Exception as e:
            last = f"readback error: {e}"
        time.sleep(0.5)
    raise RuntimeError(
        f"LS370 not on the {MAGNET_RAMP_RANGE} range for the magnet ramp ({last}). "
        "Output left at 0 %. Check the heater range/limit on the Lake Shore before retrying.")


def magnet_ramp_fault(hout_pct, meas_I, expected_lagged_A=None):
    """
    Compare measured Kepco current with what the commanded LS370 output should give.
    "high": current well above the *unlagged* command (wrong range / shunt missing) - must trip fast.
    "low": current far below the *lagged* expectation (Kepco off / range clamped). The magnet current
    trails the command with tau ~250 s in RAMP, so judging against the instantaneous command nearly
    aborted a healthy ramp on 11/16 (ratio 0.30-0.33 at 3 %).
    Returns "high", "low" or None.
    """
    if meas_I is None or not np.isfinite(meas_I):
        return None
    expected = float(hout_pct) * MAGNET_AMPS_PER_PCT
    if abs(meas_I) > 1.3 * expected + 0.3:
        return "high"
    lagged = expected if expected_lagged_A is None else float(expected_lagged_A)
    if lagged >= 0.5 and abs(meas_I) < 0.3 * lagged:
        return "low"
    return None


class MagnetRampGuard:
    """
    Tracks a first-order (tau) lagged expectation of the magnet current and how long each fault has
    persisted (seconds, not loop iterations). update() returns "high"/"low" once a fault has lasted
    long enough (high: 3 s, low: 60 s), else None.
    """
    HIGH_PERSIST_S = 3.0
    LOW_PERSIST_S = 60.0

    def __init__(self, tau_s=250.0, start_A=0.0):
        self.tau_s = max(1.0, float(tau_s))
        self.lagged_A = float(start_A)
        self.t_last = None
        self.fault = None
        self.fault_since = None

    def update(self, t, hout_pct, meas_I):
        cmd_A = float(hout_pct) * MAGNET_AMPS_PER_PCT
        if self.t_last is not None:
            dt = max(0.0, t - self.t_last)
            self.lagged_A += (cmd_A - self.lagged_A) * (1.0 - np.exp(-dt / self.tau_s))
        self.t_last = t
        f = magnet_ramp_fault(hout_pct, meas_I, self.lagged_A)
        if f != self.fault:
            self.fault, self.fault_since = f, (t if f else None)
        if f == "high" and t - self.fault_since >= self.HIGH_PERSIST_S:
            return "high"
        if f == "low" and t - self.fault_since >= self.LOW_PERSIST_S:
            return "low"
        return None

@state
def he3_adr_cycle(world: StationWorld):
    cfg = get_adr_config(world)
    log_effective_config(world, "he3_adr_cycle")

    charcoal_sp = float(cfg.get("charcoal_heat_sp", 55.0))
    flange_sp = float(cfg.get("flange_60k_heat_sp", 65.0))
    limit_3k = float(cfg.get("starting_temp_3k", cfg.get("pot_precool_limit_k", 3.2)))
    precool_timeout_s = float(cfg.get("precool_timeout_h", 12.0)) * 3600.0

    condense_dwell_s = float(cfg.get("he3_condense_dwell_h", 3.5)) * 3600.0
    launch_temp_k = float(cfg.get("launch_temp_k", 1.0))
    launch_max_rate = float(cfg.get("launch_max_rate_mk_min", 1.0))
    launch_timeout_s = float(cfg.get("launch_timeout_h", 4.0)) * 3600.0
    launch_dwell_s = float(cfg.get("launch_dwell_min", 1.0)) * 60.0

    t_hout = float(cfg.get("magnet_max_hout", MAGNET_MAX_HOUT))
    ramp_up_s = float(cfg.get("magnet_ramp_up_min", 45.0)) * 60.0
    ramp_down_s = float(cfg.get("magnet_ramp_down_min", 60.0)) * 60.0
    tau_s = float(cfg.get("magnet_tau_s", 250.0))
    demag_settle_s = float(cfg.get("demag_settle_min", 20.0)) * 60.0

    # Resume mode (set by he3_adr_resume_at_ramp): charcoal is already being heated, so skip the
    # heat-switch reset and the 3K pre-cool gate and go straight to the magnet ramp.
    resume_at_ramp = bool(getattr(world, "resume_at_ramp", False))
    world.resume_at_ramp = False

    # 0. safety: never start (and ramp from 0) while the magnet is energized
    check_magnet_deenergized(world)
    # Operator must close the green He-3 valve BEFORE step 1 (also confirmed in GUI)
    print("CLOSE THE GREEN HE3 VALVE")

    if resume_at_ramp:
        c3k = most_recent_measurements().get("cryocon_chC_temperature")
        if c3k is None or not np.isfinite(c3k) or float(c3k) > RESUME_MAX_3K_K:
            raise RuntimeError(f"Refusing to resume at magnet ramp: 3K stage (Ch C) = {c3k} K (> {RESUME_MAX_3K_K} K).")
        world.set_phase("Resume: skipping pre-cool (charcoal already heating)", 1, 6)
        safe_set_heatswitch(world, "pot", "CLOSED")
        world.wait(1)
        safe_set_heatswitch(world, "adr", "CLOSED")
        world.wait(1)
    else:
        # 1. Close all heat switches in the beginning and wait 30 seconds before switching relay to RAMP
        world.set_phase("Pre-cooling: Closing All Heat Switches (30s settle)", 1, 6)
        safe_set_heatswitch(world, "pot", "CLOSED")
        world.wait(1)
        safe_set_heatswitch(world, "adr", "CLOSED")
        world.wait(1)
        safe_set_heatswitch(world, "charcoal", "CLOSED")
        world.wait(30)

        # Pre-cooling temperature check (ensure 3K stage is cold enough). Loop stays in the state body so it yields.
        t_precool = time.time()
        warned = False
        while True:
            poll_s = precool_poll_interval(world, limit_3k, "Pre-cooling Check", 1, 6)
            if poll_s is None:
                break
            if not warned and time.time() - t_precool > precool_timeout_s:
                warned = True
                notify(world, f"⏳ Pre-cool has waited {precool_timeout_s/3600:.0f} h for the 3K stage to reach {limit_3k:.1f} K. Still waiting (nothing changed). Check the cryocooler.", key="precool_timeout")
            world.wait(poll_s)

    # 2. Zero the LS370 output (it may still be regulating in CONTROL), wait until no current flows,
    #    then switch the relay to RAMP and set the 10 mA range (CSET limit raised + verified).
    world.set_phase("Preparing magnet ramp: LS370 to 0 %, waiting for I < 10 mA", 2, 6)
    ls370_output_to_zero(world)
    t_zero = time.time()
    while True:
        mag_I, _ = _read_magnet(world)
        if np.isfinite(mag_I) and abs(mag_I) < RELAY_SWITCH_MAX_A:
            break
        if time.time() - t_zero > 120 and _relay_cached(world) == "RAMP" and np.isfinite(mag_I) and abs(mag_I) < MAGNET_ENERGIZED_A:
            break  # already in RAMP with a small residual: no relay switch needed below
        if time.time() - t_zero > 600:
            raise RuntimeError(f"Magnet current still {mag_I:.3f} A 10 min after zeroing the LS370 output; not switching the relay.")
        world.wait(2)
    if _relay_cached(world) != "RAMP":
        world.station.labjack.relay("RAMP")
        world.wait(2)
    prepare_ls370_for_magnet_ramp(world)
    world.wait(1)

    # 3. Open charcoal heatswitch and start heating sorption charcoal
    world.set_phase(f"Heating Sorption Charcoal ({charcoal_sp:.0f}K)", 2, 6)
    safe_set_heatswitch(world, "charcoal", "OPEN")
    world.wait(1)
    world.station.cryocon.loop1_source("A")
    world.wait(1)
    world.station.cryocon.loop1_setpoint(flange_sp)
    world.wait(1)
    world.station.cryocon.loop2_source("B")
    world.wait(1)
    world.station.cryocon.loop2_range("HI")
    world.wait(1)
    world.station.cryocon.loop2_setpoint(charcoal_sp)
    world.wait(1)
    world.station.cryocon.control_enabled(True)  # heat charcoal
    world.wait(1)

    # 4. Ramp up ADR magnet current starting smoothly from zero.
    # Ramp-tracking guard against a tau-lagged expectation (catches Kepco off, LS370 range clamped,
    # shunt/range mis-scaling) before the dwell is committed. Also checks V/I against the RAMP circuit.
    world.set_phase("Ramping ADR Magnet Up (0% -> max)", 3, 6)
    guard = MagnetRampGuard(tau_s=tau_s)
    fault = None
    vi_checked = False
    hout = 0.0
    t_start_ramp = time.time()
    while True:
        elapsed = time.time() - t_start_ramp
        fraction = min(1.0, elapsed / max(1.0, ramp_up_s))
        hout = fraction * t_hout
        set_magnet_output(world, hout)
        mag_I = most_recent_measurements().get("labjack_kepco_current")
        fault = guard.update(time.time(), hout, mag_I)
        if fault:
            break
        if not vi_checked and mag_I is not None and np.isfinite(mag_I) and abs(mag_I) > 1.0:
            vi_checked = True
            vi_msg = relay_vi_mismatch("RAMP", most_recent_measurements().get("labjack_kepco_voltage", float("nan")), mag_I)
            if vi_msg:
                notify(world, "⚠️ " + vi_msg, key="relay_vi_ramp")
        if fraction >= 1.0:
            break
        world.wait(1)

    if fault == "low":
        notify(world, f"⚠️ MAGNET NOT FOLLOWING: LS370 at {hout:.1f}% (expected ~{guard.lagged_A:.2f} A after lag) but Kepco current is ~0 A. Is the Kepco ON? Ramping LS370 output back to 0. Cryo-con left ON. Fix, then run 'He-3 + ADR: Resume at Magnet Ramp'.", key="ramp_low")
        return ramp_down_magnet
    if fault == "high":
        notify(world, f"🛑 MAGNET CURRENT TOO HIGH for LS370 {hout:.2f}% (expected {hout * MAGNET_AMPS_PER_PCT:.2f} A). Output HELD. Check LS370 range and 100 Ohm shunt before ramping down. Cryo-con left ON.", key="ramp_high")
        return wait_forever

    # 5. wait for he3 to condense
    world.set_phase("He-3 Condensation Dwell", 4, 6)
    world.wait(condense_dwell_s)

    # 6. cool charcoal and wait until the FAA is below the launch temperature AND has settled
    #    (the jump after opening the ADR switch is mostly the thermometer catching up with the pill).
    disp_launch = f"{launch_temp_k * 1000.0:.0f}mK" if launch_temp_k < 1.0 else f"{launch_temp_k:.2f}K"
    world.set_phase(f"Cooling to Launch Temp (FAA < {disp_launch}, settled)", 5, 6)
    safe_set_heatswitch(world, "pot", "OPEN")
    world.wait(1)
    world.station.cryocon.control_enabled(False)  # turn off heaters
    world.wait(120)  # a bit of cooling before closing charcoal heatswitch
    safe_set_heatswitch(world, "charcoal", "CLOSED")
    world.wait(1)

    faa_hist = []
    launch_timed_out = False
    t_launch_wait = time.time()
    while True:
        faa_t = most_recent_measurements().get("faa_temperature")
        faa_hist.append((time.time(), faa_t))
        faa_hist = faa_hist[-2000:]
        rate = faa_rate_mk_min(faa_hist)
        cold = faa_t is not None and np.isfinite(faa_t) and float(faa_t) < launch_temp_k
        if cold and rate is not None and abs(rate) <= launch_max_rate:
            break
        rate_disp = "measuring" if rate is None else f"{rate:+.2f} mK/min"
        faa_disp = f"{float(faa_t):.3f} K" if (faa_t is not None and np.isfinite(faa_t)) else "n/a"
        world.set_phase(f"Cooling to Launch (FAA {faa_disp} < {disp_launch}, rate {rate_disp}, need |rate| <= {launch_max_rate:g})", 5, 6)
        if time.time() - t_launch_wait > launch_timeout_s:
            notify(world, f"⏳ Launch wait timed out after {launch_timeout_s/3600:.1f} h (FAA {faa_disp}, rate {rate_disp}). Magnet held at full field. Click 'Confirm Step Done' to open the ADR switch and demag anyway, or Stop / Ramp Down Magnet.", key="launch_timeout")
            launch_timed_out = True
            break
        world.wait(5)

    while launch_timed_out and not world.is_operator_action_confirmed():
        world.set_phase("WAITING FOR OPERATOR: confirm launch (banner)", 5, 6)
        world.wait(1)

    # 7. open the ADR switch, short dwell, demag
    safe_set_heatswitch(world, "adr", "OPEN")
    world.wait(1)

    if launch_dwell_s > 0:
        world.set_phase(f"Launch Settle (Waiting {launch_dwell_s/60.0:.0f}m)", 6, 6)
        world.wait(launch_dwell_s)

    target_k, target_mk = get_adr_regulation_setpoint(world)
    reg_disp = f"{target_mk:.0f}mK" if target_mk < 1000.0 else f"{target_k:.3f}K"
    world.set_phase(f"Demag Ramp Down & Regulate @ {reg_disp}", 6, 6)

    t_start_down = time.time()
    while True:
        elapsed = time.time() - t_start_down
        fraction = min(1.0, elapsed / max(1.0, ramp_down_s))
        hout = (1.0 - fraction) * t_hout
        set_magnet_output(world, hout)
        if fraction >= 1.0:
            break
        world.wait(1)

    # 8. Settle: wait at least demag_settle_s AND until |I| < 10 mA before the relay may switch (2c).
    #    Track the FAA minimum to compare with the regulation setpoint (P0-7).
    world.set_phase(f"Demag Settle (waiting for |I| < {RELAY_SWITCH_MAX_A*1000:.0f} mA)", 6, 6)
    t_settle_start = time.time()
    faa_min = None
    settle_warned = False
    while True:
        elapsed_settle = time.time() - t_settle_start
        mr = most_recent_measurements()
        cur_i = mr.get("labjack_kepco_current")
        faa_t = mr.get("faa_temperature")
        if faa_t is not None and np.isfinite(faa_t):
            faa_min = float(faa_t) if faa_min is None else min(faa_min, float(faa_t))
        if elapsed_settle >= demag_settle_s and cur_i is not None and np.isfinite(cur_i) and abs(float(cur_i)) < RELAY_SWITCH_MAX_A:
            break
        if not settle_warned and elapsed_settle >= demag_settle_s + 900.0:
            settle_warned = True
            notify(world, f"⏳ Magnet current still {cur_i} A {elapsed_settle/60:.0f} min after demag (need < {RELAY_SWITCH_MAX_A*1000:.0f} mA before switching the relay to CONTROL). Holding at 0 % output; regulation will start once it decays.", key="demag_settle")
        world.wait(1)

    if faa_min is not None and target_k < faa_min + 0.002:
        notify(world, f"ℹ Regulation setpoint {target_mk:.1f} mK is below or near the post-demag base ({faa_min*1000:.1f} mK). The heater will sit at 0 % until the FAA warms to the setpoint; consider raising it.", key="setpoint_below_base")

    # 9. Demag complete: transition directly to closed-loop temperature regulation holding state
    return regulate_temperature

@state
def he3_adr_resume_at_ramp(world: StationWorld):
    """
    Resume a He-3 + ADR cycle at the magnet ramp-up step.
    For when the charcoal is already being heated (Cryo-con on, charcoal heat switch open)
    but the magnet did not ramp, e.g. the Kepco was off. Skips the heat-switch reset and the
    3K < 3.2 K pre-cool gate (requires 3K stage < 5 K), keeps the Cryo-con heating, ramps the
    magnet from 0 on the 10 mA range, then runs the rest of he3_adr_cycle unchanged.
    """
    world.resume_at_ramp = True
    return he3_adr_cycle

@state
def ramp_down_magnet(world: StationWorld):
    """
    Safely ramp the magnet current to 0 and leave the LS370 at open loop 0 %, range off, relay RAMP.
    Heat switches and Cryo-con are left untouched.

    Starting point (P0-3), in order of preference: the last output this software commanded, the LS370
    HTR? reading (3 tries), the measured current / (A per %). It never steps the output to 0 while more
    than MAGNET_ENERGIZED_A flows in RAMP; if no starting point can be established it holds and asks
    the operator instead. Duration scales with the measured current (A/s from the configured full-field
    ramp-down time). The relay is only switched once |I| < 10 mA.
    """
    cfg = get_adr_config(world)
    ramp_time_full_s = float(cfg.get("magnet_ramp_down_min", 60.0)) * 60.0
    max_hout = float(cfg.get("magnet_max_hout", MAGNET_MAX_HOUT))
    rc = world.station.ls370.heater
    relay = _relay_cached(world)
    world.set_phase("Safe Ramp Down: reading magnet drive", 1, 1)

    mag_I, _ = _read_magnet(world)
    start_hout = world.last_commanded_hout
    if start_hout is None or not np.isfinite(start_hout):
        start_hout = None
        for attempt in range(3):
            try:
                v = float(rc.out())
                if np.isfinite(v):
                    start_hout = v
                    break
            except Exception as e:
                print(f"ramp_down_magnet: HTR? read failed ({e}), retrying")
            world.wait(1)
    if start_hout is None and np.isfinite(mag_I) and relay != "CONTROL":
        start_hout = abs(mag_I) / MAGNET_AMPS_PER_PCT
    if start_hout is None:
        if np.isfinite(mag_I) and abs(mag_I) > MAGNET_ENERGIZED_A and relay != "CONTROL":
            notify(world, f"🛑 Ramp Down: cannot establish the LS370 output and the magnet carries {mag_I:.2f} A. Output HELD (not stepping to 0 at field). Check the LS370 / serial link, then retry Ramp Down Magnet.", key="rampdown_unknown")
            return wait_forever
        start_hout = 0.0

    # Closed loop (e.g. regulating in CONTROL): write the starting output first, then go to open loop,
    # so the hand-over does not jump. In CONTROL the 12 Ohm series resistor limits the current anyway.
    rc.out(float(start_hout))
    world.wait(1)
    rc.mode("open_loop")
    world.wait(1)

    if relay == "CONTROL" or start_hout <= 0.0:
        actual_ramp_time_s = 30.0 if start_hout > 0 else 1.0
    else:
        start_A = start_hout * MAGNET_AMPS_PER_PCT
        rate_A_s = MAGNET_FULL_FIELD_A / max(1.0, ramp_time_full_s)
        actual_ramp_time_s = max(1.0, start_A / rate_A_s)
    world.set_phase(f"Safe Ramp Down: {start_hout:.1f}% -> 0% over {actual_ramp_time_s/60.0:.1f} min", 1, 1)
    t_start_safe = time.time()
    while True:
        fraction = min(1.0, (time.time() - t_start_safe) / actual_ramp_time_s)
        set_magnet_output(world, (1.0 - fraction) * start_hout)
        if fraction >= 1.0:
            break
        world.wait(1)
    set_magnet_output(world, 0.0)
    world.wait(1)

    # Wait for the current to decay (RAMP tau ~250 s) before turning the range off / switching the relay.
    world.set_phase(f"Ramp Down: waiting for |I| < {RELAY_SWITCH_MAX_A*1000:.0f} mA", 1, 1)
    t_decay = time.time()
    decayed = False
    while time.time() - t_decay < 3600:
        mag_I, _ = _read_magnet(world)
        if np.isfinite(mag_I) and abs(mag_I) < RELAY_SWITCH_MAX_A:
            decayed = True
            break
        world.wait(2)
    rc.range("off")
    world.wait(1)
    if not decayed:
        notify(world, f"⚠️ Ramp Down: output is 0 % but the magnet current is still {mag_I:.3f} A after 1 h. Relay NOT switched. Check the Kepco / LabJack reading.", key="rampdown_decay")
        world.set_phase("Idle — output 0 %, current not yet zero (relay unchanged)", 1, 1)
        return wait_forever
    if relay != "RAMP":
        world.station.labjack.relay("RAMP")
        world.wait(2)
    world.set_phase("Idle — Holding Steady (magnet ramped down)", 1, 1)
    return wait_forever

@state
def wait_forever(world: StationWorld):
    world.set_phase("Idle — Holding Steady", 1, 1)
    while True:
        world.wait(1)


@state
def ready_for_cooldown(world:StationWorld):
    # Doesn't really do anything except close HS 
    world.set_phase("Pre-cooling: Heat switches closed", 1, 1)
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("CLOSED")
    world.wait(3)

    # Set He3 setpoints but do nothing
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(45) # Upper stage setpoint = 45 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
    world.station.cryocon.control_enabled(False) 
    print("OPEN THE GREEN HE3 VALVE")
    world.wait(1e6)

def get_current_he3_pressure(world: StationWorld = None):
    """Read current He-3 line pressure in bar."""
    try:
        if world and hasattr(world, "station") and hasattr(world.station, "labjack"):
            param = getattr(world.station.labjack, "he3_pressure", None)
            if param:
                p = param.cache.get()
                if p is not None:
                    return float(p)
                return float(param())
    except Exception:
        pass
    mr = most_recent_measurements()
    p = mr.get("labjack_he3_pressure")
    if p is not None and np.isfinite(p):
        return float(p)
    return None

@state
def autocool_he3_adr(world: StationWorld):
    """
    Auto-Cool + He-3 / ADR Cycle (300 K to Base Temperature).
    Combines 'ready_for_cooldown' and 'he3_adr_cycle' into a single autonomous workflow:
    1. Safety check: Verifies magnet current |I| < 0.2 A.
    2. Pre-cooling setup: Closes all heat switches (Pot, ADR, Charcoal) to couple stages to the 4K cold head.
    3. Cryo-con config: Sets Loop 1 (45 K) and Loop 2 (55 K) with heaters disabled.
    4. He-3 Pressure Monitoring: Monitors He-3 line pressure as cryostat cools from 300 K.
       When He-3 pressure drops to 0 bar (<= 0.10 bar, ~24 h after pulse tube comes on):
       Puts up an operator action banner to CLOSE THE GREEN HE-3 VALVE, and PAUSES
       without proceeding until the message is acknowledged.
    5. Adaptive Cooldown Wait: Waits for 3K stage (Ch C) to reach < 3.2 K (~29 hours from pulse tube start)
       using adaptive slow polling (60s down to 10s) without spamming the serial bus.
    6. Once cold (< 3.2 K) and valve closure confirmed, automatically launches the He-3 + ADR cycle:
       heats sorption charcoal, ramps magnet to 9.5 A, dwells for condensation, cools charcoal,
       demagnetizes to base, and hands off to closed-loop temperature regulation.
    """
    cfg = get_adr_config(world)
    limit_3k = float(cfg.get("starting_temp_3k", cfg.get("pot_precool_limit_k", 3.2)))
    log_effective_config(world, "autocool_he3_adr")

    # 0. Safety: ensure magnet is de-energized
    check_magnet_deenergized(world)

    # 1. Pre-cooling setup: Close all heat switches to establish thermal contact with cold head
    world.set_phase("Auto-Cool: Pre-cooling Setup (Heat Switches Closed)", 1, 7)
    safe_set_heatswitch(world, "pot", "CLOSED")
    world.wait(1)
    safe_set_heatswitch(world, "adr", "CLOSED")
    world.wait(1)
    safe_set_heatswitch(world, "charcoal", "CLOSED")
    world.wait(3)

    # Pre-configure Cryocon setpoints (heaters OFF during cooldown)
    if hasattr(world.station, "cryocon"):
        try:
            world.station.cryocon.loop1_source("A")
            world.wait(1)
            world.station.cryocon.loop1_setpoint(45) # Upper stage setpoint = 45 K
            world.wait(1)
            world.station.cryocon.loop2_source("B")
            world.wait(1)
            world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
            world.wait(1)
            world.station.cryocon.control_enabled(False) # heaters remain off during cooldown
            world.wait(1)
        except Exception as e:
            print(f"Notice: cryocon pre-cool setup: {e}")

    # 2. Monitor cooldown until He-3 pressure drops to 0 bar (~24 hours after pulse tube comes on)
    orig_tick = getattr(world, "target_tick_rate_s", 1.0)
    t_cool = time.time()
    cool_warned = False
    try:
        while True:
            if not cool_warned and time.time() - t_cool > 48 * 3600.0:
                cool_warned = True
                notify(world, "⏳ Auto-Cool: He-3 pressure has not dropped to 0 bar after 48 h of cooldown. Still waiting; check the cryocooler and He-3 line.", key="autocool_timeout")
            p_he3 = get_current_he3_pressure(world)
            mr = most_recent_measurements()
            c_temp = mr.get("cryocon_chC_temperature")

            # Condition: He-3 pressure has dropped to 0 bar (<= 0.10 bar)
            if p_he3 is not None and np.isfinite(p_he3) and float(p_he3) <= 0.10:
                break

            # Adaptive slow polling during cooldown before pressure drops:
            if c_temp is None or not np.isfinite(c_temp) or float(c_temp) > 20.0:
                poll_interval = 60.0
            elif float(c_temp) > 5.0:
                poll_interval = 30.0
            else:
                poll_interval = 10.0

            p_disp = f"{float(p_he3):.2f} bar" if (p_he3 is not None and np.isfinite(p_he3)) else "measuring..."
            c_disp = f"{float(c_temp):.1f} K" if (c_temp is not None and np.isfinite(c_temp)) else "measuring..."
            phase_txt = f"Auto-Cool Pre-cooling: P_He3 = {p_disp} (waiting for 0 bar), 3K = {c_disp} (poll {int(poll_interval)}s)"
            world.set_phase(phase_txt, 2, 7)
            world.target_tick_rate_s = poll_interval
            world.wait(poll_interval)
    finally:
        world.target_tick_rate_s = orig_tick

    # 3. He-3 pressure reached 0 bar! Put up high-visibility banner and DO NOT PROCEED until acknowledged
    msg = "⚠️ ACTION REQUIRED: He-3 pressure has dropped to 0 bar (~24h into cooldown). CLOSE the GREEN He-3 valve on the cryostat now, then click 'Confirm Step Done'."
    world.request_operator_action(msg)

    # Halt procedure progression until operator explicitly acknowledges
    while not world.is_operator_action_confirmed():
        p_he3 = get_current_he3_pressure(world)
        p_disp = f"{float(p_he3):.2f} bar" if (p_he3 is not None and np.isfinite(p_he3)) else "0.00 bar"
        wait_msg = f"WAITING FOR OPERATOR: Close GREEN He-3 Valve & click Confirm in top banner (P_He3 = {p_disp})"
        world.set_phase(wait_msg, 3, 7)
        world.wait(1)

    print("Operator confirmed green He-3 valve is CLOSED. Resuming autonomous cooldown sequence.")

    # 4. Wait for 3K stage to reach < 3.2 K (~29 hours total from pulse tube start)
    while True:
        poll_s = precool_poll_interval(world, limit_3k, "Auto-Cool Pre-cooling (3K -> 3.2K)", 4, 7)
        if poll_s is None:
            break
        world.wait(poll_s)

    # 5. 3K stage reached < 3.2 K and green valve confirmed closed! Settle 30s
    world.set_phase(f"Pre-cooling Complete (3K < {limit_3k:.1f} K). Transitioning to He-3 + ADR...", 4, 7)
    world.wait(30)

    # 6. Proceed directly into the verified He-3 + ADR cycle!
    return he3_adr_cycle

@state
def he3_only_cycle(world: StationWorld):
    """
    Helium-3 Sorption Refrigerator Cycle (No Magnet / No ADR).
    Cycles the sorption pump to condense He-3 and achieve ~300 mK base temperature
    at the 1K pot without touching or energizing the superconducting magnet.
    """
    testmode = False
    cfg = get_adr_config(world)

    charcoal_sp = float(cfg.get("charcoal_heat_sp", 55.0))
    flange_sp = float(cfg.get("flange_60k_heat_sp", 65.0))
    limit_3k = float(cfg.get("starting_temp_3k", cfg.get("pot_precool_limit_k", 3.2)))

    condense_dwell_s = float(cfg.get("he3_condense_dwell_h", 3.5)) * 3600.0
    launch_temp_k = float(cfg.get("launch_temp_k", 1.0))

    # 0. safety: check magnet is de-energized and ensure relay is set to CONTROL (magnet isolated).
    #    Only switch the relay with the LS370 at 0 % and no current flowing.
    log_effective_config(world, "he3_only_cycle")
    check_magnet_deenergized(world)
    if _relay_cached(world) != "CONTROL":
        ls370_output_to_zero(world)
        t_zero = time.time()
        while True:
            mag_I, _ = _read_magnet(world)
            if np.isfinite(mag_I) and abs(mag_I) < RELAY_SWITCH_MAX_A:
                break
            if time.time() - t_zero > 1800:
                raise RuntimeError(f"Not switching the relay to CONTROL: magnet current still {mag_I:.3f} A after 30 min at 0 % output.")
            world.wait(2)
        world.station.labjack.relay("CONTROL")
        world.wait(1)

    # Operator must close the green He-3 valve BEFORE step 1
    print("CLOSE THE GREEN HE3 VALVE")

    # 1. set heat switches and check that we're cold enough to start
    # Pot and ADR heat switches are CLOSED so the FAA stage is connected to the He-3 pot
    safe_set_heatswitch(world, "pot", "CLOSED")
    world.wait(1)
    safe_set_heatswitch(world, "adr", "CLOSED")
    world.wait(1)
    safe_set_heatswitch(world, "charcoal", "OPEN")
    world.wait(1)
    t_precool = time.time()
    precool_warned = False
    while True:
        poll_s = precool_poll_interval(world, limit_3k, "Pre-cooling Check", 1, 4)
        if poll_s is None:
            break
        if not precool_warned and time.time() - t_precool > float(cfg.get("precool_timeout_h", 12.0)) * 3600.0:
            precool_warned = True
            notify(world, f"⏳ Pre-cool still waiting for the 3K stage < {limit_3k:.1f} K after {float(cfg.get('precool_timeout_h', 12.0)):.0f} h.", key="precool_timeout")
        world.wait(poll_s)

    # 2. start heating charcoal
    world.set_phase(f"Heating Sorption Charcoal ({charcoal_sp:.0f}K)", 2, 4)
    world.station.cryocon.loop1_source("A")
    world.wait(1)
    world.station.cryocon.loop1_setpoint(flange_sp)
    world.wait(1)
    world.station.cryocon.loop2_source("B")
    world.wait(1)
    world.station.cryocon.loop2_range("HI")
    world.wait(1)
    world.station.cryocon.loop2_setpoint(charcoal_sp) # Charcoal setpoint = 55 K
    world.wait(1)
    world.station.cryocon.control_enabled(True) # heat charcoal
    world.wait(1)

    # 3. wait for he3 to condense
    world.set_phase("He-3 Condensation Dwell", 3, 4)
    if testmode:
        world.wait(10)
    else:
        world.wait(condense_dwell_s) # takes about 3.5 hours to condense He-3

    # 4. cool charcoal and wait for launch/base temperature
    # Open pot heat switch to isolate 1K pot from 4K, but keep ADR switch CLOSED so FAA cools with pot
    disp_launch = f"{launch_temp_k * 1000.0:.0f}mK" if launch_temp_k < 1.0 else f"{launch_temp_k:.2f}K"
    world.set_phase(f"Cooling to Base Temp (FAA / Pot < {disp_launch})", 4, 4)
    safe_set_heatswitch(world, "pot", "OPEN") # thermally isolate 1K pot from 4K bath
    world.wait(1)
    safe_set_heatswitch(world, "adr", "CLOSED") # keep ADR heat switch connected to the pot
    world.wait(1)
    world.station.cryocon.control_enabled(False) # turn off heaters
    if testmode:
        world.wait(1)
    else: 
        world.wait(120) # a bit of cooling before closing charcoal heatswitch
    safe_set_heatswitch(world, "charcoal", "CLOSED")  
    world.wait(1)
    safe_set_heatswitch(world, "adr", "CLOSED") # keep ADR heat switch connected to the pot
    world.wait(1)
    
    if testmode:
        world.wait(5)
    else:
        t_base_wait = time.time()
        base_warned = False
        while True:
            mr = most_recent_measurements()
            faa_t = mr.get("faa_temperature")
            pot_t = mr.get("cryocon_chD_temperature")
            if (faa_t is not None and np.isfinite(faa_t) and float(faa_t) < launch_temp_k) or (pot_t is not None and np.isfinite(pot_t) and float(pot_t) < launch_temp_k):
                break
            if not base_warned and time.time() - t_base_wait > float(cfg.get("launch_timeout_h", 4.0)) * 3600.0:
                base_warned = True
                notify(world, f"⏳ He-3 cycle: FAA/pot not below {launch_temp_k:.2f} K after {float(cfg.get('launch_timeout_h', 4.0)):.1f} h. Still waiting; check the He-3 condensation.", key="he3_base_timeout")
            world.wait(1)

    # Done — holding steady at base temperature with ADR heat switch connected to the pot
    safe_set_heatswitch(world, "adr", "CLOSED")
    world.set_phase("Idle — Holding Steady (He-3 Base Temp, ADR Switch Connected)", 1, 1)
    return wait_forever

def regulation_settings():
    """pid_config from gui_settings.json with REGULATION_DEFAULTS filled in for missing keys."""
    cfg = dict(REGULATION_DEFAULTS)
    cfg.update({k: v for k, v in load_pid_config().items() if v is not None})
    return cfg


def _parse_floats(reply):
    out = []
    for x in str(reply).split(","):
        try:
            out.append(float(x.strip()))
        except ValueError:
            out.append(None)
    return out


def configure_ls370_regulation(ls, pc, only_if_different=False):
    """
    Write CSET / PID / RAMP / SCAN for regulation from settings `pc`. With only_if_different, read
    each register first and skip writes that would not change anything (used when adopting a loop
    that is already running, so it is not disturbed). Returns a list of what was written.
    """
    written = []
    ch = int(pc["channel"])
    want = {
        "CSET": (f"CSET {ch}, 1, 1, 1, 1, {int(pc['heater_limit'])}, {float(pc['heater_resistance']):.1f}",
                 [ch, 1, 1, 1, 1, int(pc["heater_limit"]), float(pc["heater_resistance"])]),
        "PID": (f"PID {float(pc['p']):.4f}, {float(pc['i']):.1f}, {float(pc['d']):.1f}",
                [float(pc["p"]), float(pc["i"]), float(pc["d"])]),
        "RAMP": (f"RAMP {1 if pc.get('ramp_enable') else 0}, {float(pc['ramp_rate_mk_min']) / 1000.0:.4f}",
                 [1 if pc.get("ramp_enable") else 0, None]),
        "SCAN": (f"SCAN {ch}, 0", [ch, 0]),
    }
    for reg, (cmd, expect) in want.items():
        if only_if_different:
            try:
                have = _parse_floats(ls.ask(f"{reg}?"))
                same = len(have) >= len(expect) and all(e is None or (h is not None and abs(h - e) <= 1e-3 * max(1.0, abs(e))) for h, e in zip(have, expect))
                if same:
                    continue
            except Exception as e:
                print(f"[regulate] {reg}? read failed ({e}); writing anyway")
        ls.write(cmd)
        written.append(cmd)
        time.sleep(0.2)
    return written


def sync_ls370_loop_registers(rc, want_range):
    """
    Make CMODE?/HTRRNG? (and so the LS370 front panel) say what the loop is doing. A CMODE 4 write leaves both
    registers "off" on this unit while the PID output keeps running (2026-11-19), which shows "off" to anyone
    at the instrument. Re-writing HTRRNG with the running range is bumpless (verified 2026-11-19). Re-writing
    CMODE 1 is NOT: the LS370 resets the integrator (2026-11-19 at 45 %: output -> 0.8 %, FAA 60.0 -> 58.0 mK,
    back in ~5 min). That happens once per stale episode, and nothing in this code writes CMODE 4 any more.
    A range the operator chose (not "off") is left alone. Returns (list of fixes, status before).
    """
    st = rc.loop_status()
    fixed = []
    if st["range"] == "off":
        rc.range(str(want_range))
        fixed.append(f"range off -> {want_range}")
    if st["mode"] != "closed":
        rc.mode("closed")
        fixed.append(f"mode {st['mode']} -> closed")
    return fixed, st


@state
def regulate_temperature(world: StationWorld):
    """
    Closed-loop PID regulation of the FAA on the Lake Shore 370 with the relay in CONTROL
    (~12 Ohm in series with the magnet, see POST_CYCLE_FIXES 2b).

    Settings come from gui_settings.json pid_config, falling back to REGULATION_DEFAULTS
    (P 7, I 80 s, D 0, 10 mA range, CSET limit 7: ~25 uK rms at 60 mK, 2026-11-17).

    If a loop is already running (e.g. after a GUI restart: relay CONTROL, HTR? != MOUT?), it is
    adopted: no relay pulse, no output zeroing, and only registers that differ are written.
    """
    target_k, target_mk = get_adr_regulation_setpoint(world)
    disp_target = f"{target_mk:.1f} mK" if target_mk < 1000.0 else f"{target_k:.3f} K"
    world.set_phase(f"Regulating @ {disp_target}", 1, 1)
    log_effective_config(world, "regulate_temperature")

    ls = world.station.ls370
    rc = ls.heater
    pc = regulation_settings()
    relay = _relay_cached(world)

    adopt = False
    if relay == "CONTROL":
        try:
            adopt = bool(rc.closed_loop_active())
        except Exception as e:
            print(f"[regulate] could not detect a running loop ({e})")

    if not adopt and relay != "CONTROL":
        # Switching the relay: magnet must not be energized and no current may flow while it switches.
        check_magnet_deenergized(world)
        world.set_phase("Switching Relay to CONTROL: LS370 to 0 %, waiting for |I| < 10 mA", 1, 1)
        ls370_output_to_zero(world)
        ls.write("RAMP 0, 0")
        t_zero = time.time()
        while True:
            mag_I, _ = _read_magnet(world)
            if np.isfinite(mag_I) and abs(mag_I) < RELAY_SWITCH_MAX_A:
                break
            if time.time() - t_zero > 1800:
                raise RuntimeError(f"Not switching the relay to CONTROL: magnet current still {mag_I:.3f} A after 30 min at 0 % output.")
            world.set_phase(f"Switching Relay to CONTROL: waiting for |I| < 10 mA (now {mag_I:.3f} A)", 1, 1)
            world.wait(2)
        rc.range("off")
        world.station.labjack.relay("CONTROL")
        world.wait(5)
        relay = "CONTROL"

    written = configure_ls370_regulation(ls, pc, only_if_different=adopt)
    world.wait(1)

    if adopt:
        try:
            fixed, before = sync_ls370_loop_registers(rc, pc["heater_range"])
        except Exception as e:
            fixed, before = [f"register check failed ({e})"], {}
        print(f"[regulate] adopted running closed loop; wrote {written or 'nothing'}; registers {fixed or 'already correct'}")
        if fixed:
            notify(world, f"ℹ️ Regulation adopted: LS370 registers/front panel said mode {before.get('mode')}, range "
                          f"{before.get('range')} while the PID was running. Fixed: {', '.join(fixed)}.", key="reg_stale_regs")
    else:
        rc.mode("closed")
        world.wait(1)

    # Setpoint AFTER entering closed loop (the LS370 may overwrite it with the current temperature).
    try:
        cur_sp = float(ls.ask("SETP?"))
    except Exception:
        cur_sp = None
    if cur_sp is None or abs(cur_sp - target_k) > 1e-6:
        ls.write(f"SETP {target_k:.4f}")
        rc.setpoint.cache.set(target_k)
        world.wait(1)

    if not adopt:
        rc.range(str(pc["heater_range"]))
        world.wait(1)

    last_applied_sp = target_k
    world.set_phase(f"Regulating @ {disp_target}" + (" (adopted running loop)" if adopt else ""), 1, 1)

    # Supervision: V/I must look like CONTROL (12 Ohm); output > 20 % for > 10 min with |I| < 10 mA
    # means the range/limit is wrong or the actuator isn't responding (2c).
    vi_warned = False
    starved_since = None
    starved_warned = False
    regs_checked = time.time()
    while True:
        # Front panel must show the running loop: re-check CMODE?/HTRRNG? every 5 min and repair.
        if time.time() - regs_checked > 300:
            regs_checked = time.time()
            try:
                fixed, before = sync_ls370_loop_registers(rc, pc["heater_range"])
                if fixed:
                    notify(world, f"⚠️ LS370 registers changed under regulation (mode {before.get('mode')}, range "
                                  f"{before.get('range')}); restored: {', '.join(fixed)}. Did someone press a front-panel key?",
                           key="reg_regs_drift")
            except Exception as e:
                print(f"[regulate] register check failed: {e}")
        cur_k, cur_mk = get_adr_regulation_setpoint(world)
        if abs(cur_k - last_applied_sp) > 1e-6:
            ls.write(f"SETP {cur_k:.4f}")
            rc.setpoint.cache.set(cur_k)
            last_applied_sp = cur_k
            cur_disp = f"{cur_mk:.1f} mK" if cur_mk < 1000.0 else f"{cur_k:.3f} K"
            world.set_phase(f"Regulating @ {cur_disp}", 1, 1)

        mr = most_recent_measurements()
        mag_I = mr.get("labjack_kepco_current")
        mag_V = mr.get("labjack_kepco_voltage")
        htr = mr.get("ls370_heater_out")
        if not vi_warned and mag_I is not None and mag_V is not None:
            vi_msg = relay_vi_mismatch("CONTROL", float(mag_V), float(mag_I))
            if vi_msg:
                vi_warned = True
                notify(world, "⚠️ " + vi_msg, key="relay_vi_control")
        if htr is not None and mag_I is not None and np.isfinite(htr) and np.isfinite(mag_I) and htr > 20.0 and abs(mag_I) < 0.01:
            starved_since = starved_since or time.time()
            if not starved_warned and time.time() - starved_since > 600:
                starved_warned = True
                notify(world, f"⚠️ Regulation: LS370 output {htr:.0f}% for 10 min but magnet current < 10 mA. Check heater range vs CSET limit (range {pc['heater_range']}, limit {pc['heater_limit']}) and the Kepco.", key="reg_starved")
        else:
            starved_since = None
        world.wait(1)

@state
def warmup_300K(world: StationWorld):
    # Safety: ensure magnet is de-energized before warming up
    check_magnet_deenergized(world)
    print("OPEN THE GREEN HE3 VALVE")

    world.set_phase("Warming cryostat to 295 K", 1, 1)
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("CLOSED")
    world.wait(3)
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(295) # Upper stage setpoint = 295 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_range("HI")
    world.station.cryocon.loop2_setpoint(295) # Charcoal setpoint = 295 K
    world.station.cryocon.control_enabled(True) # heat charcoal
    world.wait(1e15)

STATES_LIST = [
    wait_forever,
    ready_for_cooldown,
    autocool_he3_adr,
    he3_only_cycle,
    he3_adr_cycle,
    he3_adr_resume_at_ramp,
    regulate_temperature,
    ramp_down_magnet,
    warmup_300K,
]
STATES_DICT = {s.name(): s for s in STATES_LIST}

