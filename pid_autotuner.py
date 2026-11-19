#!/usr/bin/env python3
"""
PID Auto-Tuner & Optimization Harness for Lake Shore 370 on 2PAC.
Systematically tests PI parameter configurations, waits 15 minutes per trial,
evaluates stability metrics (RMS, peak-to-peak, drift, saturation),
converges towards optimal regulation, and maintains a persistent library
of known good parameter values in ~/2pac_logs/pid_tuning_library.json and
docs/PID_TUNING_LIBRARY.md.

Usage:
    python3 pid_autotuner.py                 # Run automated tuning loop (15 min/trial)
    python3 pid_autotuner.py --status        # Show summary of all tested parameters
    python3 pid_autotuner.py --once          # Evaluate current settings for 15 min & record
    python3 pid_autotuner.py --p 0.08 --i 250 --duration 15
"""

import sys
import os
from pathlib import Path

# Auto-re-execute using repository .venv if running outside it
_venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
if _venv_python.exists() and sys.executable != str(_venv_python):
    os.execv(str(_venv_python), [str(_venv_python)] + sys.argv)

# Force line-buffered stdout for real-time daemon logging
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

import time
import json
import argparse
from datetime import datetime
import numpy as np

# Directory paths
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = Path.home() / "2pac_logs"
LIBRARY_JSON = LOGS_DIR / "pid_tuning_library.json"
LIBRARY_MD = BASE_DIR / "docs" / "PID_TUNING_LIBRARY.md"
PLOTS_DIR = LOGS_DIR / "tuning_plots"
IPC_DIR = Path.home() / ".2pac" / "ipc"   # private GUI command channel (mode 700), see gui.py
CMD_FILE = IPC_DIR / "gui_command.txt"
STATE_FILE = IPC_DIR / "ls370_state.json"
STOP_FILE = Path("/tmp/stop_pid_autotuner")

# Tuning Safety Bounds (Gentle adjustments only)
P_MIN, P_MAX = 0.001, 10.0   # P 7 was best in true CONTROL (2026-11-17); no ringing seen up to 7
I_MIN, I_MAX = 60.0, 800.0
MAX_DELTA_P_FRAC = 0.25  # Max 25% change per step
MAX_DELTA_I_FRAC = 0.25  # Max 25% change per step


def send_gui_command(line: str, wait_s: float = 0.8) -> None:
    """Send one named command to the running GUI (private channel ~/.2pac/ipc)."""
    with open(CMD_FILE, "a") as f:
        f.write(line.strip() + "\n")
    time.sleep(wait_s)


def query_ls370_state() -> dict:
    """Query live Lake Shore 370 registers via the GUI's read-only query_ls370 command."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    send_gui_command("query_ls370:PID?,CSET?,HTRRNG?,SETP?,HTR?,MOUT?,RDGK? 4", wait_s=0.5)
    for _ in range(30):
        if STATE_FILE.exists():
            try:
                raw = json.loads(STATE_FILE.read_text())
                return {
                    "pid": raw.get("PID?"), "cset": raw.get("CSET?"),
                    "htrrng": int(float(raw.get("HTRRNG?", "0"))), "setp": float(raw.get("SETP?", "nan")),
                    "htr": float(raw.get("HTR?", "nan")), "mout": float(raw.get("MOUT?", "nan")),
                    "t": float(raw.get("RDGK? 4", "nan")), "commanded_mode": raw.get("commanded_mode"),
                }
            except Exception:
                pass
        time.sleep(0.2)
    return {}


def apply_pid_hardware(p: float, i: float, d: float = 0.0, htr_range: str = None) -> bool:
    """Apply PID (and optionally the heater range) via the GUI's validated set_pid command; also syncs gui_settings.json."""
    p_clamped = max(P_MIN, min(P_MAX, float(p)))
    i_clamped = max(I_MIN, min(I_MAX, float(i)))
    d_clamped = max(0.0, min(100.0, float(d)))
    arg = f"{p_clamped:.4f},{i_clamped:.1f},{d_clamped:.1f}" + (f",{htr_range}" if htr_range else "")
    send_gui_command(f"set_pid:{arg}", wait_s=1.2)
    return True


def read_telemetry_window(t_start: float, t_end: float) -> dict:
    """Read FAA temperature and heater output from today's log files within [t_start, t_end]."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    faa_path = LOGS_DIR / today_str / "faa_temperature.log"
    out_path = LOGS_DIR / today_str / "out.log"
    I_path = LOGS_DIR / today_str / "kepco_current.log"

    ts_faa, faa_vals = [], []
    if faa_path.exists():
        with open(faa_path) as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 3:
                    try:
                        epoch = float(p[0])
                        if t_start <= epoch <= t_end:
                            val = float(p[2])
                            if np.isfinite(val) and 0.001 < val < 5.0:
                                ts_faa.append(epoch)
                                faa_vals.append(val)
                    except Exception:
                        pass

    ts_out, out_vals = [], []
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 3:
                    try:
                        epoch = float(p[0])
                        if t_start <= epoch <= t_end:
                            val = float(p[2])
                            if np.isfinite(val):
                                ts_out.append(epoch)
                                out_vals.append(val)
                    except Exception:
                        pass

    ts_I, I_vals = [], []
    if I_path.exists():
        with open(I_path) as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 3:
                    try:
                        epoch = float(p[0])
                        if t_start <= epoch <= t_end:
                            val = float(p[2])
                            if np.isfinite(val):
                                ts_I.append(epoch)
                                I_vals.append(val)
                    except Exception:
                        pass

    return {
        "t_faa": np.array(ts_faa),
        "faa": np.array(faa_vals) * 1000.0,  # in mK
        "t_out": np.array(ts_out),
        "out": np.array(out_vals),           # in %
        "t_I": np.array(ts_I),
        "I": np.array(I_vals) * 1000.0,      # in mA
    }


def compute_metrics(telemetry: dict, setpoint_mk: float, eval_fraction: float = 0.67) -> dict:
    """
    Compute rigorous stability and regulation quality metrics.
    eval_fraction: evaluate only the latter fraction of the window (e.g. last 10 of 15 min)
    to ignore initial step transients.
    """
    faa = telemetry["faa"]
    t_faa = telemetry["t_faa"]
    out = telemetry["out"]
    I_arr = telemetry["I"]

    if len(faa) < 20:
        return {"valid": False, "reason": "Insufficient telemetry points"}

    # Settle filter: discard initial (1 - eval_fraction) of the window
    n_points = len(faa)
    eval_start_idx = int(n_points * (1.0 - eval_fraction))
    faa_eval = faa[eval_start_idx:]
    out_eval = out[int(len(out) * (1.0 - eval_fraction)):] if len(out) > 0 else np.array([])
    I_eval = I_arr[int(len(I_arr) * (1.0 - eval_fraction)):] if len(I_arr) > 0 else np.array([])

    mean_mk = float(np.mean(faa_eval))
    std_uk = float(np.std(faa_eval)) * 1000.0          # RMS around mean (uK)
    ptp_uk = float(np.max(faa_eval) - np.min(faa_eval)) * 1000.0  # Peak-to-peak (uK)
    error_mk = float(abs(mean_mk - setpoint_mk))        # Offset from setpoint (mK)
    rms_from_setpoint_uk = float(np.sqrt(np.mean((faa_eval - setpoint_mk) ** 2))) * 1000.0

    # Output saturation & activity metrics
    zero_power_fraction = float(np.mean(out_eval <= 0.001)) if len(out_eval) > 0 else 0.0
    mean_out = float(np.mean(out_eval)) if len(out_eval) > 0 else 0.0
    out_ptp = float(np.max(out_eval) - np.min(out_eval)) if len(out_eval) > 0 else 0.0
    mean_I_ma = float(np.mean(I_eval)) if len(I_eval) > 0 else 0.0

    # Composite penalty score (lower is better):
    # Combines standard deviation, offset penalty, and saturation penalty
    # Perfect score is < 50
    score = std_uk + (error_mk * 300.0) + (zero_power_fraction * 400.0) + (ptp_uk * 0.1)

    # Classify state
    if zero_power_fraction > 0.15 or ptp_uk > 1500.0:
        diagnosis = "LIMIT_CYCLE_OSCILLATION"
    elif ptp_uk > 600.0:
        diagnosis = "MODERATE_HUNTING"
    elif error_mk > 0.4:
        diagnosis = "STEADY_BUT_OFFSET"
    elif std_uk < 70.0 and error_mk < 0.2:
        diagnosis = "EXCELLENT_CONVERGED"
    elif std_uk < 120.0 and error_mk < 0.3:
        diagnosis = "GOOD_STABLE"
    else:
        diagnosis = "SUBOPTIMAL"

    return {
        "valid": True,
        "n_samples": len(faa_eval),
        "mean_mk": round(mean_mk, 3),
        "setpoint_mk": round(setpoint_mk, 2),
        "error_mk": round(error_mk, 3),
        "std_uk": round(std_uk, 1),
        "ptp_uk": round(ptp_uk, 1),
        "rms_setpoint_uk": round(rms_from_setpoint_uk, 1),
        "mean_out_pct": round(mean_out, 3),
        "out_ptp_pct": round(out_ptp, 3),
        "mean_I_ma": round(mean_I_ma, 2),
        "zero_power_fraction": round(zero_power_fraction, 3),
        "score": round(score, 1),
        "diagnosis": diagnosis,
    }


def load_library() -> list:
    """Load parameter library from JSON."""
    if LIBRARY_JSON.exists():
        try:
            with open(LIBRARY_JSON) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_library(library: list) -> None:
    """Save parameter library to JSON and update markdown table."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LIBRARY_JSON, "w") as f:
        json.dump(library, f, indent=2)

    # Generate Markdown documentation
    LIBRARY_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 2PAC Lake Shore 370 PID Parameter Library",
        "",
        "> **Auto-generated Reference Library**: Records tested PID settings, thermal stability metrics, and convergence rankings on the 2PAC ADR cryostat with the $100\\ \\Omega$ Kepco shunt installed.",
        "",
        "## Summary of Tested Configurations (Ranked by Stability)",
        "",
        "| Rank | Status / Quality | P (Gain) | I (Reset s) | D (s) | Range | Temp RMS (µK) | Peak-to-Peak (µK) | Offset (mK) | Mean HTR (%) | Date / Time |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    # Sort valid entries by score (lowest score first)
    valid_entries = [e for e in library if e.get("metrics", {}).get("valid", False)]
    valid_entries.sort(key=lambda x: x["metrics"].get("score", 9999))

    for idx, entry in enumerate(valid_entries, 1):
        m = entry["metrics"]
        p = entry["params"]["p"]
        i = entry["params"]["i"]
        d = entry["params"].get("d", 0.0)
        rng = entry["params"].get("range", "1mA")
        dt_str = entry.get("timestamp", "")
        status = m.get("diagnosis", "TESTED")
        if m.get("std_uk", 999) < 60:
            badge = f"🌟 **Target (<60 µK)**"
        elif m.get("std_uk", 999) < 100:
            badge = f"✅ **Good (<100 µK)**"
        elif "OSCILLATION" in status or "HUNTING" in status:
            badge = f"⚠️ *Hunting / Oscillating*"
        else:
            badge = f"ℹ️ {status.replace('_', ' ').title()}"

        lines.append(
            f"| **#{idx}** | {badge} | `{p:.4f}` | `{i:.1f}` | `{d:.1f}` | `{rng}` | "
            f"**{m['std_uk']:.1f} µK** | {m['ptp_uk']:.1f} µK | {m['error_mk']:.3f} mK | "
            f"{m['mean_out_pct']:.2f}% | {dt_str} |"
        )

    if not valid_entries:
        lines.append("| — | *No evaluated trials recorded yet* | — | — | — | — | — | — | — | — | — |")

    lines.extend([
        "",
        "---",
        "",
        "## Tuning Guidance for ADR Control with 100 Ω Shunt",
        "1. **Integral Reset Time ($I$)**: In the Lake Shore 370, $I$ is specified in **seconds**. A *smaller* value makes the integrator *faster and more aggressive*. Because the ADR thermal lag is $\\approx 450\\text{--}600\\text{ s}$, setting $I < 100\\text{ s}$ causes persistent limit-cycle hunting. Keep $I \\ge 200\\text{ s}$.",
        "2. **Excitation Range (`1mA` vs `10mA`)**: On the `1mA` range, $80\\text{ mK}$ regulation sits at $\\approx 5\\text{--}7\\%$ output ($10\\times$ higher DAC resolution than the coarse $0.48\\%$ on `10mA`).",
        "3. **Proportional Gain ($P$)**: Keep $P$ between $0.03$ and $0.10$ to prevent sharp current steps from shocking the salt pill.",
        "",
    ])

    with open(LIBRARY_MD, "w") as f:
        f.write("\n".join(lines) + "\n")


def generate_trial_plot(trial_num: int, t_start: float, t_end: float, telemetry: dict, metrics: dict, params: dict) -> Path:
    """Generate diagnostic plot for a 15-minute trial."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        PLOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_path = PLOTS_DIR / f"trial_{trial_num:03d}_{ts_str}.png"

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

        if len(telemetry.get("t_faa", [])) > 0:
            time_faa = [datetime.fromtimestamp(t) for t in telemetry["t_faa"]]
            ax1.plot(time_faa, telemetry["faa"], label="FAA Temp (mK)", color="royalblue", lw=1.5)
            sp = params.get("setpoint", 80.0)
            ax1.axhline(sp, color="red", linestyle="--", alpha=0.7, label=f"Setpoint {sp:.1f} mK")
            ax1.set_ylabel("Temp (mK)")
            ax1.grid(True, alpha=0.3)
            ax1.legend(loc="upper right")
            title = (
                f"Trial #{trial_num} | P={params['p']:.4f}, I={params['i']:.1f}s, D={params.get('d', 0):.1f}s, Range={params.get('range','1mA')}\n"
                f"RMS: {metrics.get('std_uk', 0):.1f} µK | PtP: {metrics.get('ptp_uk', 0):.1f} µK | Offset: {metrics.get('error_mk', 0):.3f} mK | Status: {metrics.get('diagnosis', 'N/A')}"
            )
            ax1.set_title(title, fontsize=11, fontweight="bold")

        if len(telemetry.get("t_out", [])) > 0:
            time_out = [datetime.fromtimestamp(t) for t in telemetry["t_out"]]
            ax2.plot(time_out, telemetry["out"], label="LS370 Output (%)", color="forestgreen", lw=1.5)
            ax2.set_ylabel("Output (%)")
            ax2.grid(True, alpha=0.3)
            ax2.legend(loc="upper right")

        if len(telemetry.get("t_I", [])) > 0:
            time_I = [datetime.fromtimestamp(t) for t in telemetry["t_I"]]
            ax3.plot(time_I, telemetry["I"], label="Kepco Current (mA)", color="darkorange", lw=1.5)
            ax3.set_ylabel("Current (mA)")
            ax3.set_xlabel("Time")
            ax3.grid(True, alpha=0.3)
            ax3.legend(loc="upper right")

        plt.tight_layout()
        plt.savefig(plot_path, dpi=120)

        # Copy to brain artifact directory if accessible
        brain_path = Path("/home/pcuser/.gemini/antigravity/brain/f96bc275-b743-4e98-8ffb-2bec1d4916d6")
        if brain_path.exists():
            import shutil
            shutil.copy2(plot_path, brain_path / "latest_tuning_trial.png")

        plt.close(fig)
        return plot_path
    except Exception as e:
        print(f"Warning: could not generate trial plot: {e}")
        return None


def propose_next_parameters(current_p: float, current_i: float, current_range: str, metrics: dict, history: list) -> tuple:
    """
    Intelligently converge towards optimal parameters based on feedback.
    Applies small, conservative steps ('dont make very large changes').
    """
    if not metrics.get("valid", False):
        return current_p, current_i, current_range

    diag = metrics.get("diagnosis", "")
    std = metrics.get("std_uk", 100.0)
    ptp = metrics.get("ptp_uk", 500.0)
    err = metrics.get("error_mk", 0.0)
    zfrac = metrics.get("zero_power_fraction", 0.0)

    p_next = current_p
    i_next = current_i
    rng_next = current_range

    # Rule 1: Limit cycle oscillation / hard saturation (output hitting 0% or huge ptp)
    # The integrator is winding up too fast or gain is too high.
    if zfrac > 0.05 or ptp > 1000.0 or diag == "LIMIT_CYCLE_OSCILLATION":
        i_next = min(I_MAX, current_i * 1.25)
        p_next = max(P_MIN, current_p * 0.85)

    # Rule 2: Moderate hunting (ptp > 400 uK or slight zero-power clipping)
    elif ptp > 400.0 or zfrac > 0.01 or diag == "MODERATE_HUNTING":
        i_next = min(I_MAX, current_i * 1.15)
        p_next = max(P_MIN, current_p * 0.90)

    # Rule 3: Target achieved! Ultra-low noise (< 50 uK) and close to setpoint (err <= 0.10 mK)
    # Lock in and hold the winning parameters!
    elif std < 50.0 and err <= 0.10:
        p_next = current_p
        i_next = current_i

    # Rule 4: Residual steady-state offset (> 0.10 mK) with low hunting (ptp <= 350 uK)
    # Controller is too sluggish; speed up integrator and increase proportional pushback
    elif err > 0.10 and ptp <= 350.0:
        i_next = max(220.0, current_i * 0.80)  # Speed up integrator (safe floor >= 220s)
        p_next = min(0.10, current_p * 1.20)   # Increase proportional restoring authority

    # Rule 5: Low offset but residual ripple / hunting
    elif std >= 50.0 and ptp <= 400.0:
        p_next = max(P_MIN, current_p * 0.92)

    else:
        p_next = current_p
        i_next = current_i

    # Enforce gentle maximum step clamps (max 25% change per 15 min trial)
    p_step_max = current_p * MAX_DELTA_P_FRAC
    i_step_max = current_i * MAX_DELTA_I_FRAC

    p_next = max(current_p - p_step_max, min(current_p + p_step_max, p_next))
    i_next = max(current_i - i_step_max, min(current_i + i_step_max, i_next))

    p_next = max(P_MIN, min(P_MAX, round(p_next, 4)))
    i_next = max(I_MIN, min(I_MAX, round(i_next, 1)))

    return p_next, i_next, rng_next


def run_tuning_loop(args):
    print("=" * 70)
    print(" 2PAC Lake Shore 370 Automated PID Optimizer & Library Builder")
    print(f" Trial Duration: {args.duration} minutes | Target Setpoint: {args.setpoint:.2f} mK")
    print("=" * 70)

    if STOP_FILE.exists():
        STOP_FILE.unlink()

    library = load_library()
    print(f"Loaded existing parameter library: {len(library)} recorded trials.")

    # Determine starting parameters
    cur_state = query_ls370_state()
    p_curr = args.p if args.p is not None else 0.08
    i_curr = args.i if args.i is not None else 250.0
    d_curr = args.d if args.d is not None else 0.0
    rng_curr = args.range if args.range is not None else "1mA"
    sp_mk = args.setpoint

    trial_num = 1
    max_trials = args.max_trials if args.max_trials > 0 else 9999

    while trial_num <= max_trials:
        if STOP_FILE.exists():
            print("\n[STOP SIGNAL DETECTED] Gracefully exiting autotuner loop.")
            STOP_FILE.unlink()
            break

        print(f"\n>>> Starting Trial #{trial_num} of {max_trials if max_trials < 9999 else '∞'}")
        print(f"    Testing: P = {p_curr:.4f}, I = {i_curr:.1f} s, D = {d_curr:.1f} s, Range = {rng_curr}")
        print(f"    Applying settings to Lake Shore 370...")

        apply_pid_hardware(p_curr, i_curr, d_curr, rng_curr)
        t_start = time.time()
        trial_duration_s = float(args.duration) * 60.0
        t_end = t_start + trial_duration_s

        dt_start_str = datetime.fromtimestamp(t_start).strftime("%H:%M:%S")
        print(f"    Trial started at {dt_start_str}. Waiting {args.duration} minutes while collecting telemetry...")

        # Progress wait loop (prints status every 60s)
        while time.time() < t_end:
            if STOP_FILE.exists():
                break
            rem_s = int(t_end - time.time())
            time.sleep(min(30.0, rem_s))
            live = query_ls370_state()
            live_t = live.get("t", 0.0) * 1000.0
            live_out = live.get("htr", 0.0)
            print(f"    [{int(trial_duration_s - rem_s)}s / {int(trial_duration_s)}s] Live FAA: {live_t:.2f} mK | Out: {live_out:.2f}% | Rem: {rem_s//60}m {rem_s%60}s")

        t_actual_end = time.time()
        print(f"\n    15-minute trial complete. Processing telemetry and computing metrics...")

        # Read telemetry and compute metrics for the trial
        telemetry = read_telemetry_window(t_start, t_actual_end)
        metrics = compute_metrics(telemetry, setpoint_mk=sp_mk, eval_fraction=0.67)

        if metrics.get("valid", False):
            print(f"    --- Trial #{trial_num} Results ---")
            print(f"    Status:     {metrics['diagnosis']}")
            print(f"    RMS Std:    {metrics['std_uk']} µK rms")
            print(f"    Peak-to-Peak: {metrics['ptp_uk']} µK")
            print(f"    Mean Temp:  {metrics['mean_mk']} mK (Error: {metrics['error_mk']} mK)")
            print(f"    Mean Out:   {metrics['mean_out_pct']}% (Sat fraction: {metrics['zero_power_fraction']*100:.1f}%)")
            print(f"    Score:      {metrics['score']}")
        else:
            print(f"    [WARNING] Evaluation invalid: {metrics.get('reason')}")

        # Generate trial plot
        trial_params = {"p": p_curr, "i": i_curr, "d": d_curr, "range": rng_curr, "setpoint": sp_mk}
        plot_path = generate_trial_plot(trial_num, t_start, t_actual_end, telemetry, metrics, trial_params)
        if plot_path:
            print(f"    Diagnostic plot saved: {plot_path}")

        # Record trial in library
        record = {
            "trial_num": len(library) + 1,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "params": {
                "p": round(p_curr, 4),
                "i": round(i_curr, 1),
                "d": round(d_curr, 1),
                "range": rng_curr,
            },
            "metrics": metrics,
            "plot": str(plot_path) if plot_path else None,
        }
        library.append(record)
        save_library(library)
        print(f"    Saved record to {LIBRARY_JSON} and updated {LIBRARY_MD}")

        if args.once:
            print("Executed single trial (--once). Exiting.")
            break

        # Propose next set of parameters
        p_next, i_next, rng_next = propose_next_parameters(p_curr, i_curr, rng_curr, metrics, library)
        print(f"    Convergence step: Next proposed -> P = {p_next:.4f}, I = {i_next:.1f} s (Range: {rng_next})")

        p_curr, i_curr, rng_curr = p_next, i_next, rng_next
        trial_num += 1


def show_status():
    """Print current library summary."""
    library = load_library()
    if not library:
        print("No trials recorded in library yet.")
        return

    valid_entries = [e for e in library if e.get("metrics", {}).get("valid", False)]
    valid_entries.sort(key=lambda x: x["metrics"].get("score", 9999))

    print(f"\n=======================================================")
    print(f" 2PAC PID Parameter Library ({len(library)} Total Trials)")
    print(f"=======================================================")
    print(f"{'Rank':<5} {'P':<8} {'I (s)':<8} {'Range':<7} {'RMS (uK)':<10} {'PtP (uK)':<10} {'Offset':<8} {'Diagnosis'}")
    print("-" * 70)
    for idx, e in enumerate(valid_entries, 1):
        m = e["metrics"]
        p = e["params"]["p"]
        i = e["params"]["i"]
        rng = e["params"].get("range", "1mA")
        print(f"#{idx:<4} {p:<8.4f} {i:<8.1f} {rng:<7} {m['std_uk']:<10.1f} {m['ptp_uk']:<10.1f} {m['error_mk']:<8.3f} {m['diagnosis']}")
    print("-" * 70)
    if valid_entries:
        best = valid_entries[0]
        print(f"Current Best: P={best['params']['p']}, I={best['params']['i']}s, Range={best['params']['range']} -> {best['metrics']['std_uk']} uK rms")


def main():
    parser = argparse.ArgumentParser(description="2PAC Lake Shore 370 PID Auto-Tuner & Optimization Harness")
    parser.add_argument("--duration", type=float, default=15.0, help="Trial duration in minutes (default: 15.0)")
    parser.add_argument("--setpoint", type=float, default=80.0, help="Target setpoint in mK (default: 80.0)")
    parser.add_argument("--p", type=float, default=None, help="Initial P gain (default: 0.08)")
    parser.add_argument("--i", type=float, default=None, help="Initial I reset seconds (default: 250.0)")
    parser.add_argument("--d", type=float, default=0.0, help="Derivative seconds (default: 0.0)")
    parser.add_argument("--range", type=str, default="1mA", help="Heater excitation range (default: 1mA)")
    parser.add_argument("--max-trials", type=int, default=0, help="Max trials to run (0 = infinite)")
    parser.add_argument("--once", action="store_true", help="Run a single 15-minute trial and exit")
    parser.add_argument("--status", action="store_true", help="Show library status table and exit")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    run_tuning_loop(args)


if __name__ == "__main__":
    main()
