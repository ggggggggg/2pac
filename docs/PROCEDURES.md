# 2PAC ADR Operational Procedures & Safety Interlocks

## Standard Procedures

### 1. Ready for Cooldown (`ready_for_cooldown`)
- **Purpose**: Pre-cooling configuration while cryostat cools from 300 K to 4 K via pulse tube cooler.
- **Switch Configuration**:
  - Pot Heat Switch: **CLOSED**
  - ADR Heat Switch: **CLOSED**
  - Charcoal Heat Switch: **CLOSED**
- **Safety Checks**: Verifies green valve is closed before starting. Ensures magnet is de-energized ($|I| < 0.2\text{ A}$).

---

### 2. Auto-Cool: He-3 + ADR (`autocool_he3_adr`)
- **Purpose**: Fully autonomous 300 K to base run combining `ready_for_cooldown` and `he3_adr_cycle` into a single unattended sequence with pressure-gated safety interlocks.
- **Phases**:
  1. **Pre-cooling Setup**: Closes all heat switches (Pot, ADR, Charcoal) to couple stages to the 4 K cold head. Sets Cryo-con Loop 1 (45 K) and Loop 2 (55 K) with heaters disabled.
  2. **He-3 Pressure Drop to 0 bar (~24h from pulse tube startup)**:
     - As the sorption pump and pot cool, He-3 cryopumps into the system and pressure drops from room temperature positive pressure to 0 bar.
     - When $P_{He3} \le 0.10\text{ bar}$ (~24 h into cooldown), the script displays a prominent high-contrast banner in the GUI:
       `⚠️ ACTION REQUIRED: He-3 pressure has dropped to 0 bar (~24h into cooldown). CLOSE the GREEN He-3 valve on the cryostat now, then click 'Confirm Step Done'.`
     - **Mandatory Safety Pause**: The procedure strictly halts and will not proceed until the operator closes the green valve and acknowledges the message by clicking `Confirm Step Done`.
  3. **Cooldown Completion (~29h from pulse tube startup)**:
     - Once confirmed, continues adaptive slow polling (60s/30s/10s) until 3K stage (Ch C) drops below 3.2 K, without flooding the serial bus.
  4. **Autonomous Execution**:
     - Settles 30 s and seamlessly launches the full He-3 + ADR sequence (heats charcoal to 55 K, ramps magnet to 9.50 A, dwells 3.5 h, cools charcoal to launch temp, demagnetizes, and hands off to closed-loop temperature regulation).

---

### 3. He-3 Only Cycle (`he3_only_cycle`)
- **Purpose**: Condenses $^3\text{He}$ to achieve base $\sim 350\text{ mK}$ cooling without energizing the superconducting magnet.
- **Phases**:
  1. **Pre-flight**: Checks that the green He-3 valve is closed and magnet current is zero.
  2. **Heat Charcoal & Isolate Pot**:
     - Pot Heat Switch: **CLOSED**
     - ADR Heat Switch: **CLOSED**
     - Charcoal Heat Switch: **OPEN**
     - Charcoal Heater Setpoint: $55\text{ K}$ (Cryocon Loop 2)
     - 60K Flange Heater Setpoint: $65\text{ K}$ (Cryocon Loop 1)
     - Duration: Wait for charcoal desorption ($\sim 45\text{ min}$).
  3. **Condense $^3\text{He}$**:
     - Pot Heat Switch: **OPEN**
     - Charcoal Heat Switch: **CLOSED** (to pump on $^3\text{He}$)
     - Duration: $\sim 60\text{ min}$.
  4. **Base Temperature**: Base $\sim 350\text{ mK}$ holding steady. Returns to `wait_forever` (Idle).

---

### 4. Full He-3 + ADR Cycle (`he3_adr_cycle`)
- **Purpose**: Full cycle combining $^3\text{He}$ condensation and ADR magnetic cooling to reach $\sim 50\text{ mK}$.
- **Phases**:
  1. Pre-flight valve check and magnet de-energize guard.
  2. Heat charcoal to desorb $^3\text{He}$ while magnet is ramped to full field ($\sim 9.5\text{ A}$ via LS370 setpoint $58.1\%$).
  3. Wait for heat of magnetization to dump into the 4 K plate with ADR heat switch **CLOSED**.
  4. Cool pot to condense $^3\text{He}$.
  5. Thermally isolate ADR salt pill: ADR Heat Switch **OPEN**.
  6. Slowly ramp down magnet current to 0 A over 30 minutes (adiabatic demagnetization).
  7. Transition to sub-Kelvin base temperature holding steady in `wait_forever`.

---

### 5. Warm Up to 300 K (`warmup_300K`)
- **Purpose**: Controlled system warm-up from cryogenic temperatures back to room temperature.
- **Safety Interlock**: Rejects starting if magnet current is $> 0.2\text{ A}$ to prevent quenching or thermal runaway.
- **Configuration**:
  - Closes all three heat switches (Pot, ADR, Charcoal) to maximize thermal coupling to vacuum can and flanges.
  - Sets Cryocon heaters to $295\text{ K}$.

---

### 6. Ramp Down Magnet (`ramp_down_magnet`)
- **Purpose**: Standalone procedure to safely de-energize the superconducting magnet to zero current if a cycle was interrupted or paused.
- **Behavior**: Smoothly ramps current down over up to 30 minutes at a safe rate.

---

## Safety Interlocks & Limits

| Interlock | Limit / Condition | Trigger Action |
|---|---|---|
| **He-3 Overpressure** | $P_{He3} \ge 9.5\text{ bar}$ | Shuts off all Cryocon heaters immediately; aborts procedure. |
| **Magnet Safety Guard** | $|I_{mag}| > 0.2\text{ A}$ | Rejects starting Cooldown, He-3 cycle, or Warmup until magnet is ramped down. |
| **LabJack Thread Lock** | Concurrent USB access | Serialized via `threading.RLock()` to prevent relay/analog command collisions. |
| **Vacuum Gauge Calibration** | Kurt Lesker Pirani AIN3 | Continuous log-scale monitoring: $P = 10^{(V - 5)}\text{ Torr}$. |

---

## Hardware & Shunt Configuration References
* See [KEPCO_SHUNT_AND_PID_NOTES.md](file:///home/pcuser/qsp/src/2pac/docs/KEPCO_SHUNT_AND_PID_NOTES.md) for detailed hardware notes on the Kepco $100\ \Omega$ parallel shunt resistor, Lake Shore 370 current range scaling, and PID configuration differences between 2PAC and KPAC.
