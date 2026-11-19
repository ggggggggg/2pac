# 2PAC Maintenance Log & Activity History

## Fixes Implemented

- **2024-09-17 (~14:30)**: Replaced Helium adsorber. Compressor hours were 57608.9 (not confirmed if counter has ever been reset to zero).
- **Compressor Lines**: The helium lines to the compressor had to be reconnected for adsorber maintenance.
- **Charcoal Heat Switch**: Galen added Kapton tape to one side of the charcoal heat switch to cut thermal conductivity by ~2×, improving thermal isolation and cooling efficiency.

---

## Fall 2026 Activities

### Software Modernization & Automation

Major push to modernize software with a high-reliability PyQt5 / QCoDeS architecture, replacing legacy monolithic scripts with modular, robust cryogenic automation, high-performance viewport slicing plotting, dual-layer persistent logging, safety interlocks, and an automated state machine.

#### How to Launch the Application
- **Terminal**: Run `2pac-gui` from any shell (aliased to `/home/pcuser/qsp/src/2pac/launch_gui.sh`), or execute `./launch_gui.sh` directly from the repo root.
- **Desktop**: Double-click the `2PAC GUI` icon on the Linux desktop (`/home/pcuser/Desktop/2pac_gui.desktop`).
- *Reference*: Full launch and setup details are documented in [README.md](file:///home/pcuser/qsp/src/2pac/README.md).

#### Operating Modes
- **Simple Mode (Default)**: Clean, operator-focused interface designed for routine cryogenic operations. Allows single-click procedure selection, displays prominent safety confirmation modals, and shows high-visibility real-time operator action banners (e.g., prompting manual valve closures). Automatically returns to `Idle` on sequence completion.
- **Expert Mode**: Provides full state machine source inspection, live step-by-step execution highlighting, an integrated pseudocode compiler, and a desktop custom script runner.
- Toggle between modes at any time using the mode switch in the top toolbar.

#### Automated States & Procedures
The system provides 8 clean, fully automated operational states managed by the state machine ([states.py](file:///home/pcuser/qsp/src/2pac/states.py)):
1. **`Ready for Cooldown` (`ready_for_cooldown`)**: Pre-cool configuration from 300 K to 4 K. Closes all heat switches to establish thermal contact with the cold head.
2. **`Auto-Cool: He-3 + ADR` (`autocool_he3_adr`)**: Complete autonomous 300 K to base run combining `ready_for_cooldown` and `he3_adr_cycle`. Closes heat switches, monitors He-3 line pressure, and when pressure drops to 0 bar ($\le 0.10\text{ bar}$, ~24 h after pulse tube start), raises an operator action banner to close the green He-3 valve and strictly halts until acknowledged. Once confirmed, safely completes the ~29-hour cooldown to 3.2 K using adaptive slow polling (60s/30s/10s), then autonomously launches He-3 condensation, 9.5 A magnet soak, demag, and enters base regulation.
3. **`He-3 Only Cycle` (`he3_only_cycle`)**: Fully autonomous He-3 sorption refrigerator condensation cycle without energizing the magnet or Kepco supply. Safely cycles sorption pumps to achieve ~300 mK base.
4. **`He-3 / ADR Cycle` (`he3_adr_cycle`)**: Autonomous full multi-stage cycle: condenses He-3, ramps magnet to 9.50 A full field, heat-switch soaks, performs controlled demagnetization, and automatically transitions into temperature regulation.
5. **`Regulate Temperature` (`regulate_temperature`)**: Active closed-loop sub-Kelvin PID temperature holding on the ADR stage.
6. **`Ramp Down Magnet` (`ramp_down_magnet`)**: Dedicated safe abort/de-energize sequence that safely ramps magnet current to 0 A at any time without disturbing cryostat heat switches or heaters.
7. **`Warm Up 300K` (`warmup_300K`)**: Controlled system warm-up back to room temperature.
8. **`Idle` (`idle`)**: Safe quiescent resting state with zero heater output.

*Deprecated States Removed*: Obsolete and redundant states have been cleaned up and removed (`wait_forever2`, `switch_to_wait_forever_test`, `resume_he3_adr_cycle`, `open_charcoal_heatswitch`, `open_pot_heatswitch`, `open_adr_heatswitch`, `set_relay_to_ramp`).

*Safety Interlocks*: Before moving pneumatic switches or energizing heaters, the state machine verifies that the green manual backing valve is closed and confirms magnet current $|I| < 0.2\text{ A}$.

*Reference*: Step-by-step procedure phases and safety interlocks are detailed in [docs/PROCEDURES.md](file:///home/pcuser/qsp/src/2pac/docs/PROCEDURES.md).

#### Hardware Shunt & Current Range Rules
A physical $100\ \Omega$ parallel shunt resistor is permanently installed across the Kepco BOP 10-10M programming input terminals:
- **`RAMP` Mode (Magnet Field Control)**:
  - **MUST ALWAYS USE `10mA` range** (`HTRRNG 6`, limit 6).
  - Transfer function: $58.1\%$ output commands $5.81\text{ mA} \times 100\ \Omega = 0.581\text{ V} \implies \mathbf{9.50\text{ A}}$ full field magnet soak.
- **`CONTROL` Mode (Temperature Regulation)**:
  - **`100uA` range** (`HTRRNG 2`, limit 2): Recommended for highest DAC resolution. Standard tuning: $P = 0.850, I = 280\text{ s}$ (Lake Shore 370 Channel 4).
  - **`1mA` range** (`HTRRNG 4`, limit 4): Standard tuning: $P = 0.085, I = 220\text{ s}$ ($\sim 45\ \mu\text{K}$ RMS benchmark).
- *Reference*: Circuit math and transfer function derivations are documented in [docs/KEPCO_SHUNT_AND_PID_NOTES.md](file:///home/pcuser/qsp/src/2pac/docs/KEPCO_SHUNT_AND_PID_NOTES.md).
- *Reference*: Validated PID parameter sets and tuning procedures are documented in [docs/PID_TUNING_LIBRARY.md](file:///home/pcuser/qsp/src/2pac/docs/PID_TUNING_LIBRARY.md).

#### Data Logging & High-Performance Plotting
- **Dual Persistence**: Every ~1.8 s, telemetry is synchronously committed to both a high-speed SQLite database (`~/2pac_logs/YYYY-MM-DD/2pac.db`) and human-readable CSV flat logs (`~/2pac_logs/YYYY-MM-DD/<channel>.log`).
- **Zero-Lag Interactive Viewports**: Binary search viewport slicing (`np.searchsorted`) eliminates redraw latency (< 35 ms) across multi-million-point datasets. Features adaptive smart time ticks, box zoom, click-drag pan, and hover crosshair readouts.

---

### Documentation Suite Quick Links

| Topic | Document Path | Key Contents |
|---|---|---|
| **Master System Guide** | [README.md](file:///home/pcuser/qsp/src/2pac/README.md) | Installation, desktop launcher, GUI modes, plotting controls, troubleshooting |
| **Operating Procedures** | [docs/PROCEDURES.md](file:///home/pcuser/qsp/src/2pac/docs/PROCEDURES.md) | Standard run workflows, phase transitions, manual valve checklist, safety limits |
| **Software Architecture** | [docs/ARCHITECTURE.md](file:///home/pcuser/qsp/src/2pac/docs/ARCHITECTURE.md) | Multi-threading model, state machine design, instrument drivers, plotting engine |
| **Hardware Shunt & Scaling** | [docs/KEPCO_SHUNT_AND_PID_NOTES.md](file:///home/pcuser/qsp/src/2pac/docs/KEPCO_SHUNT_AND_PID_NOTES.md) | Kepco $100\ \Omega$ shunt circuit math, transfer functions, current range rules |
| **PID Parameter Library** | [docs/PID_TUNING_LIBRARY.md](file:///home/pcuser/qsp/src/2pac/docs/PID_TUNING_LIBRARY.md) | Tested PID presets (`100uA`, `1mA`, `10kΩ`), stability scores, tuning guidelines |
| **Maintenance & History** | [docs/MAINTENANCE_AND_HISTORY.md](file:///home/pcuser/qsp/src/2pac/docs/MAINTENANCE_AND_HISTORY.md) | Cryostat maintenance log, component fixes, software modernization history |

