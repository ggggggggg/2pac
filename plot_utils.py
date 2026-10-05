import numpy as np
import matplotlib.colors as mc
import colorsys
from datetime import datetime
from matplotlib.ticker import FuncFormatter, FormatStrFormatter, MultipleLocator
from matplotlib.gridspec import GridSpec

def adjust_lightness(color, amount=0.5):
    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, amount * c[1])), c[2])

TAB_GROUPS = {
    "Main": [
        "cryocon_chA_temperature",
        "cryocon_chB_temperature",
        "cryocon_chC_temperature",
        "cryocon_chD_temperature",
        "faa_temperature",
        "labjack_he3_pressure",
        "labjack_kepco_current",
    ],
    "Thermometers": [
        "cryocon_chA_temperature",
        "cryocon_chB_temperature",
        "cryocon_chC_temperature",
        "cryocon_chD_temperature",
        "faa_temperature",
    ],
    "Pressures": [
        "labjack_he3_pressure",
    ],
    "Utils": [
        "labjack_kepco_current",
        "labjack_kepco_voltage",
        "ls370_heater_out",
    ],
}

TAB_YLABELS = {
    "Main": "Overview",
    "Thermometers": "Temperature (K)",
    "Pressures": "Pressure",
    "Utils": "Value",
}

# Theming definitions for Light and Dark modes
THEMES = {
    "dark": {
        "fig_bg": "#0f172a",
        "ax_bg": "#1e293b",
        "spine": "#334155",
        "grid": "#334155",
        "grid_alpha": 0.6,
        "text": "#f8fafc",
        "subtext": "#94a3b8",
        "tick_color": "#cbd5e1",
        "crosshair": "#64748b",
        "legend_bg": "#0f172a",
        "legend_edge": "#334155",
        "legend_text": "#f8fafc",
        "channel_colors": {
            "cryocon_chA_temperature": "#38bdf8",     # Bright Cyan Blue (4K)
            "cryocon_chB_temperature": "#fbbf24",     # Amber Gold (Charcoal)
            "cryocon_chC_temperature": "#34d399",     # Emerald Green (Pot)
            "cryocon_chD_temperature": "#c084fc",     # Bright Purple (ChD)
            "faa_temperature": "#f87171",             # Crimson Rose (FAA)
            "labjack_he3_pressure": "#60a5fa",        # Royal Blue (He3 Pressure)
            "labjack_kepco_current": "#38bdf8",       # Bright Cyan (Kepco I)
            "labjack_kepco_voltage": "#f59e0b",       # Amber Yellow (Kepco V)
            "ls370_heater_out": "#f472b6",            # Neon Pink (LS370 Heater)
            "labjack_heatswitch_adr": "#a78bfa",      # Bright Violet (HS ADR)
            "labjack_heatswitch_charcoal": "#4ade80", # Bright Green (HS Charcoal)
            "labjack_heatswitch_pot": "#fb923c",      # Bright Orange (HS Pot)
            "labjack_relay": "#e879f9",               # Fuchsia (Relay)
        }
    },
    "light": {
        "fig_bg": "#ffffff",
        "ax_bg": "#ffffff",
        "spine": "#cbd5e1",
        "grid": "#e2e8f0",
        "grid_alpha": 0.8,
        "text": "#0f172a",
        "subtext": "#64748b",
        "tick_color": "#334155",
        "crosshair": "#94a3b8",
        "legend_bg": "#ffffff",
        "legend_edge": "#cbd5e1",
        "legend_text": "#0f172a",
        "channel_colors": {
            "cryocon_chA_temperature": "#0284c7",     # Deep Sky Blue (4K)
            "cryocon_chB_temperature": "#d97706",     # Warm Amber / Bronze (Charcoal)
            "cryocon_chC_temperature": "#059669",     # Forest / Emerald Green (Pot)
            "cryocon_chD_temperature": "#7c3aed",     # Vivid Purple (ChD)
            "faa_temperature": "#dc2626",             # Crimson Red (FAA)
            "labjack_he3_pressure": "#2563eb",        # Deep Royal Blue (He3 Pressure)
            "labjack_kepco_current": "#0891b2",       # Deep Cyan (Kepco I)
            "labjack_kepco_voltage": "#d97706",       # Amber (Kepco V)
            "ls370_heater_out": "#db2777",            # Deep Magenta / Pink (LS370 Heater)
            "labjack_heatswitch_adr": "#6d28d9",      # Violet (HS ADR)
            "labjack_heatswitch_charcoal": "#16a34a", # Forest Green (HS Charcoal)
            "labjack_heatswitch_pot": "#ea580c",      # Dark Orange (HS Pot)
            "labjack_relay": "#c026d3",               # Deep Fuchsia (Relay)
        }
    }
}

# Default backwards-compatible channel colors (Light mode default)
CHANNEL_COLORS = THEMES["light"]["channel_colors"]
DARK_CHANNEL_COLORS = THEMES["dark"]["channel_colors"]


# Default channel aliases — updated by the Settings tab
CHANNEL_ALIASES = {
    "cryocon_chA_temperature": "4K",
    "cryocon_chB_temperature": "Charcoal",
    "cryocon_chC_temperature": "Pot",
    "cryocon_chD_temperature": "ChD",
    "faa_temperature": "FAA",
    "labjack_he3_pressure": "He3 Pressure",
    "labjack_kepco_current": "Magnet Current",
    "labjack_kepco_voltage": "Kepco V",
    "ls370_heater_out": "LS370 Heater",
    "labjack_heatswitch_adr": "HS ADR",
    "labjack_heatswitch_charcoal": "HS Charcoal",
    "labjack_heatswitch_pot": "HS Pot",
    "labjack_relay": "Relay",
}

def display_name(key):
    """Return the alias for a channel key, or the key itself."""
    return CHANNEL_ALIASES.get(key, key)

def get_time_tick_step(span_s):
    """Return an integer multiple of 60 seconds (minutes/hours) for clean X-axis time ticks without seconds."""
    if span_s is None or span_s <= 300:
        return 60           # 1 min
    elif span_s <= 900:
        return 120          # 2 min
    elif span_s <= 2400:
        return 300          # 5 min
    elif span_s <= 7200:
        return 600          # 10 min
    elif span_s <= 18000:
        return 1800         # 30 min
    elif span_s <= 43200:
        return 3600         # 1 hr
    elif span_s <= 86400:
        return 7200         # 2 hrs
    else:
        return 14400        # 4 hrs

def epoch_to_local_str(epoch_s, span_s=None, include_seconds=False):
    """Convert epoch seconds or relative seconds to readable local time string without seconds by default."""
    try:
        if epoch_s is None or np.isnan(epoch_s):
            return ""
        if epoch_s < 1e8:  # Relative seconds (elapsed time)
            m, s = divmod(int(epoch_s), 60)
            h, m = divmod(m, 60)
            if include_seconds:
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            else:
                return f"{h:02d}:{m:02d}" if h > 0 else f"{m:02d}m"
        dt = datetime.fromtimestamp(epoch_s)
        if span_s is not None and span_s > 86400:
            return dt.strftime("%m-%d %H:%M")
        if include_seconds:
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%H:%M")
    except Exception:
        return ""

def get_dataset_units(dataset):
    """Cache dataset parameters/units to avoid repeated SQLite queries on every tick."""
    if dataset is None:
        return {}
    if not hasattr(dataset, "_cached_units"):
        try:
            dataset._cached_units = {param_spec.name: param_spec.unit for param_spec in dataset.get_parameters()}
        except Exception:
            dataset._cached_units = {}
    return dataset._cached_units

def get_time_vector(dataset, data):
    """
    Extract a robust time vector (x-axis) from a QCoDeS dataset and cache data dict.
    Returns np.ndarray or None.
    """
    if not data:
        return None

    raw_t = None

    # 1. Top-level 'time' parameter
    if "time" in data and "time" in data["time"] and len(data["time"]["time"]) > 0:
        raw_t = np.array(data["time"]["time"], dtype=float)

    # 2. Check setpoints across any parameter inner dict
    if raw_t is None or len(raw_t) == 0:
        start_ts = getattr(dataset, "run_timestamp_raw", None) if dataset else None
        if start_ts is None and dataset and hasattr(dataset, "run_timestamp"):
            try:
                ts_str = dataset.run_timestamp()
                if ts_str:
                    start_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                start_ts = None

        for key, inner in data.items():
            if "time" in inner and len(inner["time"]) > 0:
                raw_t = np.array(inner["time"], dtype=float)
                break
            elif "elapsed_time" in inner and len(inner["elapsed_time"]) > 0:
                elapsed = np.array(inner["elapsed_time"], dtype=float)
                if start_ts is not None:
                    raw_t = start_ts + elapsed
                else:
                    raw_t = elapsed
                break

    # 3. Fallback to index numbers if data exists
    if raw_t is None or len(raw_t) == 0:
        for key, inner in data.items():
            if key in inner and len(inner[key]) > 0:
                raw_t = np.arange(len(inner[key]), dtype=float)
                break

    if raw_t is None or len(raw_t) == 0:
        return None

    # Crucial sanitization: If this is an epoch timestamp array (any point > 1e8),
    # ensure any points <= 0 or < 1e8 (e.g. uninitialized zeros) are repaired
    # so they NEVER corrupt the x-axis limits back to 1970!
    if (raw_t > 1e8).any():
        valid_mask = raw_t > 1e8
        if not valid_mask.all():
            first_valid = raw_t[valid_mask][0]
            raw_t = np.where(valid_mask, raw_t, first_valid)

    return raw_t

def get_temp_keys(data):
    known_temps = [
        "cryocon_chA_temperature",
        "cryocon_chB_temperature",
        "cryocon_chC_temperature",
        "cryocon_chD_temperature",
        "faa_temperature",
    ]
    found = [k for k in known_temps if k in data and k in data[k] and len(data[k][k]) > 0]
    if not found:
        found = [k for k in data.keys() if k not in ("time", "elapsed_time", "state")
                 and ("temp" in k.lower() or "ls370" in k.lower() or "cryocon" in k.lower())
                 and k in data[k] and len(data[k][k]) > 0]
    if not found:
        found = [k for k in data.keys() if k not in ("time", "elapsed_time", "state")
                 and k in data[k] and len(data[k][k]) > 0]
    return found

def get_pressure_key(data):
    if "labjack_he3_pressure" in data and "labjack_he3_pressure" in data["labjack_he3_pressure"] and len(data["labjack_he3_pressure"]["labjack_he3_pressure"]) > 0:
        return "labjack_he3_pressure"
    for k in data.keys():
        if k not in ("time", "elapsed_time", "state") and ("pressure" in k.lower() or "pres" in k.lower()):
            if k in data[k] and len(data[k][k]) > 0:
                return k
    return "labjack_he3_pressure"

def get_kepco_i_key(data):
    if "labjack_kepco_current" in data and "labjack_kepco_current" in data["labjack_kepco_current"] and len(data["labjack_kepco_current"]["labjack_kepco_current"]) > 0:
        return "labjack_kepco_current"
    for k in data.keys():
        if k not in ("time", "elapsed_time", "state") and ("current" in k.lower() or "kepco" in k.lower()):
            if k in data[k] and len(data[k][k]) > 0:
                return k
    return "labjack_kepco_current"

def decimate_for_plot(x, v, max_pts=4000):
    """
    Decimate large arrays for fast interactive plotting while retaining
    the full 1:1 resolution on the most recent telemetry points.
    """
    n = min(len(x), len(v))
    if n <= max_pts:
        return x[:n], v[:n]
    
    # Keep the latest 200 points without downsampling for real-time fidelity
    recent_len = min(200, n // 5)
    hist_n = n - recent_len
    
    step = int(np.ceil(hist_n / (max_pts - recent_len)))
    hist_idx = np.arange(0, hist_n, step)
    recent_idx = np.arange(hist_n, n)
    all_idx = np.concatenate([hist_idx, recent_idx])
    return x[all_idx], v[all_idx]

def safe_plot(ax, x, v, **kwargs):
    """Plot x vs v safely trimming arrays to matching lengths and downsampling if large."""
    if len(x) == 0 or len(v) == 0:
        return
    n = min(len(x), len(v))
    x_sub = x[:n]
    v_sub = v[:n]
    
    # Filter out corrupted pre-epoch points if this is an epoch vector
    if len(x_sub) > 0 and np.nanmax(x_sub) > 1e8:
        valid_x = x_sub > 1e8
        x_sub = x_sub[valid_x]
        v_sub = v_sub[valid_x]
        
    if len(x_sub) == 0:
        return
        
    if len(x_sub) > 4000:
        x_sub, v_sub = decimate_for_plot(x_sub, v_sub, max_pts=4000)
        
    return ax.plot(x_sub, v_sub, **kwargs)

def plot_dataset(figure, dataset, xloc_mouse=None, filter_tab="Main", temp_scale="log", time_window="All Time", theme="light"):
    """
    Plot dataset on figure with modern light or dark mode styling.
    - Main tab: All temperatures on left; He3 Pressure and Magnet Current as a 2x1 stack on right.
    - Thermometers tab: All temperatures overlaid in 1 single plot.
    - Pressures tab: 1 full-sized subplot.
    - Utils tab: Subplots for Kepco V, LS370 Heater, Heat Switches & Relay.
    Supports temp_scale: "log" or "linear".
    Supports time_window: "Last 1 Hour", "Last 6 Hours", "Last 24 Hours", "All Time".
    Supports theme: "light" or "dark".
    Returns (data_mr, data_xloc, units, keys_to_plot, axes_list).
    """
    thm = THEMES.get(theme, THEMES["light"])
    ch_colors = thm["channel_colors"]

    figure.clf()
    figure.set_facecolor(thm["fig_bg"])
    
    data = {}
    x = np.array([])
    if dataset is not None:
        try:
            data = dataset.cache.data()
            t = get_time_vector(dataset, data)
            if t is not None:
                x = t
        except Exception as e:
            print(f"Dataset access error: {e}")

    xloc_ind = None
    data_xloc = None
    if xloc_mouse is not None and len(x) > 0:
        xloc_ind = np.argmin(np.abs(x - xloc_mouse))
        data_xloc = {key: data[key][key][xloc_ind] for key in data.keys() if key in data and key in data[key] and len(data[key][key]) > xloc_ind}
        
    data_mr = {}
    for key in data.keys():
        if key in data and key in data[key] and len(data[key][key]) > 0:
            data_mr[key] = data[key][key][-1]

    keys_hs = ["labjack_heatswitch_adr", "labjack_heatswitch_charcoal", "labjack_heatswitch_pot", "labjack_relay"]
    units = get_dataset_units(dataset)

    # Determine time window xlims
    window_s = None
    if time_window in ("1 Hour", "Last 1 Hour"):
        window_s = 3600
    elif time_window in ("6 Hours", "Last 6 Hours"):
        window_s = 21600
    elif time_window in ("24 Hours", "Last 24 Hours"):
        window_s = 86400

    target_xlim = None
    if len(x) > 0:
        x_end = x[-1]
        if window_s is not None:
            x_start = x_end - window_s
            target_xlim = (x_start, x_end + max(60, (x_end - x_start) * 0.02))
        else:
            # "All Time" mode: align to clean minute boundaries with at least 120s span
            x_min_aligned = float(np.floor(x[0] / 60.0) * 60.0)
            x_max_aligned = float(np.ceil(x_end / 60.0) * 60.0)
            if (x_max_aligned - x_min_aligned) < 120.0:
                x_max_aligned = x_min_aligned + 120.0
            target_xlim = (x_min_aligned, x_max_aligned)

    span_for_format = (target_xlim[1] - target_xlim[0]) if target_xlim else 3600

    axes_list = []
    
    if filter_tab in ("Main", "Overview"):
        # Left plot (spans 2 rows): All Temperatures in 1 plot
        # Right stack (2 rows, 1 col): Top=He3 Pressure, Bottom=Magnet Current (Kepco I)
        gs = GridSpec(2, 2, figure=figure, width_ratios=[1.3, 1.0], hspace=0.15, wspace=0.14,
                      left=0.06, right=0.98, top=0.95, bottom=0.09)
        ax_temp = figure.add_subplot(gs[0:2, 0])
        ax_he3 = figure.add_subplot(gs[0, 1], sharex=ax_temp)
        ax_kepco_i = figure.add_subplot(gs[1, 1], sharex=ax_temp)

        axes_list = [ax_temp, ax_he3, ax_kepco_i]
        
        # Style all subplots for current theme
        for ax in axes_list:
            ax.set_facecolor(thm["ax_bg"])
            for spine in ax.spines.values():
                spine.set_color(thm["spine"])
                spine.set_linewidth(1.0)
            ax.grid(True, which="both", axis="both", color=thm["grid"], linestyle="--", alpha=thm["grid_alpha"])
            ax.tick_params(axis="both", colors=thm["tick_color"], labelsize=8.5, labelleft=True)

        step = get_time_tick_step(span_for_format)

        # 1. Plot all Temperatures on ax_temp
        temp_keys = get_temp_keys(data)
        all_temp_vals = []
        for key in temp_keys:
            if key in data and key in data[key] and len(data[key][key]) > 0:
                v = np.array(data[key][key], dtype=float)
                pos = v[np.isfinite(v) & (v > 0)]
                if len(pos) > 0:
                    all_temp_vals.append(pos)
                color = ch_colors.get(key, "#0284c7")
                name = display_name(key)
                safe_plot(ax_temp, x, v, color=color, lw=1.8, label=name)
        
        if temp_scale == "log":
            ax_temp.set_yscale("log")
            if all_temp_vals:
                combined = np.concatenate(all_temp_vals)
                t_min = max(0.01, float(np.min(combined)) * 0.75)
                t_max = max(10.0, float(np.max(combined)) * 1.25)
                ax_temp.set_ylim(bottom=t_min, top=t_max)
            else:
                ax_temp.set_ylim(bottom=0.01, top=350)
            ax_temp.set_ylabel("Temperature (K)", color=thm["tick_color"], fontsize=9, fontweight="bold")
        else:
            ax_temp.set_yscale("linear")
            ax_temp.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
            if all_temp_vals:
                combined = np.concatenate(all_temp_vals)
                t_max = max(10.0, float(np.max(combined)) * 1.05)
                ax_temp.set_ylim(bottom=0.0, top=t_max)
            else:
                ax_temp.set_ylim(bottom=0.0, top=350)
            ax_temp.set_ylabel("Temperature (K)", color=thm["tick_color"], fontsize=9, fontweight="bold")

        ax_temp.set_title("Temperatures", loc="left", fontsize=10, fontweight="bold", color=thm["text"], pad=4)
        if temp_keys and len(x) > 0:
            ax_temp.legend(loc="upper left", fontsize=8, facecolor=thm["legend_bg"], edgecolor=thm["legend_edge"], labelcolor=thm["legend_text"], framealpha=0.9)
        ax_temp.xaxis.set_major_locator(MultipleLocator(step))
        ax_temp.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: epoch_to_local_str(val, span_s=span_for_format, include_seconds=False)))
        ax_temp.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax_temp.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)

        # 2. Plot He3 Pressure on ax_he3 (Top Right)
        he3_key = get_pressure_key(data)
        ax_he3.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
        color_he3 = ch_colors.get(he3_key, "#2563eb")
        if he3_key in data and he3_key in data[he3_key] and len(data[he3_key][he3_key]) > 0:
            v = np.array(data[he3_key][he3_key], dtype=float)
            safe_plot(ax_he3, x, v, color=color_he3, lw=1.8)
        ax_he3.set_title(display_name(he3_key), loc="left", fontsize=9.5, fontweight="bold", color=color_he3, pad=4)
        ax_he3.set_ylabel("Pressure (bar)", color=thm["tick_color"], fontsize=8.5, fontweight="bold")
        ax_he3.tick_params(axis="x", labelbottom=False)

        # 3. Plot Magnet Current (Kepco I) on ax_kepco_i (Bottom Right)
        kepco_key = get_kepco_i_key(data)
        ax_kepco_i.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
        color_kepco = ch_colors.get(kepco_key, "#0891b2")
        unit = units.get(kepco_key, "A")
        if kepco_key in data and kepco_key in data[kepco_key] and len(data[kepco_key][kepco_key]) > 0:
            v = np.array(data[kepco_key][kepco_key], dtype=float)
            safe_plot(ax_kepco_i, x, v, color=color_kepco, lw=1.8)
        ax_kepco_i.set_title(display_name(kepco_key), loc="left", fontsize=9.5, fontweight="bold", color=color_kepco, pad=4)
        ax_kepco_i.set_ylabel(f"Current ({unit})", color=thm["tick_color"], fontsize=8.5, fontweight="bold")
        ax_kepco_i.xaxis.set_major_locator(MultipleLocator(step))
        ax_kepco_i.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: epoch_to_local_str(val, span_s=span_for_format, include_seconds=False)))
        ax_kepco_i.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax_kepco_i.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)

        if target_xlim is not None:
            ax_temp.set_xlim(target_xlim)

        # Add hover crosshair to all 3 axes
        if data_xloc is not None and xloc_ind is not None:
            for ax in axes_list:
                ax.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

        keys_to_plot = temp_keys + ["labjack_he3_pressure", "labjack_kepco_current"]
        return (data_mr, data_xloc, units, keys_to_plot, axes_list)

    elif filter_tab in ("Thermometers", "Temperatures"):
        figure.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.09)
        ax = figure.add_subplot(1, 1, 1)
        axes_list = [ax]
        ax.set_facecolor(thm["ax_bg"])
        for spine in ax.spines.values():
            spine.set_color(thm["spine"])
            spine.set_linewidth(1.0)
        ax.grid(True, which="both", axis="both", color=thm["grid"], linestyle="--", alpha=thm["grid_alpha"])
        ax.tick_params(axis="both", colors=thm["tick_color"], labelsize=8.5, labelleft=True)

        step = get_time_tick_step(span_for_format)

        temp_keys = get_temp_keys(data)
        all_temp_vals = []
        for key in temp_keys:
            if key in data and key in data[key] and len(data[key][key]) > 0:
                v = np.array(data[key][key], dtype=float)
                pos = v[np.isfinite(v) & (v > 0)]
                if len(pos) > 0:
                    all_temp_vals.append(pos)
                color = ch_colors.get(key, "#0284c7")
                name = display_name(key)
                safe_plot(ax, x, v, color=color, lw=1.8, label=name)

        if temp_scale == "log":
            ax.set_yscale("log")
            if all_temp_vals:
                combined = np.concatenate(all_temp_vals)
                t_min = max(0.01, float(np.min(combined)) * 0.75)
                t_max = max(10.0, float(np.max(combined)) * 1.25)
                ax.set_ylim(bottom=t_min, top=t_max)
            else:
                ax.set_ylim(bottom=0.01, top=350)
            ax.set_ylabel("Temperature (K)", color=thm["tick_color"], fontsize=9, fontweight="bold")
        else:
            ax.set_yscale("linear")
            ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
            if all_temp_vals:
                combined = np.concatenate(all_temp_vals)
                t_max = max(10.0, float(np.max(combined)) * 1.05)
                ax.set_ylim(bottom=0.0, top=t_max)
            else:
                ax.set_ylim(bottom=0.0, top=350)
            ax.set_ylabel("Temperature (K)", color=thm["tick_color"], fontsize=9, fontweight="bold")

        ax.set_title("All Thermometers", loc="left", fontsize=10, fontweight="bold", color=thm["text"], pad=4)
        if temp_keys and len(x) > 0:
            ax.legend(loc="upper left", fontsize=8.5, facecolor=thm["legend_bg"], edgecolor=thm["legend_edge"], labelcolor=thm["legend_text"], framealpha=0.9)
        ax.xaxis.set_major_locator(MultipleLocator(step))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: epoch_to_local_str(val, span_s=span_for_format, include_seconds=False)))
        ax.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)

        if target_xlim is not None:
            ax.set_xlim(target_xlim)

        if data_xloc is not None and xloc_ind is not None:
            ax.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

        return (data_mr, data_xloc, units, temp_keys, axes_list)

    elif filter_tab in ("Pressures", "Pressure"):
        figure.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.09)
        ax = figure.add_subplot(1, 1, 1)
        axes_list = [ax]
        ax.set_facecolor(thm["ax_bg"])
        for spine in ax.spines.values():
            spine.set_color(thm["spine"])
            spine.set_linewidth(1.0)
        ax.grid(True, which="both", axis="both", color=thm["grid"], linestyle="--", alpha=thm["grid_alpha"])
        ax.tick_params(axis="both", colors=thm["tick_color"], labelsize=8.5, labelleft=True)
        ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))

        step = get_time_tick_step(span_for_format)

        key = get_pressure_key(data)
        color = ch_colors.get(key, "#2563eb")
        name = display_name(key)
        if key in data and key in data[key] and len(data[key][key]) > 0:
            v = np.array(data[key][key], dtype=float)
            safe_plot(ax, x, v, color=color, lw=1.8)
        ax.set_title(name, loc="left", fontsize=10, fontweight="bold", color=color, pad=4)
        ax.set_ylabel("Pressure (bar)", color=thm["tick_color"], fontsize=9, fontweight="bold")

        ax.xaxis.set_major_locator(MultipleLocator(step))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: epoch_to_local_str(val, span_s=span_for_format, include_seconds=False)))
        ax.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)

        if target_xlim is not None:
            ax.set_xlim(target_xlim)

        if data_xloc is not None and xloc_ind is not None:
            ax.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

        return (data_mr, data_xloc, units, [key], axes_list)

    else:  # "Utils" / "Diagnostics"
        figure.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.09, hspace=0.15)
        channel_list = [
            "labjack_kepco_voltage",
            "ls370_heater_out",
            "heat_switches",
        ]
        step = get_time_tick_step(span_for_format)
        first_ax = None
        for idx, ch_key in enumerate(channel_list):
            if idx == 0:
                ax = figure.add_subplot(len(channel_list), 1, idx + 1)
                first_ax = ax
            else:
                ax = figure.add_subplot(len(channel_list), 1, idx + 1, sharex=first_ax)

            axes_list.append(ax)
            ax.set_facecolor(thm["ax_bg"])
            for spine in ax.spines.values():
                spine.set_color(thm["spine"])
                spine.set_linewidth(1.0)
            ax.grid(True, which="both", axis="both", color=thm["grid"], linestyle="--", alpha=thm["grid_alpha"])
            ax.tick_params(axis="both", colors=thm["tick_color"], labelsize=8.5, labelleft=True)
            ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))

            if ch_key == "heat_switches":
                base_colors = [ch_colors.get(k, "#7c3aed") for k in keys_hs]
                for i, key in enumerate(keys_hs):
                    if key not in data or key not in data[key]:
                        continue
                    if key == "labjack_relay":
                        v_open = np.array([d == "CONTROL" for d in data[key][key]])
                        v_closed = np.array([d == "RAMP" for d in data[key][key]])
                        v_unknown = np.array([d == "UNKNOWN" for d in data[key][key]])
                    else:
                        v_open = np.array([d == "OPEN" for d in data[key][key]])
                        v_closed = np.array([d == "CLOSED" for d in data[key][key]])
                        v_unknown = np.array([d == "UNKNOWN" for d in data[key][key]])

                    yval = (2e-2) * (0.85 ** i)
                    y_open = np.where(v_open, yval, np.nan)
                    y_closed = np.where(v_closed, yval, np.nan)
                    y_unknown = np.where(v_unknown, yval, np.nan)

                    color = base_colors[i]
                    safe_plot(ax, x, y_closed, color=color, lw=2.5, label=display_name(key))
                    safe_plot(ax, x, y_open, color=color, lw=1.5, ls=":")
                    safe_plot(ax, x, y_unknown, linestyle="--", color=color, lw=1.5)

                ax.set_yscale("log")
                ax.set_ylabel("State", color=thm["tick_color"], fontsize=8.5, fontweight="bold")
                ax.legend(loc="upper left", fontsize=7.5, facecolor=thm["legend_bg"], edgecolor=thm["legend_edge"], labelcolor=thm["legend_text"], framealpha=0.9)
                ax.set_title("Heat Switches & Relay", loc="left", fontsize=9, fontweight="bold", color=thm["text"], pad=2)

            else:
                color = ch_colors.get(ch_key, "#0891b2")
                unit = units.get(ch_key, "")
                name = display_name(ch_key)
                
                if ch_key in data and ch_key in data[ch_key] and len(data[ch_key][ch_key]) > 0:
                    v = np.array(data[ch_key][ch_key], dtype=float)
                    safe_plot(ax, x, v, color=color, linewidth=1.8)
                ax.set_title(name, loc="left", fontsize=9.5, fontweight="bold", color=color, pad=3)
                ax.set_ylabel(f"{name} ({unit})" if unit else name, color=thm["tick_color"], fontsize=8.5, fontweight="bold")

            if data_xloc is not None and xloc_ind is not None:
                ax.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

            if idx == len(channel_list) - 1:
                ax.xaxis.set_major_locator(MultipleLocator(step))
                ax.xaxis.set_major_formatter(FuncFormatter(lambda val, pos: epoch_to_local_str(val, span_s=span_for_format, include_seconds=False)))
                ax.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
                ax.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)
            else:
                ax.tick_params(axis="x", labelbottom=False)

        if target_xlim is not None and first_ax is not None:
            first_ax.set_xlim(target_xlim)

        keys_to_plot = [k for k in channel_list if k != "heat_switches"] + keys_hs
        return (data_mr, data_xloc, units, keys_to_plot, axes_list)


