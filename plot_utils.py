import math
import numpy as np
import matplotlib.colors as mc
import colorsys
from datetime import datetime
from matplotlib.ticker import (
    FuncFormatter, FormatStrFormatter, MultipleLocator, MaxNLocator,
    Locator, Formatter, LogLocator, LogFormatterMathtext
)
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
        "vac_can_pressure_torr",
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
            "cryocon_chA_temperature": "#38bdf8",     # Bright Cyan Blue (40K flange)
            "cryocon_chB_temperature": "#34d399",     # Emerald Green (Charcoal)
            "cryocon_chC_temperature": "#fbbf24",     # Amber Gold (4K flange)
            "cryocon_chD_temperature": "#c084fc",     # Bright Purple (Pot)
            "faa_temperature": "#f87171",             # Crimson Rose (FAA)
            "labjack_he3_pressure": "#60a5fa",        # Royal Blue (He3 Pressure)
            "vac_can_pressure_torr": "#2dd4bf",       # Bright Teal (Vac Can Pressure)
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
            "cryocon_chA_temperature": "#0284c7",     # Deep Sky Blue (40K flange)
            "cryocon_chB_temperature": "#059669",     # Forest / Emerald Green (Charcoal)
            "cryocon_chC_temperature": "#d97706",     # Warm Amber / Bronze (4K flange)
            "cryocon_chD_temperature": "#7c3aed",     # Vivid Purple (Pot)
            "faa_temperature": "#dc2626",             # Crimson Red (FAA)
            "labjack_he3_pressure": "#2563eb",        # Deep Royal Blue (He3 Pressure)
            "vac_can_pressure_torr": "#0d9488",       # Teal (Vac Can Pressure)
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
    "cryocon_chA_temperature": "40K flange",
    "cryocon_chB_temperature": "Charcoal",
    "cryocon_chC_temperature": "4K flange",
    "cryocon_chD_temperature": "Pot",
    "faa_temperature": "FAA",
    "labjack_he3_pressure": "He3 Pressure",
    "vac_can_pressure_torr": "Vac Can Pressure",
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

class SmartTimeLocator(Locator):
    """
    Intelligent dynamic time-series locator.
    Adapts ticks in real-time as the axis is zoomed or panned, guaranteeing a
    consistent, readable tick density (typically 4 to 8 ticks) across any scale:
    from sub-seconds to minutes, hours, days, months, and decades.
    Prevents Locator.MAXTICKS overflow crashes and eliminates clutter.
    """
    MAXTICKS = 2000

    # Comprehensive human-friendly step intervals (in seconds)
    STANDARD_STEPS = [
        # Sub-second / seconds
        0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0,
        # Minutes
        60.0, 120.0, 300.0, 600.0, 900.0, 1800.0,
        # Hours
        3600.0, 7200.0, 10800.0, 14400.0, 21600.0, 43200.0,
        # Days
        86400.0, 172800.0, 259200.0, 432000.0, 604800.0,
        # Weeks / Months
        1209600.0, 2592000.0, 5184000.0, 7776000.0, 15552000.0,
        # Years
        31536000.0, 63072000.0, 157680000.0, 315360000.0
    ]

    def __init__(self, target_ticks=6, min_ticks=4, max_ticks=8):
        super().__init__()
        self.target_ticks = target_ticks
        self.min_ticks = min_ticks
        self.max_ticks = max_ticks

    def _choose_step(self, span):
        if span <= 0 or not np.isfinite(span):
            return 60.0

        ideal_step = span / self.target_ticks

        if ideal_step < self.STANDARD_STEPS[0]:
            scale = 10.0 ** math.floor(math.log10(max(1e-12, ideal_step)))
            mult = ideal_step / scale
            if mult < 1.5:
                return 1.0 * scale
            elif mult < 3.5:
                return 2.0 * scale
            elif mult < 7.5:
                return 5.0 * scale
            else:
                return 10.0 * scale

        if ideal_step > self.STANDARD_STEPS[-1]:
            scale = 10.0 ** math.floor(math.log10(ideal_step))
            mult = ideal_step / scale
            if mult < 1.5:
                return 1.0 * scale
            elif mult < 3.5:
                return 2.0 * scale
            elif mult < 7.5:
                return 5.0 * scale
            else:
                return 10.0 * scale

        best_step = self.STANDARD_STEPS[0]
        best_score = float('inf')
        for s in self.STANDARD_STEPS:
            n = span / s
            diff = abs(n - self.target_ticks)
            if self.min_ticks <= n <= self.max_ticks:
                diff -= 0.6
            if diff < best_score:
                best_score = diff
                best_step = s

        return best_step

    def tick_values(self, vmin, vmax):
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
            return [vmin] if np.isfinite(vmin) else [0.0]
        if vmin > vmax:
            vmin, vmax = vmax, vmin

        span = vmax - vmin
        step = self._choose_step(span)

        is_epoch = (vmin > 1e8)
        tz_offset = 0.0
        if is_epoch:
            try:
                tz_offset = datetime.now().astimezone().utcoffset().total_seconds()
            except Exception:
                tz_offset = 0.0

        align_offset = tz_offset if (is_epoch and step >= 86400.0) else 0.0
        first_tick = math.ceil((vmin + align_offset) / step) * step - align_offset
        ticks = []
        t = first_tick
        max_allowed = 15  # Strict safety guarantee against tick explosion
        while t <= vmax + 1e-9 * step and len(ticks) < max_allowed:
            ticks.append(t)
            t += step

        if not ticks:
            ticks = [vmin, vmax]
        return ticks

    def __call__(self):
        if self.axis is not None:
            vmin, vmax = self.axis.get_view_interval()
        else:
            vmin, vmax = (0.0, 3600.0)
        return self.tick_values(vmin, vmax)


class SmartTimeFormatter(Formatter):
    """
    Intelligent dynamic time-series formatter.
    Inspects current visible span and tick delta, generating minimal, high-clarity labels:
    - Step < 60s (fine zoom): HH:MM:SS (prevents duplicate HH:MM labels)
    - 60s <= Step < 24h: HH:MM (under 24h span) or MM/DD HH:MM (multi-day span)
    - 24h <= Step < 30 days: MM/DD (clean date, no redundant 00:00 midnight text)
    - 30 days <= Step < 3 years: YYYY-MM
    - Step >= 3 years: YYYY
    Safely handles epoch bounds and relative elapsed time.
    """
    def __init__(self):
        super().__init__()
        self._last_step = 60.0

    def format_ticks(self, values):
        if len(values) > 1:
            diffs = np.diff(values)
            pos_diffs = diffs[diffs > 0]
            if len(pos_diffs) > 0:
                self._last_step = float(np.median(pos_diffs))
        span_s = 3600.0
        if self.axis is not None:
            try:
                vmin, vmax = self.axis.get_view_interval()
                span_s = abs(vmax - vmin)
            except Exception:
                pass
        return [self._format_single(v, span_s, self._last_step) for v in values]

    def _format_single(self, val, span_s, step):
        try:
            if val is None or not np.isfinite(val):
                return ""

            # Relative seconds (elapsed time or non-epoch coordinates)
            if val < 1e8:
                is_neg = val < 0
                val_abs = abs(val)
                s = int(val_abs % 60)
                m = int((val_abs // 60) % 60)
                h = int(val_abs // 3600)
                prefix = "-" if is_neg else ""
                if step < 60:
                    return f"{prefix}{m:02d}:{s:02d}"
                elif step < 86400:
                    return f"{prefix}{h:02d}:{m:02d}"
                else:
                    d = h // 24
                    h_rem = h % 24
                    return f"{prefix}{d}d {h_rem:02d}h"

            # Check for timestamp bounds (Python datetime supports years 1 to 9999)
            if val < 0 or val > 253402300799:
                return f"{val:.1e}"

            dt = datetime.fromtimestamp(val)
            if step < 60:
                return dt.strftime("%H:%M:%S")
            elif step < 86400:
                if span_s <= 86400:
                    return dt.strftime("%H:%M")
                else:
                    return dt.strftime("%m/%d %H:%M")
            elif step < 30 * 86400:
                return dt.strftime("%m/%d")
            elif step < 365.25 * 86400:
                return dt.strftime("%Y-%m")
            else:
                return dt.strftime("%Y")
        except Exception:
            return ""

    def __call__(self, x, pos=None):
        span_s = 3600.0
        step = self._last_step
        if self.axis is not None:
            try:
                vmin, vmax = self.axis.get_view_interval()
                span_s = abs(vmax - vmin)
                locs = self.axis.get_majorticklocs()
                if len(locs) > 1:
                    diffs = np.diff(locs)
                    pos_diffs = diffs[diffs > 0]
                    if len(pos_diffs) > 0:
                        step = float(np.median(pos_diffs))
                        self._last_step = step
            except Exception:
                pass
        return self._format_single(x, span_s, step)


def get_time_tick_step(span_s):
    """Return an intelligent time step for clean X-axis time ticks across any span."""
    return SmartTimeLocator()._choose_step(span_s if span_s is not None else 3600)


def epoch_to_local_str(epoch_s, span_s=None, include_seconds=False):
    """Convert epoch seconds or relative seconds to readable local time string without seconds by default."""
    try:
        if epoch_s is None or not np.isfinite(epoch_s):
            return ""
        if epoch_s < 1e8:  # Relative seconds (elapsed time)
            is_neg = epoch_s < 0
            val_abs = abs(epoch_s)
            s = int(val_abs % 60)
            m = int((val_abs // 60) % 60)
            h = int(val_abs // 3600)
            prefix = "-" if is_neg else ""
            if include_seconds:
                if h > 0:
                    return f"{prefix}{h:02d}:{m:02d}:{s:02d}"
                return f"{prefix}{m:02d}:{s:02d}"
            else:
                if span_s is not None and span_s >= 86400:
                    d = h // 24
                    h_rem = h % 24
                    return f"{prefix}{d}d {h_rem:02d}h"
                return f"{prefix}{h:02d}:{m:02d}" if h > 0 else f"{prefix}{m:02d}m"

        if epoch_s < 0 or epoch_s > 253402300799:
            return f"{epoch_s:.1e}"

        dt = datetime.fromtimestamp(epoch_s)
        if include_seconds:
            if span_s is not None and span_s > 86400:
                return dt.strftime("%m-%d %H:%M:%S")
            return dt.strftime("%H:%M:%S")

        if span_s is not None:
            if span_s < 120:
                return dt.strftime("%H:%M:%S")
            elif span_s <= 86400:
                return dt.strftime("%H:%M")
            elif span_s <= 7 * 86400:
                return dt.strftime("%m-%d %H:%M")
            elif span_s <= 180 * 86400:
                return dt.strftime("%m-%d")
            elif span_s <= 3 * 365.25 * 86400:
                return dt.strftime("%Y-%m")
            else:
                return dt.strftime("%Y")

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
            if "vac" not in k.lower() and k in data[k] and len(data[k][k]) > 0:
                return k
    return "labjack_he3_pressure"

def get_vac_can_pressure_key(data):
    for k in ("vac_can_pressure_torr", "labjack_vac_can_pressure_torr", "vac_can_pressure", "vac_can"):
        if k in data and k in data[k] and len(data[k][k]) > 0:
            return k
    for k in data.keys():
        if "vac" in k.lower() and "pres" in k.lower() and k in data[k] and len(data[k][k]) > 0:
            return k
    return "vac_can_pressure_torr"

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

def format_cryo_temp(val):
    """
    Format temperature into human-readable cryogenic units:
    - Below 1.0 K: auto-scale to mK (e.g. 48.5 mK)
    - 1.0 K to 10.0 K: 3 decimal places (e.g. 1.245 K)
    - Above 10.0 K: 1 decimal place (e.g. 26.8 K)
    """
    if val is None or not np.isfinite(val):
        return "NaN"
    if val < 0.001:
        return f"{val * 1e6:.1f} µK"
    elif val < 1.0:
        return f"{val * 1000.0:.1f} mK"
    elif val < 10.0:
        return f"{val:.3f} K"
    else:
        return f"{val:.1f} K"

def plot_dataset(figure, dataset, xloc_mouse=None, filter_tab="Main", temp_scale="log",
                 time_window="All Time", theme="light", custom_xlim=None, hidden_channels=None):
    """
    Plot dataset on figure with modern light or dark mode styling.
    - Main tab: All temperatures on left; He3 Pressure and Magnet Current as a 2x1 stack on right.
    - Thermometers tab: All temperatures overlaid in 1 single plot.
    - Pressures tab: 1 full-sized subplot.
    - Utils tab: Subplots for Kepco V, LS370 Heater, Heat Switches & Relay.
    Supports temp_scale: "log" or "linear".
    Supports time_window: "Last 1 Hour", "Last 6 Hours", "Last 24 Hours", "All Time".
    Supports theme: "light" or "dark".
    Supports custom_xlim: Optional (xmin, xmax) tuple to enforce explicit viewport zoom.
    Supports hidden_channels: Optional set/list of channel keys to hide from the plot.
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
    tw_str = str(time_window).strip().lower()
    if "1" in tw_str and "hour" in tw_str and "24" not in tw_str:
        window_s = 3600
    elif "6" in tw_str and "hour" in tw_str:
        window_s = 21600
    elif "7" in tw_str or "week" in tw_str:
        window_s = 7 * 86400
    elif "24" in tw_str or "day" in tw_str:
        window_s = 86400
    elif "all" in tw_str:
        window_s = None
    else:
        window_s = 21600

    target_xlim = None
    if custom_xlim is not None and isinstance(custom_xlim, (tuple, list)) and len(custom_xlim) == 2:
        try:
            x0 = float(custom_xlim[0])
            x1 = float(custom_xlim[1])
            if x0 < x1:
                target_xlim = (x0, x1)
        except Exception:
            pass

    if target_xlim is None and len(x) > 0:
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

    # Viewport window slicing: Slices large historical arrays to the visible window
    # ensuring instantaneous sub-millisecond execution even with millions of points.
    x_plot = x
    slice_start = 0
    slice_end = len(x)
    if len(x) > 0 and target_xlim is not None:
        pad = max(60.0, span_for_format * 0.05)
        # Check if target_xlim is a sub-window of x
        if target_xlim[0] > (x[0] - pad) or target_xlim[1] < (x[-1] + pad):
            if target_xlim[0] > x[0]:
                slice_start = max(0, int(np.searchsorted(x, target_xlim[0] - pad)))
            if target_xlim[1] < x[-1]:
                slice_end = min(len(x), int(np.searchsorted(x, target_xlim[1] + pad)) + 1)
            if slice_start > 0 or slice_end < len(x):
                x_plot = x[slice_start:slice_end]

    def get_sliced(arr):
        if arr is None or (slice_start == 0 and slice_end == len(x)):
            return arr
        if len(arr) >= len(x):
            return arr[slice_start:slice_end]
        return arr

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

        # 1. Plot all Temperatures on ax_temp
        all_found_temps = get_temp_keys(data)
        temp_keys = [k for k in all_found_temps if not (hidden_channels and k in hidden_channels)]
        all_temp_vals = []
        for key in temp_keys:
            if key in data and key in data[key] and len(data[key][key]) > 0:
                v = np.array(data[key][key], dtype=float)
                v_plot = get_sliced(v)
                pos = v_plot[np.isfinite(v_plot) & (v_plot > 0)]
                if len(pos) > 0:
                    all_temp_vals.append(pos)
                color = ch_colors.get(key, "#0284c7")
                name = display_name(key)
                safe_plot(ax_temp, x_plot, v_plot, color=color, lw=1.8, label=name)
        
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
        ax_temp.xaxis.set_major_locator(SmartTimeLocator())
        ax_temp.xaxis.set_major_formatter(SmartTimeFormatter())
        ax_temp.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax_temp.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)

        # 2. Plot He3 Pressure on ax_he3 (Top Right)
        he3_key = get_pressure_key(data)
        ax_he3.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
        color_he3 = ch_colors.get(he3_key, "#2563eb")
        if he3_key in data and he3_key in data[he3_key] and len(data[he3_key][he3_key]) > 0:
            v = np.array(data[he3_key][he3_key], dtype=float)
            v_plot = get_sliced(v)
            safe_plot(ax_he3, x_plot, v_plot, color=color_he3, lw=1.8)
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
            v_plot = get_sliced(v)
            safe_plot(ax_kepco_i, x_plot, v_plot, color=color_kepco, lw=1.8)
        ax_kepco_i.set_title(display_name(kepco_key), loc="left", fontsize=9.5, fontweight="bold", color=color_kepco, pad=4)
        ax_kepco_i.set_ylabel(f"Current ({unit})", color=thm["tick_color"], fontsize=8.5, fontweight="bold")
        ax_kepco_i.xaxis.set_major_locator(SmartTimeLocator())
        ax_kepco_i.xaxis.set_major_formatter(SmartTimeFormatter())
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

        all_found_temps = get_temp_keys(data)
        temp_keys = [k for k in all_found_temps if not (hidden_channels and k in hidden_channels)]
        all_temp_vals = []
        for key in temp_keys:
            if key in data and key in data[key] and len(data[key][key]) > 0:
                v = np.array(data[key][key], dtype=float)
                v_plot = get_sliced(v)
                pos = v_plot[np.isfinite(v_plot) & (v_plot > 0)]
                if len(pos) > 0:
                    all_temp_vals.append(pos)
                color = ch_colors.get(key, "#0284c7")
                name = display_name(key)
                safe_plot(ax, x_plot, v_plot, color=color, lw=1.8, label=name)

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
        ax.xaxis.set_major_locator(SmartTimeLocator())
        ax.xaxis.set_major_formatter(SmartTimeFormatter())
        ax.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)

        if target_xlim is not None:
            ax.set_xlim(target_xlim)

        if data_xloc is not None and xloc_ind is not None:
            ax.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

        return (data_mr, data_xloc, units, temp_keys, axes_list)

    elif filter_tab in ("Pressures", "Pressure"):
        figure.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.09, hspace=0.18)
        ax1 = figure.add_subplot(2, 1, 1)
        ax2 = figure.add_subplot(2, 1, 2, sharex=ax1)
        axes_list = [ax1, ax2]

        for ax in (ax1, ax2):
            ax.set_facecolor(thm["ax_bg"])
            for spine in ax.spines.values():
                spine.set_color(thm["spine"])
                spine.set_linewidth(1.0)
            ax.grid(True, which="both", axis="both", color=thm["grid"], linestyle="--", alpha=thm["grid_alpha"])
            ax.tick_params(axis="both", colors=thm["tick_color"], labelsize=8.5, labelleft=True)

        # 1. He3 Pressure (Top)
        he3_key = get_pressure_key(data)
        color_he3 = ch_colors.get(he3_key, "#2563eb")
        name_he3 = display_name(he3_key)
        ax1.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
        if he3_key in data and he3_key in data[he3_key] and len(data[he3_key][he3_key]) > 0:
            v_he3 = np.array(data[he3_key][he3_key], dtype=float)
            v_he3_plot = get_sliced(v_he3)
            safe_plot(ax1, x_plot, v_he3_plot, color=color_he3, lw=1.8)
        ax1.set_title(name_he3, loc="left", fontsize=9.5, fontweight="bold", color=color_he3, pad=3)
        ax1.set_ylabel("Pressure (bar)", color=thm["tick_color"], fontsize=8.5, fontweight="bold")
        ax1.tick_params(axis="x", labelbottom=False)

        # 2. Vacuum Can Pressure (Bottom)
        vac_key = get_vac_can_pressure_key(data)
        color_vac = ch_colors.get(vac_key, "#0d9488")
        name_vac = display_name(vac_key)
        ax2.set_yscale("log")
        has_vac = False
        if vac_key in data and vac_key in data[vac_key] and len(data[vac_key][vac_key]) > 0:
            v_vac = np.array(data[vac_key][vac_key], dtype=float)
            v_vac_plot = get_sliced(v_vac)
            valid_mask = np.isfinite(v_vac_plot) & (v_vac_plot > 0)
            if np.any(valid_mask):
                has_vac = True
                safe_plot(ax2, x_plot, v_vac_plot, color=color_vac, lw=1.8)
                y_min_val = float(np.min(v_vac_plot[valid_mask]))
                y_max_val = float(np.max(v_vac_plot[valid_mask]))
                if y_max_val / max(1e-9, y_min_val) < 10.0:
                    log_mid = (np.log10(y_min_val) + np.log10(y_max_val)) / 2.0
                    ax2.set_ylim(bottom=10.0 ** (np.floor(log_mid) - 1.0), top=10.0 ** (np.ceil(log_mid) + 1.0))
                else:
                    ax2.set_ylim(bottom=10.0 ** np.floor(np.log10(y_min_val)), top=10.0 ** np.ceil(np.log10(y_max_val)))

        if not has_vac:
            ax2.set_ylim(bottom=1e-4, top=1e3)

        ax2.yaxis.set_major_locator(LogLocator(base=10.0))
        ax2.yaxis.set_major_formatter(LogFormatterMathtext())
        ax2.set_title(name_vac, loc="left", fontsize=9.5, fontweight="bold", color=color_vac, pad=3)
        ax2.set_ylabel("Vac Can (Torr)", color=thm["tick_color"], fontsize=8.5, fontweight="bold")
        ax2.xaxis.set_major_locator(SmartTimeLocator())
        ax2.xaxis.set_major_formatter(SmartTimeFormatter())
        ax2.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
        ax2.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)
        try:
            figure.align_ylabels(axes_list)
        except Exception:
            pass

        if target_xlim is not None:
            ax1.set_xlim(target_xlim)

        if data_xloc is not None and xloc_ind is not None:
            ax1.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)
            ax2.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

        return (data_mr, data_xloc, units, [he3_key, vac_key], axes_list)

    else:  # "Utils" / "Diagnostics"
        figure.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.09, hspace=0.18)
        channel_list = [
            "labjack_kepco_voltage",
            "ls370_heater_out",
        ]
        first_ax = None
        for idx, ch_key in enumerate(channel_list):
            if idx == 0:
                ax = figure.add_subplot(len(channel_list), 1, idx + 1)
                first_ax = ax
                first_ax.xaxis.set_major_locator(SmartTimeLocator())
                first_ax.xaxis.set_major_formatter(SmartTimeFormatter())
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

            color = ch_colors.get(ch_key, "#0891b2")
            unit = units.get(ch_key, "")
            name = display_name(ch_key)
            
            if ch_key in data and ch_key in data[ch_key] and len(data[ch_key][ch_key]) > 0:
                v = np.array(data[ch_key][ch_key], dtype=float)
                v_plot = get_sliced(v)
                safe_plot(ax, x_plot, v_plot, color=color, linewidth=1.8)
            ax.set_title(name, loc="left", fontsize=9.5, fontweight="bold", color=color, pad=3)
            ax.set_ylabel(f"{name} ({unit})" if unit else name, color=thm["tick_color"], fontsize=8.5, fontweight="bold")

            if data_xloc is not None and xloc_ind is not None:
                ax.axvline(x[xloc_ind], color=thm["crosshair"], alpha=0.8, linestyle="--", linewidth=1.0)

            if idx == len(channel_list) - 1:
                ax.xaxis.set_major_locator(SmartTimeLocator())
                ax.xaxis.set_major_formatter(SmartTimeFormatter())
                ax.tick_params(axis="x", colors=thm["tick_color"], rotation=15, labelsize=8.5, labelbottom=True)
                ax.set_xlabel("Local Time", color=thm["subtext"], fontsize=9)
            else:
                ax.tick_params(axis="x", labelbottom=False)

        if target_xlim is not None and first_ax is not None:
            first_ax.set_xlim(target_xlim)

        return (data_mr, data_xloc, units, channel_list, axes_list)


def export_snapshot_plot(dataset, out_path, xlim=None, run_label="Current Run"):
    """
    Exports an 8-panel (2x4) publication-style snapshot figure matching the 2pac cryostat
    reference report layout into out_path:
      Row 0: Upper stage temp. (K), Charcoal temp. (K), 3 K plate temp. (K), ³He pot temp (K)
      Row 1: FAA temp (K), ³He pressure (abs. bar), Magnet current (A), Magnet setpoint (%)
    Top x-axis on Row 0: Time elapsed (hr)
    Bottom x-axis on Row 1: Time elapsed (ks)
    Only plots current dataset data within the specified xlim window.
    """
    import matplotlib.pyplot as plt
    from pathlib import Path

    data = dataset.cache.data()
    t = get_time_vector(dataset, data)
    if t is None or len(t) == 0:
        raise ValueError("No telemetry time vector found in dataset.")

    if xlim is not None and isinstance(xlim, (tuple, list)) and len(xlim) == 2:
        x_min_ts, x_max_ts = float(xlim[0]), float(xlim[1])
    else:
        x_min_ts, x_max_ts = float(t[0]), float(t[-1])

    if x_min_ts >= x_max_ts:
        x_min_ts, x_max_ts = float(t[0]), float(t[-1])

    mask = (t >= x_min_ts) & (t <= x_max_ts)
    if not np.any(mask):
        mask = np.ones(len(t), dtype=bool)

    t_sub = t[mask]

    # Elapsed time is measured from the beginning of the plot window, not the beginning of the file
    t0_plot = max(x_min_ts, float(t[0]))
    t_hr = (t_sub - t0_plot) / 3600.0
    x_min_hr = 0.0
    x_max_hr = max(0.05, (x_max_ts - t0_plot) / 3600.0)

    t_min_dt = datetime.fromtimestamp(t0_plot).strftime("%Y-%m-%d %H:%M")
    t_max_dt = datetime.fromtimestamp(x_max_ts).strftime("%Y-%m-%d %H:%M")

    channel_map = [
        ("Upper stage (40K) temp. (K)", ["cryocon_chA_temperature", "chA", "40k"]),
        ("Charcoal temp. (K)", ["cryocon_chB_temperature", "chB", "charcoal"]),
        ("4 K flange temp. (K)", ["cryocon_chC_temperature", "chC", "4k", "3k"]),
        ("³He pot temp (K)", ["cryocon_chD_temperature", "chD", "pot"]),
        ("FAA temp (K)", ["faa_temperature", "faa"]),
        ("³He pressure (abs. bar)", ["labjack_he3_pressure", "he3_pressure"]),
        ("Magnet current (A)", ["labjack_kepco_current", "kepco_current"]),
        ("Magnet setpoint (%)", ["ls370_heater_out", "labjack_kepco_voltage"]),
    ]

    fig, axes = plt.subplots(2, 4, figsize=(15, 8.2), sharex=True)
    fig.patch.set_facecolor("white")

    for idx, (label, candidates) in enumerate(channel_map):
        row = idx // 4
        col = idx % 4
        ax = axes[row, col]
        ax.set_facecolor("white")

        y_raw = None
        for c in candidates:
            if c in data and c in data[c] and len(data[c][c]) > 0:
                y_raw = np.array(data[c][c], dtype=float)[mask]
                break
        if y_raw is None:
            y_raw = np.zeros_like(t_sub)

        ax.plot(t_hr, y_raw, color="#00aa00", lw=2.0, label=run_label)
        ax.set_ylabel(label, fontsize=9.5, fontweight="bold", color="black")
        ax.grid(True, linestyle=":", color="#cccccc", alpha=0.8)

        for spine in ax.spines.values():
            spine.set_color("black")
            spine.set_linewidth(1.1)
        ax.tick_params(direction="in", top=True, right=True, which="both", colors="black", labelsize=8.5)
        ax.legend(loc="upper right", frameon=True, edgecolor="#cccccc", facecolor="white", fontsize=8.5, framealpha=0.9)

        y_valid = y_raw[np.isfinite(y_raw)]
        if len(y_valid) > 0:
            y_min, y_max = np.min(y_valid), np.max(y_valid)
            if "setpoint" in label.lower() and y_min == y_max == 0:
                ax.set_ylim(-0.05, 0.05)
            elif y_max > y_min:
                pad = (y_max - y_min) * 0.05
                ax.set_ylim(y_min - pad, y_max + pad)
            else:
                ax.set_ylim(y_min - 0.1, y_max + 0.1)

        ax.set_xlim(x_min_hr, x_max_hr)

        if row == 0:
            ax.tick_params(labelbottom=False)
        else:
            ax.set_xlabel("Time elapsed (hr)", fontsize=9.5, fontweight="bold", color="black", labelpad=5)
            if x_max_hr < 0.9:
                ax.xaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5]))
            else:
                if x_max_hr <= 8.5:
                    step = 1
                elif x_max_hr <= 16.5:
                    step = 2
                elif x_max_hr <= 36.5:
                    step = 4
                else:
                    step = 6
                ax.xaxis.set_major_locator(MultipleLocator(step))
                ax.xaxis.set_major_formatter(FormatStrFormatter("%d"))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fig.suptitle(f"2pac ADR Cryostat Telemetry Snapshot — {now_str}   [Local Time: {t_min_dt} to {t_max_dt}]",
                 fontsize=11, fontweight="bold", y=0.98, color="black")
    plt.subplots_adjust(left=0.065, right=0.98, top=0.93, bottom=0.09, wspace=0.28, hspace=0.18)

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_p), dpi=150, facecolor="white", edgecolor="none")
    plt.close(fig)
    return out_p



