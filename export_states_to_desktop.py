"""
Deprecated (2026-11-18, POST_CYCLE_FIXES P1-8).

This script used to write text copies of the He-3 / ADR procedures to ~/Desktop/custom_scripts. Those
copies lacked the safety checks in states.py (CSET limit, ramp-tracking guard, zero-current relay
switching), and the desktop script loader now refuses any script that drives the magnet or relay.
Use the built-in procedures in the GUI instead. Desktop scripts remain available for simple,
non-magnet tasks (heat switches, Cryo-con setpoints, waits).
"""
import sys

if __name__ == "__main__":
    print(__doc__)
    sys.exit(1)
