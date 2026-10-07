"""
Daily Logging and Dataset Engine for 2pac ADR Cryostat.

Replaces fragmented QCoDeS 'runs' with a continuous, daily-split telemetry architecture:
- Logs are strictly partitioned by day: ~/2pac_logs/<YYYY-MM-DD>/2pac.db
- Reopening the application on the same day resumes and appends to the day's record
  instead of creating Run 1, Run 2, Run 3...
- Automatic midnight rollover creates the next day's log folder and database without restarting.
- Fully compatible with plot_utils.py (provides .cache.data() and .get_parameters()).
- Preserves instrument settings on exit: hardware outputs (Lake Shore 370 DAC, Cryo-con,
  LabJack latching relays) are never reset on application exit or computer shutdown.
"""

import time
import sqlite3
import bisect
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

PARAM_UNITS = {
    "cryocon_chA_temperature": "K",
    "cryocon_chB_temperature": "K",
    "cryocon_chC_temperature": "K",
    "cryocon_chD_temperature": "K",
    "faa_temperature": "K",
    "labjack_he3_pressure": "bar",
    "labjack_kepco_current": "A",
    "labjack_kepco_voltage": "V",
    "ls370_heater_out": "%",
    "labjack_relay": "",
    "labjack_heatswitch_pot": "",
    "labjack_heatswitch_charcoal": "",
    "labjack_heatswitch_adr": "",
    "vac_can_pressure_torr": "Torr",
    "labjack_vac_can_pressure_torr": "Torr",
    "state": "",
    "time": "s",
    "elapsed_time": "s"
}

PARAM_NAME_MAP = {
    "chA_temperature": "cryocon_chA_temperature",
    "chB_temperature": "cryocon_chB_temperature",
    "chC_temperature": "cryocon_chC_temperature",
    "chD_temperature": "cryocon_chD_temperature",
    "kepco_current": "labjack_kepco_current",
    "kepco_voltage": "labjack_kepco_voltage",
    "he3_pressure": "labjack_he3_pressure",
    "vac_can_pressure_torr": "vac_can_pressure_torr",
    "labjack_vac_can_pressure_torr": "vac_can_pressure_torr",
    "vac_can_pressure": "vac_can_pressure_torr",
    "vac_can": "vac_can_pressure_torr",
    "heatswitch_pot": "labjack_heatswitch_pot",
    "heatswitch_charcoal": "labjack_heatswitch_charcoal",
    "heatswitch_adr": "labjack_heatswitch_adr",
    "relay": "labjack_relay",
    "out": "ls370_heater_out",
    "ls370_heater_out": "ls370_heater_out",
}

NUMERIC_COLUMNS = [
    "time", "elapsed_time",
    "cryocon_chA_temperature", "cryocon_chB_temperature",
    "cryocon_chC_temperature", "cryocon_chD_temperature",
    "faa_temperature", "labjack_he3_pressure",
    "vac_can_pressure_torr",
    "labjack_kepco_current", "labjack_kepco_voltage",
    "ls370_heater_out"
]

TEXT_COLUMNS = [
    "state", "labjack_relay",
    "labjack_heatswitch_pot", "labjack_heatswitch_charcoal",
    "labjack_heatswitch_adr"
]

ALL_COLUMNS = NUMERIC_COLUMNS + TEXT_COLUMNS


import threading


class ParamInfo:
    def __init__(self, name: str, unit: str = ""):
        self.name = name
        self.unit = unit

    def __repr__(self):
        return f"ParamInfo({self.name}, unit='{self.unit}')"


class DailyDatasetCache:
    """Provides the .data() method expected by plot_utils.plot_dataset with thread-safety."""
    def __init__(self, data_dict: Dict[str, Any], lock: Optional[threading.Lock] = None):
        self._data_dict = data_dict
        self._lock = lock
        self._cached_arrays: Optional[Dict[str, Dict[str, np.ndarray]]] = None
        self._cached_len: int = 0

    def invalidate(self):
        self._cached_arrays = None
        self._cached_len = 0

    def data(self) -> Dict[str, Dict[str, np.ndarray]]:
        if self._lock:
            with self._lock:
                return self._compute_data()
        return self._compute_data()

    def _compute_data(self) -> Dict[str, Dict[str, np.ndarray]]:
        if not self._data_dict:
            return {}
        lens = [len(v) for v in self._data_dict.values()]
        min_len = min(lens) if lens else 0
        if min_len == 0:
            return {k: {k: np.array([])} for k in self._data_dict}

        if self._cached_arrays is not None and self._cached_len == min_len:
            return self._cached_arrays

        res = {}
        for k, v in self._data_dict.items():
            if isinstance(v, (list, tuple)):
                res[k] = {k: np.array(list(v[:min_len]))}
            elif isinstance(v, np.ndarray):
                res[k] = {k: np.array(v[:min_len])}
            else:
                res[k] = {k: np.array([v])}
        self._cached_arrays = res
        self._cached_len = min_len
        return res


class DailyDataset:
    """Wrapper that mimics a QCoDeS dataset for plotting and querying."""
    def __init__(self, date_str: str, data_dict: Dict[str, Any], db_path: Optional[str] = None, lock: Optional[threading.Lock] = None):
        self.name = f"Daily Log ({date_str})"
        self.table_name = "telemetry"
        self.date_str = date_str
        self.db_path = db_path
        self._raw_data = data_dict
        self._lock = lock
        self.cache = DailyDatasetCache(data_dict, lock=lock)

    def get_parameters(self) -> List[ParamInfo]:
        params = []
        for col in ALL_COLUMNS:
            params.append(ParamInfo(col, PARAM_UNITS.get(col, "")))
        return params

    @property
    def number_of_results(self) -> int:
        if self._lock:
            with self._lock:
                times = self._raw_data.get("time", [])
                return len(times)
        times = self._raw_data.get("time", [])
        return len(times)


class DailyLogManager:
    """
    Manages continuous logging split by day.
    Reopening the app on the same day appends to the day's database.
    """
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or (Path.home() / "2pac_logs")
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self.current_day: str = ""
        self.db_path: Optional[Path] = None
        self.conn: Optional[sqlite3.Connection] = None
        self.in_memory_data: Dict[str, List[Any]] = {}
        self.dataset: Optional[DailyDataset] = None

        self._pending_rows: List[tuple] = []
        self._last_commit_time = time.time()
        self._start_time = time.time()

        self._init_for_today()

    def _canonical_name(self, raw_name: str) -> str:
        name = PARAM_NAME_MAP.get(raw_name, raw_name)
        return name

    def _init_for_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.conn is not None:
            try:
                self.flush()
                self.conn.close()
            except Exception:
                pass

        self.current_day = today
        day_dir = self.base_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = day_dir / "2pac.db"

        # Initialize SQLite with WAL mode for fast writes and non-blocking reads
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        # Create telemetry table if not exists
        cols_sql = ["time REAL", "local_time TEXT", "elapsed_time REAL"]
        for col in NUMERIC_COLUMNS:
            if col not in ("time", "elapsed_time"):
                cols_sql.append(f"{col} REAL")
        for col in TEXT_COLUMNS:
            cols_sql.append(f"{col} TEXT")

        self.conn.execute(f"CREATE TABLE IF NOT EXISTS telemetry ({', '.join(cols_sql)})")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(time)")

        # Ensure any newly added columns exist in existing telemetry table
        c = self.conn.cursor()
        c.execute("PRAGMA table_info(telemetry)")
        existing_cols = {row[1] for row in c.fetchall()}
        for col in NUMERIC_COLUMNS:
            if col not in existing_cols and col not in ("time", "elapsed_time"):
                try:
                    self.conn.execute(f"ALTER TABLE telemetry ADD COLUMN {col} REAL")
                except Exception:
                    pass
        for col in TEXT_COLUMNS:
            if col not in existing_cols:
                try:
                    self.conn.execute(f"ALTER TABLE telemetry ADD COLUMN {col} TEXT")
                except Exception:
                    pass
        self.conn.commit()

        # Initialize in-memory arrays
        with self._lock:
            self.in_memory_data = {col: [] for col in ALL_COLUMNS}

        # Check if telemetry table already has existing rows from earlier today
        c = self.conn.cursor()
        c.execute("SELECT count(*) FROM telemetry")
        existing_rows_count = c.fetchone()[0]

        if existing_rows_count > 0:
            print(f"[DailyLogManager] Found {existing_rows_count:,} existing telemetry rows for {today}. Loading into memory...")
            self._load_from_sqlite()
        else:
            # Check if per-channel .log files exist from today and import them
            self._import_from_text_logs_if_present(day_dir)

        # Preload recent historical data from preceding days for smooth rolling plots across midnight
        self._preload_recent_history()

        if self.dataset is None:
            self.dataset = DailyDataset(today, self.in_memory_data, str(self.db_path), lock=self._lock)
        else:
            self.dataset.date_str = today
            self.dataset.name = f"Daily Log ({today})"
            self.dataset.db_path = str(self.db_path)
            self.dataset._raw_data = self.in_memory_data
            self.dataset.cache = DailyDatasetCache(self.in_memory_data, lock=self._lock)

    def _load_from_sqlite(self):
        c = self.conn.cursor()
        c.execute("PRAGMA table_info(telemetry)")
        db_cols = {r[1] for r in c.fetchall()}
        col_names = ALL_COLUMNS
        avail_cols = [c if c in db_cols else f"NULL as {c}" for c in col_names]
        query = f"SELECT {', '.join(avail_cols)} FROM telemetry ORDER BY time ASC"
        c.execute(query)
        rows = c.fetchall()
        if not rows:
            return

        with self._lock:
            for col_idx, col_name in enumerate(col_names):
                vals = [r[col_idx] for r in rows]
                if col_name in NUMERIC_COLUMNS:
                    self.in_memory_data[col_name] = [float(v) if v is not None else np.nan for v in vals]
                else:
                    self.in_memory_data[col_name] = [str(v) if v is not None else "" for v in vals]
            if self.dataset and self.dataset.cache:
                self.dataset.cache.invalidate()

    def _import_from_text_logs_if_present(self, day_dir: Path):
        """If SQLite telemetry is empty but .log files exist for today, import them seamlessly."""
        time_log = day_dir / "time.log"
        if not time_log.exists():
            return

        try:
            print(f"[DailyLogManager] Importing today's existing text logs into {self.db_path.name}...")
            # Read timestamps
            timestamps = []
            local_times = []
            with open(time_log, "r") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) >= 3:
                        try:
                            timestamps.append(float(parts[0]))
                            local_times.append(parts[1])
                        except ValueError:
                            pass

            n_pts = len(timestamps)
            if n_pts == 0:
                return

            channel_data = {}
            for col in ALL_COLUMNS:
                if col in ("time", "elapsed_time"):
                    continue
                # Find corresponding .log file
                # Check direct name or short name
                candidates = [f"{col}.log"]
                for short, canonical in PARAM_NAME_MAP.items():
                    if canonical == col:
                        candidates.append(f"{short}.log")

                found_log = None
                for cand in candidates:
                    p = day_dir / cand
                    if p.exists():
                        found_log = p
                        break

                vals = []
                if found_log:
                    with open(found_log, "r") as f:
                        for line in f:
                            parts = line.strip().split(",")
                            if len(parts) >= 3:
                                raw_v = parts[2]
                                if col in NUMERIC_COLUMNS:
                                    try:
                                        vals.append(float(raw_v))
                                    except ValueError:
                                        vals.append(np.nan)
                                else:
                                    vals.append(raw_v)
                # Pad or slice to match length
                if len(vals) < n_pts:
                    fill = np.nan if col in NUMERIC_COLUMNS else ""
                    vals.extend([fill] * (n_pts - len(vals)))
                elif len(vals) > n_pts:
                    vals = vals[:n_pts]
                channel_data[col] = vals

            # Populate in-memory
            with self._lock:
                self.in_memory_data["time"] = list(timestamps)
                t0 = timestamps[0] if timestamps else time.time()
                self.in_memory_data["elapsed_time"] = [t - t0 for t in timestamps]
                for col in ALL_COLUMNS:
                    if col not in ("time", "elapsed_time"):
                        self.in_memory_data[col] = channel_data.get(col, [np.nan] * n_pts)
                if self.dataset and self.dataset.cache:
                    self.dataset.cache.invalidate()

            # Insert batch into SQLite
            insert_cols = ["time", "local_time", "elapsed_time"] + [c for c in ALL_COLUMNS if c not in ("time", "elapsed_time")]
            placeholders = ", ".join(["?"] * len(insert_cols))
            insert_sql = f"INSERT INTO telemetry ({', '.join(insert_cols)}) VALUES ({placeholders})"

            batch_rows = []
            for i in range(n_pts):
                r = [timestamps[i], local_times[i] if i < len(local_times) else "", timestamps[i] - t0]
                for c in insert_cols[3:]:
                    r.append(self.in_memory_data[c][i])
                batch_rows.append(tuple(r))

            self.conn.executemany(insert_sql, batch_rows)
            self.conn.commit()
            print(f"[DailyLogManager] Successfully imported {n_pts:,} data points for today!")
        except Exception as e:
            print(f"[DailyLogManager] Warning: failed to import text logs: {e}")

    def _preload_recent_history(self, cutoff_time: Optional[float] = None):
        """
        Preloads telemetry from preceding days into self.in_memory_data
        so rolling time windows ('Last 6 Hours', 'Last 24 Hours', and multi-day cooldowns)
        span seamlessly across midnight boundaries without truncation.
        """
        if cutoff_time is None:
            cutoff_time = time.time() - (8 * 86400)  # past 8 days (covers 7 full days)

        days_to_check = []
        try:
            today_dt = datetime.strptime(self.current_day, "%Y-%m-%d")
        except Exception:
            today_dt = datetime.now()

        for d in range(8, 0, -1):
            day_str = (today_dt - timedelta(days=d)).strftime("%Y-%m-%d")
            db_p = self.base_dir / day_str / "2pac.db"
            if db_p.exists():
                days_to_check.append(db_p)

        if not days_to_check:
            return

        all_prev_rows = []
        col_names = ALL_COLUMNS
        cols_query = ", ".join(col_names)

        for db_p in days_to_check:
            try:
                conn = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
                c = conn.cursor()
                c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='telemetry'")
                if not c.fetchone():
                    conn.close()
                    continue
                c.execute("PRAGMA table_info(telemetry)")
                db_cols = {r[1] for r in c.fetchall()}
                avail_cols = [c if c in db_cols else f"NULL as {c}" for c in col_names]
                c.execute(f"SELECT {', '.join(avail_cols)} FROM telemetry WHERE time >= ? ORDER BY time ASC", (cutoff_time,))
                rows = c.fetchall()
                conn.close()
                if rows:
                    all_prev_rows.extend(rows)
            except Exception as e:
                print(f"[DailyLogManager] Warning: failed to preload history from {db_p}: {e}")

        if not all_prev_rows:
            return

        with self._lock:
            # Prepend to in_memory_data
            for col_idx, col_name in enumerate(col_names):
                if col_name in NUMERIC_COLUMNS:
                    hist_vals = [float(r[col_idx]) if r[col_idx] is not None else np.nan for r in all_prev_rows]
                else:
                    hist_vals = [str(r[col_idx]) if r[col_idx] is not None else "" for r in all_prev_rows]
                self.in_memory_data[col_name] = hist_vals + self.in_memory_data.get(col_name, [])

            if self.in_memory_data.get("time"):
                t0 = self.in_memory_data["time"][0]
                self.in_memory_data["elapsed_time"] = [t - t0 for t in self.in_memory_data["time"]]

            if self.dataset and self.dataset.cache:
                self.dataset.cache.invalidate()

        print(f"[DailyLogManager] Preloaded {len(all_prev_rows):,} historical data points from previous days for smooth multi-day plotting.")

    def _rollover_to_new_day(self, today: str):
        """
        Rotates SQLite storage to a new day directory at midnight without wiping
        in-memory history or invalidating the live dataset reference.
        Retains the last 48 hours of telemetry for seamless rolling plots.
        """
        # 1. Flush any uncommitted rows to yesterday's database
        try:
            self.flush()
            if self.conn is not None:
                self.conn.close()
        except Exception as e:
            print(f"[DailyLogManager] Error closing yesterday's database: {e}")

        # 2. Update to new day
        self.current_day = today
        day_dir = self.base_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = day_dir / "2pac.db"

        # 3. Open new day SQLite database
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        cols_sql = ["time REAL", "local_time TEXT", "elapsed_time REAL"]
        for col in NUMERIC_COLUMNS:
            if col not in ("time", "elapsed_time"):
                cols_sql.append(f"{col} REAL")
        for col in TEXT_COLUMNS:
            cols_sql.append(f"{col} TEXT")

        self.conn.execute(f"CREATE TABLE IF NOT EXISTS telemetry ({', '.join(cols_sql)})")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(time)")
        self.conn.commit()

        # 4. Prune points older than 8 days from in_memory_data
        cutoff = time.time() - (8 * 86400)
        with self._lock:
            times = self.in_memory_data.get("time", [])
            if times:
                idx = bisect.bisect_left(times, cutoff)
                if idx > 0 and idx < len(times):
                    for col in ALL_COLUMNS:
                        if col in self.in_memory_data:
                            self.in_memory_data[col] = self.in_memory_data[col][idx:]
                    if self.in_memory_data["time"]:
                        t0 = self.in_memory_data["time"][0]
                        self.in_memory_data["elapsed_time"] = [t - t0 for t in self.in_memory_data["time"]]

        # 5. Update dataset metadata in-place
        if self.dataset:
            self.dataset.date_str = today
            self.dataset.name = f"Daily Log ({today})"
            self.dataset.db_path = str(self.db_path)
            if self.dataset.cache:
                self.dataset.cache.invalidate()

        print(f"[DailyLogManager] Seamless rollover complete: now logging to {self.db_path}. In-memory points retained: {len(self.in_memory_data.get('time', [])):,}.")

    def add_result(self, *res_tuple):
        """Called every tick by states.update(datasaver, state)."""
        now = time.time()
        row_dict: Dict[str, Any] = {}
        for item in res_tuple:
            if isinstance(item, tuple) and len(item) == 2:
                param, val = item
                if isinstance(param, str):
                    name = param
                else:
                    name = getattr(param, "name", str(param))
                canon = self._canonical_name(name)
                row_dict[canon] = val

        t_val = float(row_dict.get("time", now))
        today = datetime.fromtimestamp(t_val).strftime("%Y-%m-%d")

        # Midnight rollover check
        if today != self.current_day:
            print(f"[DailyLogManager] Rolling over to new day: {today}")
            self._rollover_to_new_day(today)

        local_time_str = datetime.fromtimestamp(t_val).strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            times = self.in_memory_data["time"]
            if times:
                t0 = times[0]
            else:
                t0 = t_val
            elapsed_val = t_val - t0

            row_dict["time"] = t_val
            row_dict["local_time"] = local_time_str
            row_dict["elapsed_time"] = elapsed_val

            # Append to in-memory buffers
            for col in ALL_COLUMNS:
                v = row_dict.get(col, None)
                if col in NUMERIC_COLUMNS:
                    try:
                        num_v = float(v) if v is not None else np.nan
                    except (ValueError, TypeError):
                        num_v = np.nan
                    self.in_memory_data[col].append(num_v)
                else:
                    self.in_memory_data[col].append(str(v) if v is not None else "")

            if self.dataset and self.dataset.cache:
                self.dataset.cache.invalidate()

        # Queue for SQLite
        insert_cols = ["time", "local_time", "elapsed_time"] + [c for c in ALL_COLUMNS if c not in ("time", "elapsed_time")]
        row_tuple = [row_dict.get("time", t_val), local_time_str, elapsed_val]
        for c in insert_cols[3:]:
            row_tuple.append(row_dict.get(c, None))
        self._pending_rows.append(tuple(row_tuple))

        # Periodic SQLite commit (every 1 second)
        if (now - self._last_commit_time) >= 1.0:
            self.flush()

    def flush(self):
        if not self._pending_rows or self.conn is None:
            return
        try:
            insert_cols = ["time", "local_time", "elapsed_time"] + [c for c in ALL_COLUMNS if c not in ("time", "elapsed_time")]
            placeholders = ", ".join(["?"] * len(insert_cols))
            sql = f"INSERT INTO telemetry ({', '.join(insert_cols)}) VALUES ({placeholders})"
            self.conn.executemany(sql, self._pending_rows)
            self.conn.commit()
            self._pending_rows.clear()
            self._last_commit_time = time.time()
        except Exception as e:
            print(f"[DailyLogManager] Flush error: {e}")

    def close(self):
        self.flush()
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def load_daily_dataset(path_or_date: str) -> DailyDataset:
    """Load a day's dataset from a date string (YYYY-MM-DD), folder, or sqlite database path."""
    p = Path(path_or_date)
    if not p.exists() and len(path_or_date) == 10 and "-" in path_or_date:
        p = Path.home() / "2pac_logs" / path_or_date / "2pac.db"

    if p.is_dir():
        db_file = p / "2pac.db"
    else:
        db_file = p

    date_str = p.parent.name if p.is_file() else p.name
    data_dict = {col: [] for col in ALL_COLUMNS}

    if db_file.exists():
        conn = sqlite3.connect(str(db_file))
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry'")
        if c.fetchone():
            c.execute("PRAGMA table_info(telemetry)")
            db_cols = {r[1] for r in c.fetchall()}
            avail_cols = [col if col in db_cols else f"NULL as {col}" for col in ALL_COLUMNS]
            c.execute(f"SELECT {', '.join(avail_cols)} FROM telemetry ORDER BY time ASC")
            rows = c.fetchall()
            for col_idx, col_name in enumerate(ALL_COLUMNS):
                vals = [r[col_idx] for r in rows]
                if col_name in NUMERIC_COLUMNS:
                    data_dict[col_name] = np.array([float(v) if v is not None else np.nan for v in vals], dtype=float)
                else:
                    data_dict[col_name] = np.array([str(v) if v is not None else "" for v in vals], dtype=object)
            conn.close()
            return DailyDataset(date_str, data_dict, str(db_file))
        else:
            # Legacy QCoDeS db: check for latest run
            c.execute("SELECT run_id, result_table_name FROM runs ORDER BY run_id DESC LIMIT 1")
            row = c.fetchone()
            conn.close()
            if row:
                import qcodes
                qcodes.initialise_or_create_database_at(str(db_file))
                return qcodes.load_by_id(row[0])

    # If no SQLite telemetry, load from text log files in the directory
    day_dir = db_file.parent
    time_log = day_dir / "time.log"
    if time_log.exists():
        timestamps = []
        with open(time_log) as f:
            for l in f:
                parts = l.strip().split(",")
                if len(parts) >= 3:
                    try:
                        timestamps.append(float(parts[0]))
                    except ValueError:
                        pass
        n = len(timestamps)
        if n > 0:
            data_dict["time"] = np.array(timestamps, dtype=float)
            data_dict["elapsed_time"] = np.array(timestamps) - timestamps[0]

            for col in ALL_COLUMNS:
                if col in ("time", "elapsed_time"):
                    continue
                cand = [f"{col}.log"]
                for s, can in PARAM_NAME_MAP.items():
                    if can == col:
                        cand.append(f"{s}.log")
                found = None
                for cd in cand:
                    if (day_dir / cd).exists():
                        found = day_dir / cd
                        break
                if found:
                    arr = []
                    with open(found) as f:
                        for l in f:
                            pts = l.strip().split(",")
                            if len(pts) >= 3:
                                if col in NUMERIC_COLUMNS:
                                    try:
                                        arr.append(float(pts[2]))
                                    except ValueError:
                                        arr.append(np.nan)
                                else:
                                    arr.append(pts[2])
                    if len(arr) < n:
                        fill = np.nan if col in NUMERIC_COLUMNS else ""
                        arr.extend([fill] * (n - len(arr)))
                    data_dict[col] = np.array(arr[:n])
                else:
                    fill = np.nan if col in NUMERIC_COLUMNS else ""
                    data_dict[col] = np.array([fill] * n)
            return DailyDataset(date_str, data_dict, str(db_file))

    return DailyDataset(date_str, data_dict, str(db_file))


def list_daily_logs(base_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan ~/2pac_logs for available daily records."""
    d = base_dir or (Path.home() / "2pac_logs")
    if not d.exists():
        return []

    entries = []
    for item in sorted(d.iterdir(), reverse=True):
        if item.is_dir() and item.name.count("-") == 2:
            date_str = item.name
            db_file = item / "2pac.db"
            faa_log = item / "faa_temperature.log"
            time_log = item / "time.log"

            points = 0
            size_bytes = 0
            time_range_str = "—"

            if db_file.exists():
                size_bytes += db_file.stat().st_size
                try:
                    conn = sqlite3.connect(str(db_file))
                    c = conn.cursor()
                    c.execute("SELECT count(*), min(time), max(time) FROM telemetry")
                    r = c.fetchone()
                    conn.close()
                    if r and r[0] > 0:
                        points = r[0]
                        if r[1] and r[2]:
                            t_start = datetime.fromtimestamp(r[1]).strftime("%H:%M:%S")
                            t_end = datetime.fromtimestamp(r[2]).strftime("%H:%M:%S")
                            time_range_str = f"{t_start} — {t_end}"
                except Exception:
                    pass

            if points == 0 and time_log.exists():
                try:
                    size_bytes += time_log.stat().st_size
                    with open(time_log) as f:
                        lines = f.readlines()
                        points = len(lines)
                        if lines:
                            p0 = lines[0].split(",")
                            p1 = lines[-1].split(",")
                            if len(p0) >= 2 and len(p1) >= 2:
                                t_start = p0[1].split()[-1] if len(p0[1].split()) > 1 else p0[1]
                                t_end = p1[1].split()[-1] if len(p1[1].split()) > 1 else p1[1]
                                time_range_str = f"{t_start} — {t_end}"
                except Exception:
                    pass

            entries.append({
                "date": date_str,
                "path": str(db_file if db_file.exists() else item),
                "points": points,
                "time_range": time_range_str,
                "size_mb": size_bytes / (1024 * 1024)
            })

    return entries


HARDWARE_STATE_FILE = Path.home() / "2pac_logs" / "last_hardware_state.json"

def save_hardware_state(magnet_current: float = 0.0,
                        he3_pressure: float = 0.0,
                        active_procedure: str = "wait_forever",
                        phase_name: str = "Idle",
                        temperatures: Optional[Dict[str, float]] = None,
                        heatswitches: Optional[Dict[str, str]] = None):
    """
    Persist current hardware and procedure state on application exit or shutdown.
    Ensures safe recovery and records that instrument settings are held.
    """
    state_payload = {
        "timestamp": time.time(),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "magnet_current": float(magnet_current),
        "he3_pressure_bar": float(he3_pressure),
        "active_procedure": str(active_procedure),
        "phase_name": str(phase_name),
        "temperatures": temperatures or {},
        "heatswitches": heatswitches or {"pot": "CLOSED", "adr": "CLOSED", "charcoal": "CLOSED"},
        "status": "HELD_SAFE",
        "notice": "Physical instrument settings (Lake Shore 370 DAC, Cryo-con, LabJack relays) held without reset."
    }
    try:
        HARDWARE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json
        HARDWARE_STATE_FILE.write_text(json.dumps(state_payload, indent=2))
    except Exception as e:
        print(f"Warning: could not save hardware state: {e}")

def get_last_hardware_state() -> Optional[Dict[str, Any]]:
    """Read last saved hardware state if available."""
    if not HARDWARE_STATE_FILE.exists():
        return None
    try:
        import json
        return json.loads(HARDWARE_STATE_FILE.read_text())
    except Exception:
        return None
