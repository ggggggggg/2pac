# Legacy modules (not used by the GUI)

Moved here on 2026-11-18 (POST_CYCLE_FIXES P1-7). These are older copies of code whose live versions are:

| Legacy file | Live version |
|---|---|
| world.py, world_no_mpl.py, imperative_statemachine.py, custom_script_loader.py, nonblocking_readline.py | `engine/` |
| lakeshore370.py, labjacku3.py, cryocon24c.py, station_2pac.py | `instruments/` |
| log_data.py, read_logs.py | `daily_logger.py` (GUI logging) |

The live path is `main.py` -> `engine/`, `instruments/`, `states.py`, `gui.py`. Nothing imports these files.
They diverge from the live code (e.g. legacy `world.py` lacks the scheduler and wait-guard fixes), so do not
edit or run them; delete them once nobody needs them for reference.
