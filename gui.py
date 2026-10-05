import sys
import time
import json
import sqlite3
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QComboBox, QTextEdit, QLabel, QHBoxLayout,
                             QPushButton, QTabWidget, QMessageBox, QFileDialog, QGridLayout, QLineEdit,
                             QScrollArea, QFrame, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
                             QListWidget, QListWidgetItem, QCheckBox, QSpinBox, QDoubleSpinBox, QFormLayout)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QTextCursor, QTextCharFormat, QIcon
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
import matplotlib.pyplot as plt
import numpy as np

from states import wait_forever
from plot_utils import plot_dataset, CHANNEL_ALIASES, CHANNEL_COLORS, display_name, THEMES

SETTINGS_PATH = Path.home() / "2pac_logs" / "channel_aliases.json"

DEFAULT_CHANNEL_ALIASES = {
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

# ---------------- Procedures (states) shown to the user ----------------
# Plain-language names for state functions. Anything not listed falls back to an
# auto-generated name (underscores removed, words capitalised).
STATE_LABELS = {
    "wait_forever": "Idle",
    "ready_for_cooldown": "Ready for Cooldown",
    "he3_adr_cycle": "He-3 + ADR Cycle",
    "warmup_300K": "Warm Up to 300 K",
    "open_adr_heatswitch": "Open ADR Heat Switch",
    "open_charcoal_heatswitch": "Open Charcoal Heat Switch",
    "open_pot_heatswitch": "Open Pot Heat Switch",
    "set_relay_to_ramp": "Set Relay to Ramp",
}

STATE_DESCRIPTIONS = {
    "wait_forever": "Log data only. No hardware changes.",
    "ready_for_cooldown": "Closes all heat switches and sets He-3 setpoints (heaters off).\n"
                          "You will be asked to open the green He-3 valve.",
    "he3_adr_cycle": "Full He-3 / ADR cycle (several hours): heats charcoal, ramps the magnet up, "
                     "condenses He-3, then ramps the magnet down.\nWaits until the pot is below 3.2 K before starting.",
    "warmup_300K": "Closes all heat switches and heats the stages to 295 K.",
}

# The normal operator sequence. Simple mode only offers these.
SIMPLE_WORKFLOW = ["wait_forever", "ready_for_cooldown", "he3_adr_cycle", "warmup_300K"]

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


# ---------------- Persisted GUI settings ----------------
GUI_SETTINGS_PATH = Path.home() / "2pac_logs" / "gui_settings.json"
DEFAULT_GUI_SETTINGS = {
    "expert_mode": False,
    "log_interval_s": 1.0,
    "plot_refresh_s": 1,
    "default_range": "6 Hours",
    "text_logs": True,
    "theme": "light",
}


def load_gui_settings():
    settings = dict(DEFAULT_GUI_SETTINGS)
    try:
        if GUI_SETTINGS_PATH.exists():
            with open(GUI_SETTINGS_PATH) as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k in settings and isinstance(v, type(settings[k])) or (k in settings and isinstance(settings[k], float) and isinstance(v, int)):
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
    background: #090d16;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #475569;
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
    font-size: 11px;
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
    background: #f8fafc;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
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
    if color is None:
        color = QColor(224, 242, 254) if theme == "light" else QColor(30, 58, 138)

    doc = textedit.document()
    if line_number < 0 or line_number >= doc.blockCount():
        return

    cursor = QTextCursor(doc)
    cursor.beginEditBlock()

    block = doc.firstBlock()
    while block.isValid():
        block_cursor = QTextCursor(block)
        block_cursor.select(QTextCursor.LineUnderCursor)
        block_cursor.setCharFormat(QTextCharFormat())
        block = block.next()

    cursor.endEditBlock()

    block = doc.findBlockByNumber(line_number)
    cursor = QTextCursor(block)
    fmt = QTextCharFormat()
    fmt.setBackground(color)
    fmt.setForeground(QColor(2, 132, 199) if theme == "light" else QColor(56, 189, 248))
    cursor.select(QTextCursor.LineUnderCursor)
    cursor.setCharFormat(fmt)


class DataFetchThread(QThread):
    state_update = pyqtSignal(str, str)
    procedure_finished = pyqtSignal(str)
    procedure_error = pyqtSignal(str, str)
    operator_action = pyqtSignal(str, str)

    def __init__(self, world, first_state, states_dict):
        super().__init__()
        self.world = world
        self.next_state = first_state
        self.states_dict = states_dict
        self.state = None
        self.running = True
        self.paused = False

    def set_combo_value(self, value):
        if isinstance(value, str):
            if value in self.states_dict:
                self.next_state = self.states_dict[value]
                self.paused = False
        else:
            self.next_state = value
            self.paused = False

    def run(self):
        while self.running:
            if self.next_state is not None:
                self.state = self.next_state
                self.next_state = None

            if self.state is None:
                time.sleep(0.5)
                continue

            state_name = self.state.name()
            # If entering ready_for_cooldown, emit operator action for the He-3 valve
            if state_name == "ready_for_cooldown":
                self.operator_action.emit(state_name, "⚠️ ACTION REQUIRED: Open the green He-3 valve on the cryostat.")

            runner = self.world.state_runner(self.state)
            self.world._update(self.state)
            tstart = self.world.last_update_time_s

            try:
                for (state, line_number) in runner:
                    if not self.running:
                        return
                    if self.next_state is not None:
                        break

                    while self.paused and self.next_state is None and self.running:
                        time.sleep(max(0.1, self.world.target_tick_rate_s))
                        self.world._update(state)
                        elapsed = self.world.last_update_time_s - tstart
                        s1 = f"state={state.name()} [PAUSED] {line_number=} {elapsed=:.2f}"
                        self.state_update.emit(s1, state.code_highlighted(line_number))

                    if self.next_state is not None:
                        break

                    self.state = state
                    elapsed = self.world.last_update_time_s - tstart
                    s1 = f"state={state.name()} {line_number=} {elapsed=:.2f} state_elapsed_s={self.world.state_elapsed_s():.2f}"
                    s2 = state.code_highlighted(line_number)
                    self.state_update.emit(s1, s2)

                    # Check for valve instruction in he3_adr_cycle
                    if state.name() == "he3_adr_cycle":
                        code_line = state.code_line(line_number)
                        if "CLOSE THE GREEN HE3 VALVE" in code_line:
                            self.operator_action.emit("he3_adr_cycle", "⚠️ ACTION REQUIRED: Close the green He-3 valve on the cryostat.")

                # If runner exited naturally without next_state being set
                if self.next_state is None and self.running:
                    finished_name = self.state.name()
                    self.procedure_finished.emit(finished_name)
                    # Automatically transition to IDLE_STATE (wait_forever)
                    idle_st = self.states_dict.get(IDLE_STATE)
                    if idle_st is not None:
                        self.state = idle_st
                    else:
                        time.sleep(1)

            except Exception as e:
                err_msg = str(e)
                failed_name = self.state.name() if self.state else "procedure"
                print(f"Error in state runner for '{failed_name}': {e}")
                self.procedure_error.emit(failed_name, err_msg)
                # Safely fall back to IDLE_STATE
                idle_st = self.states_dict.get(IDLE_STATE)
                self.state = idle_st
                time.sleep(1)


class MyApp(QWidget):
    def __init__(self, world, dataset, states_dict):
        super().__init__()

        load_aliases()

        self.gui_settings = load_gui_settings()
        self.expert_mode = bool(self.gui_settings.get("expert_mode", False))

        self.world = world
        self.world.target_tick_rate_s = float(self.gui_settings.get("log_interval_s", 1.0))
        import states as states_module
        states_module.ENABLE_TEXT_LOGGING = bool(self.gui_settings.get("text_logs", True))

        self.live_dataset = dataset
        self.historical_dataset = None
        self.displaying_historical = False
        self.states_dict = states_dict
        self.theme = self.gui_settings.get("theme", "light")
        self.current_badge_state = "idle"
        self.active_plot_tab = "Overview"
        self.temp_scale = "log"
        self.time_window = self.gui_settings.get("default_range", "6 Hours")
        self.user_has_zoomed = False
        self.previewing_state = None
        self.axes_list = []
        self.on_mouse_move_event = None
        self.db_file_path = None

        # Left-click drag & pan state
        self._drag_active = False
        self._drag_start_x = None
        self._drag_start_y = None
        self._drag_start_ax = None
        self._drag_init_xlim = None
        self._drag_init_ylim = None
        self._drag_has_moved = False

        screen_geometry = QApplication.desktop().screenGeometry()
        win_w = min(1440, screen_geometry.width())
        win_h = min(900, int(0.85 * screen_geometry.height()))
        self.setFixedSize(win_w, win_h)
        self.setWindowTitle("2pac gui — Idle")
        icon_path = Path(__file__).parent / "adr_gui_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # ================= Overall Layout =================
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(3)

        # Operator Action / Alert Banner
        self.operator_banner = QFrame()
        self.operator_banner.setObjectName("operator_banner")
        banner_layout = QHBoxLayout(self.operator_banner)
        banner_layout.setContentsMargins(10, 6, 10, 6)
        banner_layout.setSpacing(8)
        self.lbl_operator_action = QLabel("")
        self.lbl_operator_action.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_operator_action.setWordWrap(True)
        self.btn_dismiss_banner = QPushButton("Dismiss")
        self.btn_dismiss_banner.setFixedWidth(80)
        self.btn_dismiss_banner.clicked.connect(self.dismiss_operator_banner)
        banner_layout.addWidget(self.lbl_operator_action, stretch=1)
        banner_layout.addWidget(self.btn_dismiss_banner)
        self.operator_banner.setVisible(False)
        outer_layout.addWidget(self.operator_banner)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(4)

        # ================= Control Sidebar (Compact Fixed 185px) =================
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("sidebar_frame")
        sidebar_frame.setFixedWidth(185)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setAlignment(Qt.AlignTop)
        sidebar_layout.setContentsMargins(6, 6, 6, 6)
        sidebar_layout.setSpacing(5)

        self.lbl_status_badge = QLabel("IDLE")
        self.lbl_status_badge.setAlignment(Qt.AlignCenter)
        self.lbl_status_badge.setFixedHeight(24)
        sidebar_layout.addWidget(self.lbl_status_badge)

        lbl_proc = QLabel("Procedure:")
        lbl_proc.setObjectName("muted_label")
        sidebar_layout.addWidget(lbl_proc)

        self.combo_box = QComboBox(self)
        self.combo_box.wheelEvent = lambda event: None
        self._populate_state_combo()
        self.combo_box.currentIndexChanged.connect(self.on_combo_changed)
        sidebar_layout.addWidget(self.combo_box)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("btn_start")
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("btn_pause")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btn_stop")

        self.btn_start.clicked.connect(self.request_state_change)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop_state)

        sidebar_layout.addWidget(self.btn_start)
        sidebar_layout.addWidget(self.btn_pause)
        sidebar_layout.addWidget(self.btn_stop)

        self.btn_toggle_mode = QPushButton("Mode: Expert" if self.expert_mode else "Mode: Simple")
        self.btn_toggle_mode.clicked.connect(self.toggle_expert_mode)
        sidebar_layout.addWidget(self.btn_toggle_mode)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        sep1.setObjectName("separator")
        sidebar_layout.addWidget(sep1)

        self.btn_reload_scripts = QPushButton("Reload Scripts")
        self.btn_reload_scripts.clicked.connect(self.reload_desktop_scripts)
        self.btn_reload_scripts.setVisible(self.expert_mode)
        sidebar_layout.addWidget(self.btn_reload_scripts)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        sep2.setObjectName("separator")
        sidebar_layout.addWidget(sep2)

        self.lbl_data_source = QLabel("● Live")
        self.lbl_data_source.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.lbl_data_source)

        self.btn_live_data = QPushButton("Return to Live")
        self.btn_live_data.setEnabled(False)
        self.btn_live_data.clicked.connect(self.return_to_live)
        sidebar_layout.addWidget(self.btn_live_data)

        self.btn_reset_zoom = QPushButton("Reset Zoom")
        self.btn_reset_zoom.clicked.connect(self.reset_zoom)
        sidebar_layout.addWidget(self.btn_reset_zoom)

        main_layout.addWidget(sidebar_frame)

        # ================= Four Primary Navigation Tabs =================
        self.main_tabs = QTabWidget()

        # --- 1. Plots Tab ---
        self.graphs_tab = QWidget()
        graphs_layout = QVBoxLayout()
        graphs_layout.setContentsMargins(1, 1, 1, 1)
        graphs_layout.setSpacing(2)

        # Sleek plot toolbar with View selector, Time Range, Scale, Theme, and Matplotlib actions
        plot_ctrl_bar = QHBoxLayout()
        plot_ctrl_bar.setContentsMargins(2, 0, 2, 0)
        plot_ctrl_bar.setSpacing(4)

        lbl_v = QLabel("View:")
        lbl_v.setObjectName("muted_label")
        plot_ctrl_bar.addWidget(lbl_v)

        self.combo_view = QComboBox()
        self.combo_view.wheelEvent = lambda event: None
        self.combo_view.addItems(["Overview", "Thermometers", "Pressure", "Diagnostics"])
        self.combo_view.setCurrentText("Overview")
        self.combo_view.currentTextChanged.connect(self.on_view_changed)
        plot_ctrl_bar.addWidget(self.combo_view)

        plot_ctrl_bar.addSpacing(6)
        lbl_tw = QLabel("Range:")
        lbl_tw.setObjectName("muted_label")
        plot_ctrl_bar.addWidget(lbl_tw)

        self.combo_time_window = QComboBox()
        self.combo_time_window.wheelEvent = lambda event: None
        self.combo_time_window.addItems(["1 Hour", "6 Hours", "24 Hours", "All Time"])
        self.combo_time_window.setCurrentText("6 Hours")
        self.combo_time_window.currentTextChanged.connect(self.on_time_window_changed)
        plot_ctrl_bar.addWidget(self.combo_time_window)

        plot_ctrl_bar.addSpacing(6)
        self.btn_toggle_temp_scale = QPushButton("Log Scale")
        self.btn_toggle_temp_scale.clicked.connect(self.toggle_temp_scale)
        plot_ctrl_bar.addWidget(self.btn_toggle_temp_scale)

        self.btn_theme_toggle = QPushButton("Light")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        plot_ctrl_bar.addWidget(self.btn_theme_toggle)

        plot_ctrl_bar.addStretch()

        self.figure = plt.Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        plot_ctrl_bar.addWidget(self.toolbar)
        graphs_layout.addLayout(plot_ctrl_bar)
        graphs_layout.addWidget(self.canvas)

        self.figure.canvas.mpl_connect("motion_notify_event", self.mpl_on_mouse_move)
        self.figure.canvas.mpl_connect("scroll_event", self.mpl_on_scroll)
        self.figure.canvas.mpl_connect("button_press_event", self.mpl_on_click)
        self.figure.canvas.mpl_connect("button_release_event", self.mpl_on_release)

        self.graphs_tab.setLayout(graphs_layout)

        # --- 2. Scripts Tab ---
        self.scripting_tab = QWidget()
        scripting_layout = QVBoxLayout()
        scripting_layout.setContentsMargins(8, 8, 8, 8)
        scripting_layout.setSpacing(6)

        script_bar = QHBoxLayout()
        self.lbl_script_name = QLabel("Active Script: wait_forever")
        self.lbl_script_name.setObjectName("muted_label")
        script_bar.addWidget(self.lbl_script_name)
        script_bar.addStretch()

        self.btn_apply_script = QPushButton("Execute Modified Code")
        self.btn_apply_script.clicked.connect(lambda: self.request_state_change(bypass_confirm=False))
        script_bar.addWidget(self.btn_apply_script)
        scripting_layout.addLayout(script_bar)

        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(False)
        self.text_output.setLineWrapMode(QTextEdit.NoWrap)
        scripting_layout.addWidget(self.text_output)
        self.scripting_tab.setLayout(scripting_layout)

        # --- 3. Channels Tab (The 3rd Tab as required) ---
        self.settings_tab = QWidget()
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(12, 10, 12, 10)
        settings_layout.setSpacing(8)

        settings_top = QHBoxLayout()
        lbl_settings_hdr = QLabel("Channel Aliases")
        lbl_settings_hdr.setObjectName("section_header")
        settings_top.addWidget(lbl_settings_hdr)
        settings_top.addStretch()

        self.btn_reset_aliases = QPushButton("Reset Defaults")
        self.btn_reset_aliases.clicked.connect(self.reset_default_aliases)
        settings_top.addWidget(self.btn_reset_aliases)

        self.btn_save_aliases = QPushButton("Save Aliases")
        self.btn_save_aliases.clicked.connect(self.save_channel_aliases)
        settings_top.addWidget(self.btn_save_aliases)
        settings_layout.addLayout(settings_top)

        lbl_settings_sub = QLabel("Assign human-readable aliases (Pot, FAA, Charcoal, 4K) to telemetry channels:")
        lbl_settings_sub.setObjectName("muted_label")
        settings_layout.addWidget(lbl_settings_sub)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self.alias_grid = QGridLayout(scroll_content)
        self.alias_grid.setSpacing(8)
        self.alias_grid.setContentsMargins(4, 4, 4, 4)

        self.alias_grid.addWidget(QLabel("<b>Hardware Channel</b>"), 0, 0)
        self.alias_grid.addWidget(QLabel("<b>Display Alias</b>"), 0, 1)

        self.alias_inputs = {}
        row_idx = 1
        # Order channels cleanly
        ordered_keys = list(DEFAULT_CHANNEL_ALIASES.keys()) + [k for k in CHANNEL_ALIASES if k not in DEFAULT_CHANNEL_ALIASES]
        for key in ordered_keys:
            alias = CHANNEL_ALIASES.get(key, DEFAULT_CHANNEL_ALIASES.get(key, key))
            lbl_k = QLabel(key)
            lbl_k.setObjectName("muted_label")
            self.alias_grid.addWidget(lbl_k, row_idx, 0)
            inp = QLineEdit(alias)
            self.alias_inputs[key] = inp
            self.alias_grid.addWidget(inp, row_idx, 1)
            row_idx += 1

        self.alias_grid.setRowStretch(row_idx, 1)
        scroll_area.setWidget(scroll_content)
        settings_layout.addWidget(scroll_area)
        self.settings_tab.setLayout(settings_layout)

        # --- 4. History Tab (Database Explorer) ---
        self.db_tab = QWidget()
        db_layout = QVBoxLayout()
        db_layout.setContentsMargins(8, 8, 8, 8)
        db_layout.setSpacing(6)

        db_top_bar = QHBoxLayout()
        lbl_db_hdr = QLabel("Run History")
        lbl_db_hdr.setObjectName("section_header")
        db_top_bar.addWidget(lbl_db_hdr)
        db_top_bar.addStretch()

        self.btn_select_db_file = QPushButton("Choose File...")
        self.btn_select_db_file.clicked.connect(self.choose_db_file)
        db_top_bar.addWidget(self.btn_select_db_file)

        self.btn_refresh_db = QPushButton("Refresh")
        self.btn_refresh_db.clicked.connect(self.populate_db_table)
        db_top_bar.addWidget(self.btn_refresh_db)

        self.btn_load_selected_run = QPushButton("Load Run")
        self.btn_load_selected_run.clicked.connect(self.load_selected_db_run)
        db_top_bar.addWidget(self.btn_load_selected_run)
        db_layout.addLayout(db_top_bar)

        self.db_table = QTableWidget()
        self.db_table.setColumnCount(4)
        self.db_table.setHorizontalHeaderLabels(["Run ID", "Experiment", "Points", "Timestamp"])
        self.db_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.db_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.db_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.db_table.doubleClicked.connect(self.on_db_row_double_click)
        db_layout.addWidget(self.db_table)

        self.db_tab.setLayout(db_layout)

        # --- 5. Utils Tab ---
        self.utils_tab = self._build_utils_tab()

        # Add tabs: Plots, (Scripts in Expert mode), Channels, History, Utils
        self.main_tabs.addTab(self.graphs_tab, "Plots")
        if self.expert_mode:
            self.main_tabs.addTab(self.scripting_tab, "Scripts")
        self.main_tabs.addTab(self.settings_tab, "Channels")
        self.main_tabs.addTab(self.db_tab, "History")
        self.main_tabs.addTab(self.utils_tab, "Utils")

        main_layout.addWidget(self.main_tabs, stretch=1)
        outer_layout.addLayout(main_layout, stretch=1)

        # ================= Dual-Row Bottom Status Bar =================
        status_frame = QFrame()
        status_frame.setObjectName("status_frame")
        status_frame.setFixedHeight(44)
        status_bar_layout = QVBoxLayout()
        status_bar_layout.setContentsMargins(8, 2, 8, 2)
        status_bar_layout.setSpacing(0)

        # Row 1: Cursor values in grey
        self.lbl_cursor_vals = QLabel("CURSOR  [Hover over plot to inspect point]")
        self.lbl_cursor_vals.setFont(QFont("Consolas", 9))
        self.lbl_cursor_vals.setFixedHeight(18)
        status_bar_layout.addWidget(self.lbl_cursor_vals)

        # Row 2: Persistent latest values in bold black
        self.lbl_latest_vals = QLabel("LATEST  Waiting for telemetry...")
        self.lbl_latest_vals.setFont(QFont("Consolas", 9, QFont.Bold))
        self.lbl_latest_vals.setFixedHeight(18)
        status_bar_layout.addWidget(self.lbl_latest_vals)

        status_frame.setLayout(status_bar_layout)
        outer_layout.addWidget(status_frame)

        self.setLayout(outer_layout)

        # Apply initial theme (Light Mode default)
        self.apply_theme()

        # Initial DB population
        self.populate_db_table()

        # Thread setup with completion, error, and operator alert hooks
        self.data_thread = DataFetchThread(world, first_state=wait_forever, states_dict=states_dict)
        self.data_thread.state_update.connect(self.state_update)
        self.data_thread.procedure_finished.connect(self._on_procedure_finished)
        self.data_thread.procedure_error.connect(self._on_procedure_error)
        self.data_thread.operator_action.connect(self._on_operator_action)
        self.data_thread.start()

        # Command IPC timer for automation and testing
        self.cmd_timer = QTimer(self)
        self.cmd_timer.setInterval(500)
        self.cmd_timer.timeout.connect(self._check_external_commands)
        self.cmd_timer.start()

        # Dedicated plot refresh timer
        self.plot_timer = QTimer(self)
        cadence_s = int(self.gui_settings.get("plot_refresh_s", 1))
        self.plot_timer.setInterval(cadence_s * 1000)
        self.plot_timer.timeout.connect(self._on_plot_timer)
        self.plot_timer.start()

    # ------------- Theming & Visual Styling ---------------
    def _set_status_badge(self, text, state_key):
        self.current_badge_state = state_key
        self.lbl_status_badge.setText(text)
        style = STATUS_BADGE_STYLES.get(self.theme, {}).get(state_key, "")
        self.lbl_status_badge.setStyleSheet(style)

    def _set_data_source_badge(self, is_live, text=None):
        if text:
            self.lbl_data_source.setText(text)
        else:
            self.lbl_data_source.setText("● Live" if is_live else "● Historical")
        style_key = "live" if is_live else "history"
        style = DATA_SOURCE_STYLES.get(self.theme, {}).get(style_key, "")
        self.lbl_data_source.setStyleSheet(style)

    def _style_temp_scale_btn(self):
        is_light = (self.theme == "light")
        if self.temp_scale == "log":
            self.btn_toggle_temp_scale.setText("Log Scale")
            if is_light:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #ffffff; color: #0284c7; border: 1px solid #0284c7; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
            else:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #1e293b; color: #38bdf8; border: 1px solid #38bdf8; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
        else:
            self.btn_toggle_temp_scale.setText("Linear Scale")
            if is_light:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #ffffff; color: #d97706; border: 1px solid #d97706; font-weight: 600; padding: 4px 10px; border-radius: 4px;")
            else:
                self.btn_toggle_temp_scale.setStyleSheet("background-color: #1e293b; color: #fbbf24; border: 1px solid #fbbf24; font-weight: 600; padding: 4px 10px; border-radius: 4px;")

    def apply_theme(self):
        is_light = (self.theme == "light")
        self.setStyleSheet(LIGHT_QSS if is_light else DARK_QSS)

        # Matplotlib navigation toolbar
        if is_light:
            self.toolbar.setStyleSheet("background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 4px; padding: 1px;")
        else:
            self.toolbar.setStyleSheet("background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 4px; padding: 1px;")

        self._style_temp_scale_btn()

        if is_light:
            self.btn_theme_toggle.setText("Light")
            self.btn_theme_toggle.setStyleSheet("background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; font-weight: 500; padding: 4px 10px; border-radius: 4px;")
            self.lbl_cursor_vals.setStyleSheet("color: #64748b;")
            self.lbl_latest_vals.setStyleSheet("color: #0f172a;")
        else:
            self.btn_theme_toggle.setText("Dark")
            self.btn_theme_toggle.setStyleSheet("background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; font-weight: 500; padding: 4px 10px; border-radius: 4px;")
            self.lbl_cursor_vals.setStyleSheet("color: #94a3b8;")
            self.lbl_latest_vals.setStyleSheet("color: #f8fafc;")

        self._set_status_badge(self.lbl_status_badge.text(), getattr(self, "current_badge_state", "idle"))
        self._set_data_source_badge(not self.displaying_historical)

        thm = THEMES.get(self.theme, THEMES["light"])
        self.figure.set_facecolor(thm["fig_bg"])

        self.update_plot()

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()

    # ------------- Database Explorer Methods ---------------
    def choose_db_file(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select qcodes Database", str(Path.home() / "2pac_logs"), "Database Files (*.db);;All Files (*)", options=options)
        if file_name:
            self.db_file_path = file_name
            self.populate_db_table()

    def populate_db_table(self):
        if self.db_file_path is None:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            default_db = Path.home() / "2pac_logs" / today / "2pac.db"
            if default_db.exists():
                self.db_file_path = str(default_db)
            else:
                db_files = sorted(Path.home().glob("2pac_logs/**/*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
                if db_files:
                    self.db_file_path = str(db_files[0])

        if not self.db_file_path or not Path(self.db_file_path).exists():
            self.db_table.setRowCount(0)
            return

        try:
            conn = sqlite3.connect(self.db_file_path)
            c = conn.cursor()
            c.execute("SELECT run_id, name, result_table_name, run_timestamp FROM runs ORDER BY run_id DESC")
            rows = c.fetchall()

            valid_runs = []
            for run_id, name, table_name, timestamp in rows:
                try:
                    c.execute(f'SELECT max(rowid) FROM "{table_name}"')
                    res = c.fetchone()
                    cnt = res[0] if res and res[0] is not None else 0
                    if cnt > 0:
                        from plot_utils import epoch_to_local_str
                        t_str = epoch_to_local_str(timestamp) if timestamp else ""
                        valid_runs.append((run_id, name, cnt, t_str))
                except Exception:
                    pass
            conn.close()

            self.db_table.setRowCount(len(valid_runs))
            for row_idx, (r_id, name, cnt, t_str) in enumerate(valid_runs):
                self.db_table.setItem(row_idx, 0, QTableWidgetItem(str(r_id)))
                self.db_table.setItem(row_idx, 1, QTableWidgetItem(str(name)))
                self.db_table.setItem(row_idx, 2, QTableWidgetItem(f"{cnt:,}"))
                self.db_table.setItem(row_idx, 3, QTableWidgetItem(str(t_str)))

        except Exception as e:
            print(f"Error populating DB table: {e}")

    def on_db_row_double_click(self, item):
        self.load_selected_db_run()

    def load_selected_db_run(self):
        selected_items = self.db_table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Select Run", "Please select a run from the table first.")
            return

        row = selected_items[0].row()
        run_id_item = self.db_table.item(row, 0)
        if not run_id_item:
            return

        run_id = int(run_id_item.text())
        try:
            import qcodes
            qcodes.initialise_or_create_database_at(self.db_file_path)
            self.historical_dataset = qcodes.load_by_id(run_id)
            self.displaying_historical = True
            self._set_data_source_badge(False, f"● Run #{run_id}")
            self.btn_live_data.setEnabled(True)
            self.user_has_zoomed = False
            self.update_plot()
            self.main_tabs.setCurrentWidget(self.graphs_tab)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load dataset:\n\n{e}")

    # ------------- Channels Aliases & Script Loader ---------------
    def save_channel_aliases(self):
        for key, inp in self.alias_inputs.items():
            CHANNEL_ALIASES[key] = inp.text().strip() or key
        save_aliases()
        self.update_plot()
        QMessageBox.information(self, "Saved", "Channel aliases updated.")

    def reset_default_aliases(self):
        CHANNEL_ALIASES.update(DEFAULT_CHANNEL_ALIASES)
        for key, inp in self.alias_inputs.items():
            if key in DEFAULT_CHANNEL_ALIASES:
                inp.setText(DEFAULT_CHANNEL_ALIASES[key])
        save_aliases()
        self.update_plot()

    def _populate_state_combo(self):
        cur_key = self.current_selected_state_key() or IDLE_STATE
        self.combo_box.blockSignals(True)
        self.combo_box.clear()

        if not self.expert_mode:
            for key in SIMPLE_WORKFLOW:
                if key in self.states_dict:
                    self.combo_box.addItem(state_label(key), key)
        else:
            first_keys = [k for k in SIMPLE_WORKFLOW if k in self.states_dict]
            other_keys = sorted([k for k in self.states_dict.keys() if k not in SIMPLE_WORKFLOW])
            for key in first_keys + other_keys:
                self.combo_box.addItem(state_label(key), key)

        found_idx = self.combo_box.findData(cur_key)
        if found_idx >= 0:
            self.combo_box.setCurrentIndex(found_idx)
        elif self.combo_box.count() > 0:
            self.combo_box.setCurrentIndex(0)
        self.combo_box.blockSignals(False)

    def current_selected_state_key(self):
        if not hasattr(self, "combo_box"):
            return None
        idx = self.combo_box.currentIndex()
        if idx >= 0:
            data = self.combo_box.itemData(idx)
            if data:
                return str(data)
        txt = self.combo_box.currentText()
        for k in self.states_dict:
            if state_label(k) == txt or k == txt:
                return k
        return None

    def toggle_expert_mode(self, enabled=None):
        if enabled is None:
            self.expert_mode = not self.expert_mode
        else:
            self.expert_mode = bool(enabled)

        self.gui_settings["expert_mode"] = self.expert_mode
        save_gui_settings(self.gui_settings)

        self.btn_toggle_mode.setText("Mode: Expert" if self.expert_mode else "Mode: Simple")
        if hasattr(self, "chk_expert_mode") and self.chk_expert_mode.isChecked() != self.expert_mode:
            self.chk_expert_mode.blockSignals(True)
            self.chk_expert_mode.setChecked(self.expert_mode)
            self.chk_expert_mode.blockSignals(False)

        self.btn_reload_scripts.setVisible(self.expert_mode)

        if self.expert_mode:
            if self.main_tabs.indexOf(self.scripting_tab) == -1:
                self.main_tabs.insertTab(1, self.scripting_tab, "Scripts")
        else:
            idx = self.main_tabs.indexOf(self.scripting_tab)
            if idx != -1:
                if self.main_tabs.currentIndex() == idx:
                    self.main_tabs.setCurrentWidget(self.graphs_tab)
                self.main_tabs.removeTab(idx)

        self._populate_state_combo()

    def show_operator_banner(self, text):
        self.lbl_operator_action.setText(text)
        self.operator_banner.setVisible(True)

    def dismiss_operator_banner(self):
        self.operator_banner.setVisible(False)

    def _on_operator_action(self, state_name, text):
        self.show_operator_banner(text)

    def _on_procedure_finished(self, state_name):
        self._set_status_badge("IDLE", "idle")
        idx = self.combo_box.findData(IDLE_STATE)
        if idx >= 0:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(idx)
            self.combo_box.blockSignals(False)
        self.lbl_script_name.setText(f"Active Script: {state_label(IDLE_STATE)}")
        self.show_operator_banner(f"✓ Procedure '{state_label(state_name)}' completed. Returned to Idle.")

    def _on_procedure_error(self, state_name, err_msg):
        self._set_status_badge("ERROR", "error")
        idx = self.combo_box.findData(IDLE_STATE)
        if idx >= 0:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(idx)
            self.combo_box.blockSignals(False)
        self.lbl_script_name.setText(f"Active Script: {state_label(IDLE_STATE)}")
        self.show_operator_banner(f"⚠️ Error in {state_label(state_name)}: {err_msg}. Reverted safely to Idle.")

    def _build_utils_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # 1. Telemetry and Hardware Loop Group
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
        self.combo_default_range.addItems(["1 Hour", "6 Hours", "24 Hours", "All Time"])
        self.combo_default_range.setCurrentText(self.gui_settings.get("default_range", "6 Hours"))
        self.combo_default_range.currentTextChanged.connect(self._on_default_range_changed)
        telemetry_form.addRow("Default Time Range:", self.combo_default_range)

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
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return tab

    def _on_log_interval_changed(self, val):
        self.world.target_tick_rate_s = float(val)
        self.gui_settings["log_interval_s"] = float(val)
        save_gui_settings(self.gui_settings)

    def _on_plot_cadence_changed(self, val):
        self.plot_timer.setInterval(int(val) * 1000)
        self.gui_settings["plot_refresh_s"] = int(val)
        save_gui_settings(self.gui_settings)

    def _on_text_logs_toggled(self, checked):
        import states
        states.ENABLE_TEXT_LOGGING = bool(checked)
        self.gui_settings["text_logs"] = bool(checked)
        save_gui_settings(self.gui_settings)

    def _on_default_range_changed(self, val):
        self.gui_settings["default_range"] = str(val)
        save_gui_settings(self.gui_settings)

    def pin_to_dock(self):
        try:
            app_dir = Path.home() / ".local" / "share" / "applications"
            app_dir.mkdir(parents=True, exist_ok=True)
            desktop_path = app_dir / "2pac_gui.desktop"
            desktop_content = """[Desktop Entry]
Version=1.0
Type=Application
Name=2pac gui
Comment=Hardware Control GUI for 2pac ADR
Exec=/home/pcuser/qsp/src/2pac/launch_gui.sh
Path=/home/pcuser/qsp/src/2pac
Icon=/home/pcuser/qsp/src/2pac/adr_gui_icon.png
Terminal=false
StartupWMClass=2pac_gui
Categories=Science;Utility;
"""
            desktop_path.write_text(desktop_content)
            desktop_path.chmod(0o755)

            # Also install to Desktop folder
            desktop_desktop_path = Path.home() / "Desktop" / "2pac_gui.desktop"
            desktop_desktop_path.write_text(desktop_content)
            desktop_desktop_path.chmod(0o755)

            try:
                subprocess.run(["update-desktop-database", str(app_dir)], check=False)
            except Exception:
                pass

            res = subprocess.run(["gsettings", "get", "org.gnome.shell", "favorite-apps"],
                                 capture_output=True, text=True, check=True)
            cur_apps = res.stdout.strip()
            if "2pac_gui.desktop" not in cur_apps:
                import ast
                apps_list = ast.literal_eval(cur_apps) if cur_apps.startswith("[") else []
                if "2pac_gui.desktop" not in apps_list:
                    apps_list.append("2pac_gui.desktop")
                    apps_repr = str(apps_list).replace("'", '"')
                    subprocess.run(["gsettings", "set", "org.gnome.shell", "favorite-apps", apps_repr], check=True)
            QMessageBox.information(self, "Pinned", "2pac gui has been pinned to your GNOME dock / sidebar.")
        except Exception as e:
            QMessageBox.warning(self, "Pin Error", f"Could not pin launcher: {e}")

    def open_logs_directory(self):
        d = Path.home() / "2pac_logs"
        d.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(d)])
        except Exception as e:
            QMessageBox.warning(self, "Open Error", f"Could not open folder: {e}")

    def open_scripts_directory(self):
        d = Path.home() / "Desktop" / "custom_scripts"
        d.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(d)])
        except Exception as e:
            QMessageBox.warning(self, "Open Error", f"Could not open folder: {e}")

    def reload_desktop_scripts(self):
        try:
            from custom_script_loader import load_all_desktop_scripts
            custom_states = load_all_desktop_scripts()
            self.states_dict.update(custom_states)
            if hasattr(self, "data_thread"):
                self.data_thread.states_dict.update(custom_states)
            
            cur_key = self.current_selected_state_key()
            self._populate_state_combo()
            if cur_key:
                idx = self.combo_box.findData(cur_key)
                if idx >= 0:
                    self.combo_box.setCurrentIndex(idx)

            QMessageBox.information(self, "Reloaded", f"Loaded {len(custom_states)} script(s) from ~/Desktop/custom_scripts/.")
        except Exception as e:
            QMessageBox.warning(self, "Reload Error", f"Failed to reload desktop scripts:\n\n{e}")

    # ------------- State Control ---------------
    def _check_external_commands(self):
        cmd_file = Path("/tmp/2pac_gui_command.txt")
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
                    for i in range(self.combo_view.count()):
                        if v_name.lower() in self.combo_view.itemText(i).lower():
                            self.combo_view.setCurrentIndex(i)
                            break
                elif cmd.startswith("range:"):
                    r_name = cmd.split("range:")[1].strip()
                    for i in range(self.combo_time_window.count()):
                        if r_name.lower() in self.combo_time_window.itemText(i).lower():
                            self.combo_time_window.setCurrentIndex(i)
                            break
                elif cmd == "pause":
                    self.toggle_pause()
                elif cmd == "stop":
                    self.stop_state(bypass_confirm=True)
                elif cmd == "dismiss_banner":
                    self.dismiss_operator_banner()
                elif cmd.startswith("theme:"):
                    new_theme = cmd.split("theme:")[1].strip()
                    if new_theme in ("light", "dark"):
                        self.theme = new_theme
                        self.apply_theme()
        except Exception as e:
            print(f"Error handling external command: {e}")

    def request_state_change(self, bypass_confirm=False):
        target_state = self.current_selected_state_key()
        if not target_state or target_state not in self.states_dict:
            return

        disp_name = state_label(target_state)
        if not bypass_confirm:
            reply = QMessageBox.question(self, 'Confirm Procedure',
                                         f'Switch to procedure: {disp_name}?',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        self.previewing_state = None
        self.dismiss_operator_banner()

        editor_text = self.text_output.toPlainText()
        lines = editor_text.split('\n')
        clean_lines = []
        for line in lines:
            if line.startswith('--> '):
                clean_lines.append(line[4:])
            elif line.startswith('    '):
                clean_lines.append(line[4:])
            else:
                clean_lines.append(line)
        clean_source = '\n'.join(clean_lines)

        orig_state = self.states_dict.get(target_state)
        orig_content = (orig_state.display_source if orig_state and orig_state.display_source is not None 
                        else (orig_state.raw_source if orig_state else ""))
        is_unmodified = (orig_state is not None and clean_source.strip() == orig_content.strip())

        if is_unmodified or not self.expert_mode:
            self.data_thread.next_state = orig_state
            self.data_thread.paused = False
            self.btn_pause.setText("Pause")
            self._set_status_badge("RUNNING", "running")
            self.lbl_script_name.setText(f"Active Script: {disp_name}")
            return

        try:
            from imperative_statemachine import State, insert_line_number_yields, collect_exits, remove_decorators
            from custom_script_loader import parse_txt_to_python
            import states as states_module

            py_source = parse_txt_to_python(target_state, clean_source)
            source = remove_decorators(py_source)
            new_source = insert_line_number_yields(source)
            exits = collect_exits(source)

            exec_globals = dict(states_module.__dict__)
            new_code = compile(new_source, f"<edited {target_state}>", "exec")
            exec(new_code, exec_globals)

            func_name = None
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("def "):
                    func_name = stripped.split("(")[0].replace("def ", "").strip()
                    break

            if not func_name and target_state in exec_globals:
                func_name = target_state

            if func_name and func_name in exec_globals:
                has_def_in_clean = any(l.strip().startswith("def ") for l in clean_source.splitlines())
                display_src = clean_source if not has_def_in_clean else None
                dynamic_state = State(exits, source, new_source, exec_globals[func_name], display_source=display_src)
                self.states_dict[target_state] = dynamic_state
                if hasattr(self, "data_thread"):
                    self.data_thread.states_dict[target_state] = dynamic_state
                    self.data_thread.next_state = dynamic_state
                    self.data_thread.paused = False
                self.btn_pause.setText("Pause")
                self._set_status_badge("RUNNING", "running")
                self.lbl_script_name.setText(f"Active Script: {disp_name} (modified)")
            else:
                QMessageBox.warning(self, "Error", f"Could not find function for '{disp_name}'.")
        except SyntaxError as se:
            QMessageBox.warning(self, "Syntax Error", f"Syntax error in '{disp_name}' (line {se.lineno}):\n\n{se.text or ''}\n{se}")
        except Exception as e:
            QMessageBox.warning(self, "Compile Error", f"Failed to compile script '{disp_name}':\n\n{e}")

    def on_combo_changed(self, index=None):
        state_key = self.current_selected_state_key()
        if state_key and state_key in self.states_dict:
            state = self.states_dict[state_key]
            self.text_output.setReadOnly(False)
            self.text_output.setText(state.code_highlighted(0))
            self.previewing_state = state_key
            self.lbl_script_name.setText(f"Preview: {state_label(state_key)}")

    def toggle_pause(self):
        if self.data_thread.paused:
            self.data_thread.paused = False
            self.btn_pause.setText("Pause")
            self._set_status_badge("RUNNING", "running")
        else:
            self.data_thread.paused = True
            self.btn_pause.setText("Resume")
            self._set_status_badge("PAUSED", "paused")

    def stop_state(self, bypass_confirm=False):
        if not bypass_confirm:
            reply = QMessageBox.question(self, 'Confirm Stop',
                                         'Stop current procedure and switch to Idle?',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.previewing_state = None
        self.dismiss_operator_banner()
        idx = self.combo_box.findData(IDLE_STATE)
        if idx >= 0 and self.combo_box.currentIndex() != idx:
            self.combo_box.blockSignals(True)
            self.combo_box.setCurrentIndex(idx)
            self.combo_box.blockSignals(False)
        self.data_thread.set_combo_value(IDLE_STATE)
        self._set_status_badge("STOPPED", "stopped")
        self.lbl_script_name.setText(f"Active Script: {state_label(IDLE_STATE)}")

    def return_to_live(self):
        self.displaying_historical = False
        self.historical_dataset = None
        self._set_data_source_badge(True, "● Live")
        self.btn_live_data.setEnabled(False)
        self.user_has_zoomed = False
        self.update_plot()

    # ------------- Plot Interaction ---------------
    def on_view_changed(self, text):
        self.active_plot_tab = text
        self.user_has_zoomed = False
        self.update_plot()

    def on_time_window_changed(self, text):
        tw_map = {
            "1 Hour": "Last 1 Hour",
            "6 Hours": "Last 6 Hours",
            "24 Hours": "Last 24 Hours",
            "All Time": "All Time",
        }
        self.time_window = tw_map.get(text, "Last 6 Hours")
        self.user_has_zoomed = False
        self.update_plot()

    def toggle_temp_scale(self):
        self.temp_scale = "linear" if self.temp_scale == "log" else "log"
        self._style_temp_scale_btn()
        self.user_has_zoomed = False
        self.update_plot()

    def _on_plot_timer(self):
        if self._drag_active:
            return
        if not self.displaying_historical:
            self.update_plot()

    def _find_scroll_axis_and_zone(self, event):
        """
        Determines target axis and zoom zone ('x', 'y', or 'both') based on mouse position.
        Handles event.inaxes as well as hover over axis tick labels outside bounding box.
        """
        if not self.axes_list or event.x is None or event.y is None:
            return None, None

        # 1. If inside an axis bounding box
        if event.inaxes in self.axes_list:
            ax = event.inaxes
            bbox = ax.bbox
            rx = (event.x - bbox.x0) / bbox.width if bbox.width > 0 else 0.5
            ry = (event.y - bbox.y0) / bbox.height if bbox.height > 0 else 0.5
            if ry < 0.25 and rx >= 0.25:
                return ax, "x"
            elif rx < 0.25 and ry >= 0.25:
                return ax, "y"
            elif rx < 0.25 and ry < 0.25:
                return ax, "x" if ry < rx else "y"
            else:
                return ax, "both"

        # 2. If hovering outside bounding box near axis ticks or labels
        for ax in self.axes_list:
            bbox = ax.bbox
            # Hovering near bottom edge (X axis tick numbers / labels)
            if (bbox.x0 - 15 <= event.x <= bbox.x1 + 15) and (bbox.y0 - 45 <= event.y <= bbox.y0 + 5):
                return ax, "x"
            # Hovering near left edge (Y axis tick numbers / labels)
            if (bbox.x0 - 65 <= event.x <= bbox.x0 + 5) and (bbox.y0 - 15 <= event.y <= bbox.y1 + 15):
                return ax, "y"

        # Fallback to first axis X zoom if near the canvas
        return self.axes_list[0], "x"

    def reset_zoom(self):
        self.user_has_zoomed = False
        self._drag_active = False
        self._drag_start_ax = None
        if hasattr(self, 'toolbar') and self.toolbar is not None:
            self.toolbar.update()
        self.update_plot()

    def mpl_on_click(self, event):
        if event.button == 3:  # Right-click resets zoom
            self.reset_zoom()
            return

        if event.button == 1 and event.inaxes in self.axes_list:
            self._drag_active = True
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            self._drag_start_ax = event.inaxes
            self._drag_init_xlim = event.inaxes.get_xlim()
            self._drag_init_ylim = event.inaxes.get_ylim()
            self._drag_has_moved = False

    def mpl_on_release(self, event):
        if event.button == 1:
            self._drag_active = False
            self._drag_start_ax = None

    def mpl_on_scroll(self, event):
        if not self.axes_list:
            return

        ax, zone = self._find_scroll_axis_and_zone(event)
        if ax is None or zone is None:
            return

        scale_factor = 0.8 if event.button == 'up' else 1.25
        zoom_x = (zone in ("x", "both"))
        zoom_y = (zone in ("y", "both"))

        # Zoom X axis (affects all subplots synchronously)
        if zoom_x:
            cur_xlim = self.axes_list[0].get_xlim()
            span_x = cur_xlim[1] - cur_xlim[0]
            if event.xdata is not None:
                x_center = event.xdata
            else:
                bbox = ax.bbox
                if bbox.width > 0 and bbox.x0 <= event.x <= bbox.x1:
                    frac = (event.x - bbox.x0) / bbox.width
                    x_center = cur_xlim[0] + frac * span_x
                else:
                    x_center = (cur_xlim[0] + cur_xlim[1]) / 2.0

            new_xlim = [x_center - (x_center - cur_xlim[0]) * scale_factor,
                        x_center + (cur_xlim[1] - x_center) * scale_factor]
            for a in self.axes_list:
                a.set_xlim(new_xlim)

        # Zoom Y axis (affects target subplot only)
        if zoom_y:
            cur_ylim = ax.get_ylim()
            if ax.get_yscale() == 'log' and cur_ylim[0] > 0 and cur_ylim[1] > 0:
                log_min = np.log10(cur_ylim[0])
                log_max = np.log10(cur_ylim[1])
                span_log = log_max - log_min
                if event.ydata is not None and event.ydata > 0:
                    log_center = np.log10(event.ydata)
                else:
                    bbox = ax.bbox
                    if bbox.height > 0 and bbox.y0 <= event.y <= bbox.y1:
                        frac = (event.y - bbox.y0) / bbox.height
                        log_center = log_min + frac * span_log
                    else:
                        log_center = (log_min + log_max) / 2.0

                new_log_min = log_center - (log_center - log_min) * scale_factor
                new_log_max = log_center + (log_max - log_center) * scale_factor
                new_log_min = max(-10.0, new_log_min)
                new_log_max = min(10.0, new_log_max)
                ax.set_ylim([10 ** new_log_min, 10 ** new_log_max])
            else:
                span_y = cur_ylim[1] - cur_ylim[0]
                if event.ydata is not None:
                    y_center = event.ydata
                else:
                    bbox = ax.bbox
                    if bbox.height > 0 and bbox.y0 <= event.y <= bbox.y1:
                        frac = (event.y - bbox.y0) / bbox.height
                        y_center = cur_ylim[0] + frac * span_y
                    else:
                        y_center = (cur_ylim[0] + cur_ylim[1]) / 2.0

                new_ylim = [y_center - (y_center - cur_ylim[0]) * scale_factor,
                            y_center + (cur_ylim[1] - y_center) * scale_factor]
                ax.set_ylim(new_ylim)

        self.user_has_zoomed = True
        self.canvas.draw_idle()

    def mpl_on_mouse_move(self, event):
        self.on_mouse_move_event = event

        # Handle left-click dragging and panning
        if self._drag_active and self._drag_start_ax is not None and event.x is not None and event.y is not None:
            dx = event.x - self._drag_start_x
            dy = event.y - self._drag_start_y
            if not self._drag_has_moved and (abs(dx) > 3 or abs(dy) > 3):
                self._drag_has_moved = True
                self.user_has_zoomed = True

            if self._drag_has_moved:
                ax = self._drag_start_ax
                bbox = ax.bbox
                if bbox.width > 0 and bbox.height > 0:
                    # Shift X across all subplots
                    x_min0, x_max0 = self._drag_init_xlim
                    span_x = x_max0 - x_min0
                    shift_x = (dx / bbox.width) * span_x
                    new_xlim = (x_min0 - shift_x, x_max0 - shift_x)
                    for a in self.axes_list:
                        a.set_xlim(new_xlim)

                    # Shift Y for the dragged subplot
                    y_min0, y_max0 = self._drag_init_ylim
                    if ax.get_yscale() == 'log' and y_min0 > 0 and y_max0 > 0:
                        log_min = np.log10(y_min0)
                        log_max = np.log10(y_max0)
                        span_log_y = log_max - log_min
                        shift_log_y = (dy / bbox.height) * span_log_y
                        new_ylim = (10 ** (log_min - shift_log_y), 10 ** (log_max - shift_log_y))
                    else:
                        span_y = y_max0 - y_min0
                        shift_y = (dy / bbox.height) * span_y
                        new_ylim = (y_min0 - shift_y, y_max0 - shift_y)
                    ax.set_ylim(new_ylim)

                    self.canvas.draw_idle()

        self._update_cursor_status()

    # ------------- Dual-Row Status Bar ---------------
    def _format_val(self, key, val, units):
        alias = display_name(key)
        unit = units.get(key, "")
        if isinstance(val, (int, float)):
            if np.isnan(val):
                return f"{alias}: NaN"
            return f"{alias}: {val:.3f} {unit}".strip()
        return f"{alias}: {val}"

    def _update_latest_status(self, data_mr, units, keys):
        if not data_mr:
            self.lbl_latest_vals.setText("LATEST  Waiting for telemetry...")
            return

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
            from plot_utils import get_time_vector, epoch_to_local_str
            t = get_time_vector(dataset, data)
            if t is None or len(t) == 0:
                return
            xloc_ind = np.argmin(np.abs(t - event.xdata))
            units = {p.name: p.unit for p in dataset.get_parameters()}

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

    # ------------- Core Update ---------------
    def state_update(self, s1, s2):
        running_state = s1.split(" ")[0].replace("state=", "") if s1.startswith("state=") else ""
        
        # Update badge
        if "PAUSED" in s1:
            self._set_status_badge("PAUSED", "paused")
        elif running_state == IDLE_STATE:
            self._set_status_badge("IDLE", "idle")
        else:
            self._set_status_badge("RUNNING", "running")

        disp_title = state_label(running_state)
        self.setWindowTitle(f"2pac gui — {disp_title}")

        if self.previewing_state is None or self.previewing_state == running_state:
            self.previewing_state = None
            if running_state in self.states_dict:
                idx = self.combo_box.findData(running_state)
                if idx >= 0 and self.combo_box.currentIndex() != idx:
                    self.combo_box.blockSignals(True)
                    self.combo_box.setCurrentIndex(idx)
                    self.combo_box.blockSignals(False)

            self.lbl_script_name.setText(f"Active Script: {disp_title}")
            self.text_output.setReadOnly(False)
            self.text_output.setText(s2)
            textCursor = self.text_output.textCursor()
            textCursor.setPosition(get_arrow_char_index(s2, plus=100))
            color_line(self.text_output, get_arrow_linenum(s2), theme=self.theme)
            self.text_output.setTextCursor(textCursor)

        if not self.displaying_historical:
            self.update_plot()

    def update_plot(self):
        dataset = self.historical_dataset if self.displaying_historical else self.live_dataset
        xloc_for_vals = self.on_mouse_move_event.xdata if self.on_mouse_move_event and self.on_mouse_move_event.inaxes else None

        saved_xlim = self.axes_list[0].get_xlim() if (self.user_has_zoomed and self.axes_list) else None
        saved_ylims = [ax.get_ylim() for ax in self.axes_list] if (self.user_has_zoomed and self.axes_list) else []

        active_tw = "All Time" if (self.user_has_zoomed or self.displaying_historical) else self.time_window
        result = plot_dataset(self.figure, dataset, xloc_for_vals, filter_tab=self.active_plot_tab,
                              temp_scale=self.temp_scale, time_window=active_tw, theme=self.theme)
        data_mr, data_xloc, units, keys, self.axes_list = result

        if self.axes_list:
            if self.user_has_zoomed and saved_xlim is not None:
                self.axes_list[0].set_xlim(saved_xlim)
                for idx, ax in enumerate(self.axes_list):
                    if idx < len(saved_ylims):
                        ax.set_ylim(saved_ylims[idx])

        self._update_latest_status(data_mr, units, keys)
        self.canvas.draw_idle()
