"""
Shared imports, constants and helper functions for the 2PAC GUI (split out of gui.py, P1-12).
gui.py and the gui_* mixin modules do `from gui_common import *`.
"""
import sys
import os
import re
import time
import json
import sqlite3
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QComboBox, QTextEdit, QLabel, QHBoxLayout,
                             QPushButton, QTabWidget, QTabBar, QMessageBox, QFileDialog, QGridLayout, QLineEdit,
                             QScrollArea, QFrame, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
                             QListWidget, QListWidgetItem, QCheckBox, QSpinBox, QDoubleSpinBox, QFormLayout,
                             QProgressBar)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QObject, QEvent
from PyQt5.QtGui import QFont, QColor, QTextCursor, QTextCharFormat, QTextFormat, QIcon
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import numpy as np

from states import wait_forever
import states as _states_mod
from plot_utils import plot_dataset, CHANNEL_ALIASES, CHANNEL_COLORS, display_name, THEMES, format_cryo_temp, format_magnet_current

SETTINGS_PATH = Path.home() / "2pac_logs" / "channel_aliases.json"

DEFAULT_CHANNEL_ALIASES = {
    "cryocon_chA_temperature": "60K flange",
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

# ---------------- Procedures (states) shown to the user ----------------
# Plain-language names for state functions. Anything not listed falls back to an
# auto-generated name (underscores removed, words capitalised).
STATE_LABELS = {
    "wait_forever": "Idle",
    "ready_for_cooldown": "Ready for Cooldown",
    "autocool_he3_adr": "Auto-Cool: He-3 + ADR",
    "he3_only_cycle": "He-3 Cycle (No Magnet)",
    "he3_adr_cycle": "He-3 + ADR Cycle",
    "he3_adr_resume_at_ramp": "He-3 + ADR: Resume at Magnet Ramp",
    "regulate_temperature": "Regulate Temperature",
    "ramp_down_magnet": "Ramp Down Magnet",
    "warmup_300K": "Warm Up to 300 K",
}

STATE_DESCRIPTIONS = {
    "wait_forever": "Log data only. No hardware changes.",
    "ready_for_cooldown": "Closes all heat switches and sets He-3 setpoints (heaters off).\n"
                          "You will be asked to open the green He-3 valve.",
    "autocool_he3_adr": "Complete automated 300 K to base run:\n"
                        "1. Pre-cools cryostat with heat switches closed.\n"
                        "2. Safely waits for 3K stage to reach < 3.2 K (~29 h cooldown) using slow adaptive polling (60s/30s/10s).\n"
                        "3. Automatically executes the full He-3 + ADR cycle (condense He-3, ramp magnet, demag, and regulate).",
    "he3_only_cycle": "He-3 condensation cycle (no magnet / no ADR):\n"
                      "Heats charcoal (55 K), dwells 3.5 h, and cools charcoal to reach base temp (~300 mK).\n"
                      "Keeps ADR heat switch connected (CLOSED) to the pot so the FAA stage cools with the pot.\n"
                      "Relay is locked to CONTROL so the magnet remains de-energized.",
    "he3_adr_cycle": "Full He-3 / ADR cycle (~8 h total):\n"
                     "1. Pre-cool check: Verifies 3K starting temp (Ch C) < 3.2 K.\n"
                     "2. Heat charcoal (55 K) & RAMP MAGNET UP (0 -> 58.1%, 45 min) with ADR switch closed.\n"
                     "3. Condense He-3: 3.5 h dwell holding charcoal hot & magnet at full field.\n"
                     "4. Cool charcoal: Pumps He-3 until FAA reaches launch temperature (< 1.0 K).\n"
                     "5. RAMP MAGNET DOWN (Demag, 58.1% -> 0%, 45 min) with ADR switch open to reach base / regulate.",
    "he3_adr_resume_at_ramp": "Resume a He-3 + ADR cycle at the magnet ramp (e.g. Kepco was off):\n"
                              "Skips heat-switch reset and the 3K < 3.2 K gate (needs 3K < 5 K), keeps Cryo-con heating,\n"
                              "ramps magnet 0 -> 58.1% on the 10 mA range, then condense, launch, demag and regulate as usual.\n"
                              "Make sure the Kepco is ON first.",
    "regulate_temperature": "Sets relay to CONTROL and regulates temperature at target setpoint using Lake Shore 370 closed PID loop.",
    "ramp_down_magnet": "Safely ramps the magnet current from its current level down to 0 A at the standard safe rate.",
    "warmup_300K": "Closes all heat switches and warms the cryostat to 295 K.\n"
                   "You will be asked to open the green He-3 valve.",
}

# The normal operator sequence. Simple mode only offers these.
SIMPLE_WORKFLOW = [
    "wait_forever",
    "ready_for_cooldown",
    "autocool_he3_adr",
    "he3_only_cycle",
    "he3_adr_cycle",
    "he3_adr_resume_at_ramp",
    "regulate_temperature",
    "ramp_down_magnet",
    "warmup_300K",
]

IDLE_STATE = "wait_forever"


def state_label(key):
    """Human-readable name for a state key (no underscores)."""
    if not key:
        return ""
    if key in STATE_LABELS:
        return STATE_LABELS[key]
    words = [w for w in key.replace("-", "_").split("_") if w]
    return " ".join(w if any(c.isupper() or c.isdigit() for c in w) else w.capitalize() for w in words)


def format_duration(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


# ---------------- External command channel (private) ----------------
IPC_DIR = Path.home() / ".2pac" / "ipc"
try:
    IPC_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(IPC_DIR.parent, 0o700)
    os.chmod(IPC_DIR, 0o700)
except Exception as _e:
    print(f"Could not prepare {IPC_DIR}: {_e}")
LS370_STANDARD_QUERIES = ("PID?", "CSET?", "SETP?", "HTR?", "MOUT?", "CMODE?", "HTRRNG?", "RAMP?", "FILTER? 4", "RDGK? 4")

# ---------------- Persisted GUI settings ----------------
GUI_SETTINGS_PATH = Path.home() / "2pac_logs" / "gui_settings.json"
DEFAULT_GUI_SETTINGS = {
    "expert_mode": False,
    "log_interval_s": 1.0,
    "plot_refresh_s": 1,
    "default_range": "6 Hours",
    "text_logs": True,
    "theme": "light",
    # Single source of truth: recipe and regulation defaults live in states.py (P1-6).
    "adr_config": dict(_states_mod.DEFAULT_ADR_CONFIG),
    "pid_config": dict(_states_mod.REGULATION_DEFAULTS),
    # Remote alerts (alerts.py): fill in to get phone/chat alerts for banners, errors and stale telemetry.
    "alerts": {"webhook_url": "", "ntfy_url": "", "min_interval_s": 600},
    # Kepco wiring resistance per relay position (Ohm), for the inductive-voltage plot (P1-13).
    "magnet_config": {"wiring_r_ramp_ohm": 0.120, "wiring_r_control_ohm": 12.0},
}


def load_gui_settings():
    settings = dict(DEFAULT_GUI_SETTINGS)
    for _k in ("adr_config", "pid_config", "alerts", "magnet_config"):
        settings[_k] = dict(DEFAULT_GUI_SETTINGS[_k])
    try:
        if GUI_SETTINGS_PATH.exists():
            with open(GUI_SETTINGS_PATH) as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k in ("adr_config", "pid_config", "alerts", "magnet_config") and isinstance(v, dict):
                    settings[k].update(v)
                elif k in settings and isinstance(v, type(settings[k])) or (k in settings and isinstance(settings[k], float) and isinstance(v, int)):
                    settings[k] = v
    except Exception as e:
        print(f"Could not read GUI settings, using defaults: {e}")
    return settings


def save_gui_settings(settings):
    try:
        GUI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = GUI_SETTINGS_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2)
        tmp.replace(GUI_SETTINGS_PATH)
    except Exception as e:
        print(f"Could not save GUI settings: {e}")

DARK_QSS = """
QWidget {
    background-color: #090d16;
    color: #f8fafc;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}
QFrame#sidebar_frame, QFrame#status_frame {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 4px;
}
QFrame#separator {
    color: #1e293b;
    background-color: #1e293b;
    height: 1px;
    border: none;
}
QLabel {
    color: #cbd5e1;
}
QLabel#section_header {
    color: #f8fafc;
    font-size: 13px;
    font-weight: 600;
}
QLabel#muted_label {
    color: #94a3b8;
    font-size: 11px;
}
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #0f172a;
    border-radius: 4px;
    top: -1px;
}
QTabBar::tab {
    background-color: #111827;
    color: #94a3b8;
    padding: 7px 18px;
    border: 1px solid #1e293b;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-weight: 500;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #0f172a;
    color: #38bdf8;
    font-weight: 600;
    border-top: 2px solid #38bdf8;
}
QTabBar::tab:hover:!selected {
    color: #f8fafc;
    background-color: #1e293b;
}
QTabBar#plot_view_tabs::tab {
    padding: 4px 12px;
    border: 1px solid #1e293b;
    border-radius: 4px;
    background-color: #111827;
    color: #94a3b8;
    font-weight: 500;
    margin-right: 3px;
}
QTabBar#plot_view_tabs::tab:selected {
    background-color: #1e293b;
    color: #38bdf8;
    border: 1px solid #38bdf8;
    font-weight: 600;
}
QTabBar#plot_view_tabs::tab:hover:!selected {
    background-color: #1e293b;
    color: #f8fafc;
}
QPushButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 5px 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}
QPushButton:pressed {
    background-color: #0f172a;
}
QPushButton:disabled {
    background-color: #0f172a;
    color: #475569;
    border-color: #1e293b;
}
QPushButton#btn_start {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #3b82f6;
    font-weight: 600;
}
QPushButton#btn_start:hover {
    background-color: #1d4ed8;
}
QPushButton#btn_pause {
    background-color: #d97706;
    color: #ffffff;
    border: 1px solid #f59e0b;
    font-weight: 600;
}
QPushButton#btn_pause:hover {
    background-color: #b45309;
}
QPushButton#btn_stop {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #ef4444;
    font-weight: 600;
}
QPushButton#btn_stop:hover {
    background-color: #b91c1c;
}
QComboBox, QLineEdit {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox:focus, QLineEdit:focus {
QComboBox:focus, QLineEdit:focus {
    border-color: #38bdf8;
}
QComboBox QAbstractItemView {
    background-color: #1e293b;
    color: #f8fafc;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    border: 1px solid #334155;
}
QTextEdit {
    background-color: #0b0f19;
    color: #38bdf8;
    border: 1px solid #1e293b;
    border-radius: 4px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, Menlo, monospace;
    font-size: 12px;
}
QTableWidget {
    background-color: #0b0f19;
    color: #f8fafc;
    gridline-color: #1e293b;
    border: 1px solid #1e293b;
    border-radius: 4px;
    selection-background-color: #1e3a8a;
    selection-color: #38bdf8;
}
QHeaderView::section {
    background-color: #1e293b;
    color: #38bdf8;
    padding: 5px 8px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid #334155;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 25px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QListWidget#state_list {
    background-color: #0b0f19;
    border: 1px solid #1e293b;
    border-radius: 4px;
    outline: none;
}
QListWidget#state_list::item {
    padding: 7px 6px;
    border-bottom: 1px solid #1e293b;
    color: #cbd5e1;
}
QListWidget#state_list::item:selected {
    background-color: #1e3a8a;
    color: #38bdf8;
}
QSpinBox, QDoubleSpinBox {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 3px 6px;
}
QFrame#operator_banner {
    background-color: #78350f;
    border: 1px solid #d97706;
    border-radius: 4px;
}
QFrame#operator_banner QLabel {
    background-color: transparent;
    color: #fde68a;
    font-weight: 600;
}
QFrame#operator_banner QPushButton {
    background-color: #d97706;
    color: #ffffff;
    border: 1px solid #f59e0b;
    font-weight: 600;
}
QFrame#operator_banner QPushButton:hover {
    background-color: #b45309;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #334155;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #38bdf8;
}
"""

LIGHT_QSS = """
QWidget {
    background-color: #f8fafc;
    color: #0f172a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}
QFrame#sidebar_frame, QFrame#status_frame {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
}
QFrame#separator {
    color: #e2e8f0;
    background-color: #e2e8f0;
    height: 1px;
    border: none;
}
QLabel {
    color: #334155;
}
QLabel#section_header {
    color: #0f172a;
    font-size: 13px;
    font-weight: 600;
}
QLabel#muted_label {
    color: #64748b;
}
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    background-color: #ffffff;
    border-radius: 4px;
    top: -1px;
}
QTabBar::tab {
    background-color: #f1f5f9;
    color: #64748b;
    padding: 7px 18px;
    border: 1px solid #e2e8f0;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-weight: 500;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #0284c7;
    font-weight: 600;
    border-top: 2px solid #0284c7;
}
QTabBar::tab:hover:!selected {
    color: #0f172a;
    background-color: #e2e8f0;
}
QTabBar#plot_view_tabs::tab {
    padding: 4px 12px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #f1f5f9;
    color: #64748b;
    font-weight: 500;
    margin-right: 3px;
}
QTabBar#plot_view_tabs::tab:selected {
    background-color: #ffffff;
    color: #0284c7;
    border: 1px solid #0284c7;
    font-weight: 600;
}
QTabBar#plot_view_tabs::tab:hover:!selected {
    background-color: #e2e8f0;
    color: #0f172a;
}
QPushButton {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 5px 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background-color: #e2e8f0;
}
QPushButton:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border-color: #e2e8f0;
}
QPushButton#btn_start {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #0284c7;
    font-weight: 600;
}
QPushButton#btn_start:hover {
    background-color: #0369a1;
    border-color: #0369a1;
}
QPushButton#btn_pause {
    background-color: #d97706;
    color: #ffffff;
    border: 1px solid #d97706;
    font-weight: 600;
}
QPushButton#btn_pause:hover {
    background-color: #b45309;
    border-color: #b45309;
}
QPushButton#btn_stop {
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #dc2626;
    font-weight: 600;
}
QPushButton#btn_stop:hover {
    background-color: #b91c1c;
    border-color: #b91c1c;
}
QComboBox, QLineEdit {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox:focus, QLineEdit:focus {
    border-color: #0284c7;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #0f172a;
    selection-background-color: #e0f2fe;
    selection-color: #0284c7;
    border: 1px solid #cbd5e1;
}
QTextEdit {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    font-family: "JetBrains Mono", "Fira Code", Consolas, Menlo, monospace;
    font-size: 12px;
}
QTableWidget {
    background-color: #ffffff;
    color: #0f172a;
    gridline-color: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    selection-background-color: #e0f2fe;
    selection-color: #0284c7;
}
QHeaderView::section {
    background-color: #f8fafc;
    color: #475569;
    padding: 5px 8px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid #e2e8f0;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 25px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QListWidget#state_list {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    outline: none;
}
QListWidget#state_list::item {
    padding: 7px 6px;
    border-bottom: 1px solid #f1f5f9;
    color: #334155;
}
QListWidget#state_list::item:selected {
    background-color: #e0f2fe;
    color: #0369a1;
}
QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 3px 6px;
}
QFrame#operator_banner {
    background-color: #fef3c7;
    border: 1px solid #f59e0b;
    border-radius: 4px;
}
QFrame#operator_banner QLabel {
    background-color: transparent;
    color: #92400e;
    font-weight: 600;
}
QFrame#operator_banner QPushButton {
    background-color: #f59e0b;
    color: #ffffff;
    border: 1px solid #d97706;
    font-weight: 600;
}
QFrame#operator_banner QPushButton:hover {
    background-color: #d97706;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #0284c7;
}
"""

STATUS_BADGE_STYLES = {
    "dark": {
        "running": "background-color: #064e3b; color: #34d399; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #059669; padding: 4px;",
        "idle": "background-color: #1e293b; color: #94a3b8; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #334155; padding: 4px;",
        "paused": "background-color: #78350f; color: #fbbf24; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #d97706; padding: 4px;",
        "stopped": "background-color: #7f1d1d; color: #fca5a5; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #dc2626; padding: 4px;",
        "error": "background-color: #7f1d1d; color: #fca5a5; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #dc2626; padding: 4px;",
    },
    "light": {
        "running": "background-color: #dcfce7; color: #15803d; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #86efac; padding: 4px;",
        "idle": "background-color: #f1f5f9; color: #64748b; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #cbd5e1; padding: 4px;",
        "paused": "background-color: #fef3c7; color: #b45309; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #fcd34d; padding: 4px;",
        "stopped": "background-color: #fee2e2; color: #b91c1c; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #fca5a5; padding: 4px;",
        "error": "background-color: #fee2e2; color: #b91c1c; font-weight: bold; border-radius: 4px; font-size: 11px; border: 1px solid #fca5a5; padding: 4px;",
    }
}

DATA_SOURCE_STYLES = {
    "dark": {
        "live": "color: #34d399; font-weight: 600; font-size: 11px;",
        "history": "color: #fbbf24; font-weight: 600; font-size: 11px;",
    },
    "light": {
        "live": "color: #15803d; font-weight: 600; font-size: 11px;",
        "history": "color: #d97706; font-weight: 600; font-size: 11px;",
    }
}

PRIMARY_STATUS_KEYS = [
    "cryocon_chA_temperature",
    "cryocon_chB_temperature",
    "cryocon_chC_temperature",
    "faa_temperature",
    "labjack_he3_pressure",
    "vac_can_pressure_torr",
    "labjack_kepco_current",
]

def load_aliases():
    """Load channel aliases from disk if available."""
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
                CHANNEL_ALIASES.update(saved)
        except Exception:
            pass

def save_aliases():
    """Persist channel aliases to disk."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(CHANNEL_ALIASES, f, indent=2)

def get_arrow_linenum(s2):
    lines = s2.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('-->'):
            return i
    return 0

def get_arrow_char_index(s2, plus=0):
    lines = s2.split('\n')
    char_index = 0
    for line in lines:
        if line.startswith('-->'):
            return min(char_index+plus, len(s2)-1)
        char_index += len(line) + 1
    return 0

def color_line(textedit, line_number, color=None, theme="light"):
    """Instantly highlight active execution line using native Qt ExtraSelections without blocking text traversal."""
    if not hasattr(textedit, "setExtraSelections") or line_number is None or line_number < 0:
        return
    doc = textedit.document()
    if line_number >= doc.blockCount():
        return
    block = doc.findBlockByNumber(line_number)
    cursor = QTextCursor(block)

    sel = QTextEdit.ExtraSelection()
    if color is None:
        color = QColor(224, 242, 254) if theme == "light" else QColor(30, 58, 138)
    sel.format.setBackground(color)
    sel.format.setProperty(QTextFormat.FullWidthSelection, True)
    sel.cursor = cursor
    textedit.setExtraSelections([sel])


class ScrollAreaWheelForwarder(QObject):
    """
    Event filter installed on interactive child widgets (QComboBox, QSpinBox, QDoubleSpinBox, QPushButton)
    inside a QScrollArea. Prevents accidental parameter alteration when the user rolls their
    mouse scroll wheel over the controls, forwarding the wheel event directly to the scroll area
    so the sidebar or tab scrolls smoothly instead of modifying values or getting stuck.
    """
    def __init__(self, scroll_area):
        super().__init__(scroll_area)
        self.scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            self.scroll_area.wheelEvent(event)
            return True
        return False


def forward_child_wheel_events(scroll_area, container_widget):
    """Install ScrollAreaWheelForwarder on all interactive input children of a container widget."""
    forwarder = ScrollAreaWheelForwarder(scroll_area)
    for child in container_widget.findChildren((QComboBox, QSpinBox, QDoubleSpinBox, QPushButton)):
        child.installEventFilter(forwarder)
    return forwarder
