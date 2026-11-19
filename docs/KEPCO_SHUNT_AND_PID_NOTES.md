# Kepco Magnet Programming Shunt Resistor & PID Configuration Notes

> **Purpose**: Reference guide for hardware shunt resistor configurations, Lake Shore 370 output ranges, and software PID settings between **2PAC** and **KPAC**. Consult this document whenever installing or modifying the physical $100\ \Omega$ parallel shunt resistor on the Kepco programming input.

---

## 1. System Architecture & The Hardware Difference

The Lake Shore 370 heater output is a **programmable DC current source** ($I$), whereas the Kepco power supply programming input expects an **analog voltage reference** ($V$).

```
[ Lake Shore 370 Output ]  --->  (I_out)  ---> [ Optional Parallel Shunt ] ---> [ Kepco BOP Program Input ]
    (Current Source)                                   (R_shunt)                      (Voltage Reference)
                                                           │
                                                          GND
                                            V_program = I_out × R_shunt
```

### KPAC Configuration (With $100\ \Omega$ Parallel Shunt)
* **Physical Circuit**: A **$100\ \Omega$ precision resistor** is connected in parallel across the Lake Shore output / Kepco programming input terminals.
* **Current-to-Voltage Conversion**: $V_\text{Kepco} = I_\text{LS370} \times 100\ \Omega$.
* **Ramp Settings**:
  * Output Range: **`10mA`** (`HTRRNG 6`)
  * Target Output: $\approx \mathbf{80\%}$ to reach full field ($14\text{ A}$)
  * Math: $0.80 \times 10\text{ mA} = 8.0\text{ mA} \implies 8.0\text{ mA} \times 100\ \Omega = \mathbf{0.80\text{ V}}$ programming input.
* **Regulation**: Operates with $R_\text{shunt} = 100\ \Omega$ defining the loop transfer function.

---

### 2PAC Status (Updated 2026-10-16 — 100 Ω Physical Shunt Installed)
* **Physical Circuit**: The **$100\ \Omega$ parallel shunt resistor** is now installed across the Kepco BOP 10-10M programming input terminals.
* **Lake Shore Resistance**: Lake Shore 370 knows the heater resistance is **$100\ \Omega$** (`CSET` resistance parameter = $100.0\ \Omega$).
* **Kepco Model**: **Kepco BOP 10-10M** ($\pm 10\text{ V}, \pm 10\text{ A}$).
* **Operating Current Ranges**:
  * **`RAMP` mode**: **`10mA`** range (`HTRRNG 6`). $58.1\%$ output ($5.81\text{ mA} \times 100\ \Omega = 0.581\text{ V}$) commands $9.5\text{ A}$ magnet ramp.
  * **`CONTROL` mode**: **`10mA`** range (`HTRRNG 6`, limit code 6) or **`3.16mA`** range (`HTRRNG 5`) for regulation at $50\text{--}70\text{ mK}$.
* **Background & Impedance Math**:
  * Standard Kepco programmable supplies use a **$10\text{ k}\Omega$ internal input resistance** on their voltage programming input ($1\text{ k}\Omega/\text{V}$, $0\text{--}10\text{ V}$ / $0\text{--}1\text{ mA}$ bridge).
  * With the **$100\ \Omega$ shunt in parallel** ($100\ \Omega \parallel 10\text{ k}\Omega \approx 99\ \Omega$), the input impedance is lowered by $100\times$.
  * Therefore, the Lake Shore 370 output current ranges are shifted up by $100\times$ (`100uA` $\rightarrow$ `10mA`), generating identical programming voltages.
* **Why `Kepco V` Rises Linearly to $\sim 1.1\text{ V}$ During the Ramp (10/14 09:17 Log)**:
  * The `Kepco V` telemetry channel (`labjack_kepco_voltage`) monitors the **Kepco high-current output terminals** across the magnet leads, where:
    $$V_\text{Kepco, out} = I_\text{mag} \cdot R_\text{leads} + L_\text{mag} \frac{dI_\text{mag}}{dt}$$
  * During the 60-minute ramp to $9.57\text{ A}$ ($\frac{dI}{dt} \approx 2.64\text{ mA/s}$), the inductive component $L \frac{dI}{dt}$ is tiny ($\sim 0.05\text{ V}$), and `Kepco V` remains at $\approx 1.15\text{ V}$ even after the ramp finishes ($dI/dt = 0$ at 10:20–10:34).
  * Therefore, the linear rise from $0\text{ V} \rightarrow 1.15\text{ V}$ is due to the **ohmic resistance of the room-temperature cables, feedthroughs, and magnet leads**:
    $$R_\text{leads} = \frac{1.15\text{ V}}{9.57\text{ A}} \approx \mathbf{0.12\ \Omega}$$
* **Relay Routing (`RAMP` vs. `CONTROL`)** (corrected 2026-11-18, see `POST_CYCLE_FIXES.md` §2b):
  * The programming side is the same in both positions: LS370 heater output → [$100\ \Omega$ shunt ∥ Kepco input ~10 kΩ] → Kepco (voltage-programmed). The $100\ \Omega$ shunt has been installed on 2PAC since 2026-10-16.
  * **`RAMP`**: Kepco output → leads (~$0.12\ \Omega$) → magnet. Sensitivity ≈ 1,606 A per A of LS370 current; magnet current lags the command with $\tau = L/R \approx 250\text{ s}$.
  * **How the relay does it (confirmed 2026-11-18):** the $12\ \Omega$ resistor is wired **in parallel with the relay contact**. RAMP closes the contact and shorts the $12\ \Omega$; CONTROL opens it, so all current flows through $12\ \Omega$ + wiring.
  * **`CONTROL`**: contact open, **~$12\ \Omega$ in series** with the magnet on the Kepco output side. Same programming, ~100× less magnet current (≈ 15.6 A/A), $\tau \approx 2.5\text{ s}$. Regulation works by modulating the magnet field (demag/remag), not through a separate stage heater. The Kepco is *not* isolated.
  * A ~$10\ \Omega$ Dale resistor is permanently in parallel with the magnet.
  * Measured V/I: RAMP 0.12 Ω (9.3 A, 1.13 V); CONTROL 11.9–12.0 Ω (0.10–0.16 A). The software now checks V/I against these after switching.
  * ⚠️ **Never switch the relay with output applied.** The Kepco is voltage-programmed: CONTROL → RAMP with ~1 V regulation output shorts the 12 Ω and the magnet current climbs toward 1 V / 0.12 Ω ≈ 8 A (τ ≈ 250 s). RAMP → CONTROL at field opens the contact and forces the magnet current into 12 Ω / the Dale resistor (fast discharge, voltage spike). The software and the Utils relay buttons require |I| < 10 mA **and** LS370 output ≈ 0 %.
  * The 10/16–18 "stuck relay" period = contact stayed closed (12 Ω shorted) while software logged CONTROL.


---

## 2. Checklist When Installing the 100 Ω Physical Shunt on 2PAC

When you physically insert the $100\ \Omega$ resistor in parallel across the Kepco programming input, **you must update the current ranges and software settings before energizing**:

### ⚠️ Critical Pre-Energize Warning
> [!CAUTION]
> **DO NOT** energize the Lake Shore on high current ranges (e.g. $100\text{ mA}$) with the $100\ \Omega$ resistor installed!
> By Ohm's law:
> $$V = I \times R = 100\text{ mA} \times 100\ \Omega = 10.0\text{ V}$$
> $10\text{ V}$ is the maximum compliance voltage of the Lake Shore 370 and would severely overdrive the Kepco power supply to its maximum output rail limit.

### Configuration Changes Required

| Setting | Before (No Shunt / $1\ \Omega$) | After Installing $100\ \Omega$ Shunt | Reason |
| :--- | :--- | :--- | :--- |
| **Physical Shunt** | None (direct into $10\text{ k}\Omega$ Kepco) | **$100\ \Omega$ in parallel** | Drops input impedance by $100\times$ ($10\text{ k}\Omega \to 100\ \Omega$) |
| **Ramp Current Range (`RAMP`)** | `100uA` (`HTRRNG 2`) | **`10mA` range** (`HTRRNG 6`) | $58.1\%$ ($5.81\text{ mA} \times 100\ \Omega = 0.581\text{ V}$) commands $9.5\text{ A}$ |
| **Regulation Range (`CONTROL`, 50–70 mK)** | `100uA` or `31.6uA` | **`3.16mA` or `10mA`** *(or `1mA`)* | Scales up by $100\times$ from today's `100uA` / `31.6uA` regulation |
| **Full Field Output %** | $58.1\%$ (for $9.5\text{ A}$) | **$58.1\%$** (for $9.5\text{ A}$) | Identical percentage once range is shifted by $100\times$ |
| **Software Load Resistor (`CSET`)** | `1.0 Ω` | **`100.0 Ω`** | Updates LS370 internal power & loop scaling to $100\ \Omega$ |
| **Current Limit Setting** | Code `2` (`100uA`) / `3` (`316uA`) | **Code `6` (`10mA`)** | Matches $10\text{ mA}$ range |
| **PID Transfer from KPAC** | Did not work (impedance mismatch) | **Direct 1:1 transfer valid** | Loop transfer functions ($V/I$) are now identical |

### Choosing the Regulation Range for 50–70 mK (With $100\ \Omega$ Resistor)

> ⚠️ **Superseded (2026-11-18).** The numbers in this subsection were taken 10/16–10/18 while the latching relay was most likely stuck in RAMP (software logged CONTROL). True CONTROL is ~100× (not 10×) less sensitive than RAMP. For real CONTROL use the **10 mA range with CSET limit 7, P 7, I 80 s, D 0** (~25 µK rms at 60 mK, output 50–65 %), see `PID_TUNING_LIBRARY.md`. The table below is kept for history only.

In `CONTROL` mode, the relay scales the Kepco current sensitivity down by **$10\times$** compared to `RAMP` mode (today on `100uA` without the shunt, $100\% = 1.68\text{ A}$, so $70\text{ mK}$ held at $\text{Hout} \approx 4.6\%$ / $I_\text{mag} = 76\text{ mA}$, and $80\text{ mK}$ held at $\text{Hout} \approx 8.0\%$ / $I_\text{mag} = 135\text{ mA}$).

When you install the **$100\ \Omega$ parallel resistor**, every range shifts up by **$100\times$**:

| LS370 Range (With $100\ \Omega$) | Equivalent Today (No Shunt) | Max Magnet Current in `CONTROL` ($100\%$) | Output % @ **50 mK** ($\sim 25\text{ mA}$) | Output % @ **70 mK** ($\sim 76\text{ mA}$) | Best Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`10mA`** (`HTRRNG 6`) | `100uA` | **$1.68\text{ A}$** | $\sim 1.5\%$ | $\sim 4.6\%$ | **Exact 1:1 match to today's successful run**, with $1.68\text{ A}$ headroom to catch the stage from higher temps. |
| **`3.16mA`** (`HTRRNG 5`) | `31.6uA` | **$0.53\text{ A}$** ($530\text{ mA}$) | $\sim 4.7\%$ | $\sim 14.5\%$ | **Recommended sweet spot for 50–70 mK**: $3.16\times$ finer DAC resolution while still keeping $530\text{ mA}$ of headroom. |
| **`1mA`** (`HTRRNG 4`) | *(10 µA)* | **$0.17\text{ A}$** ($168\text{ mA}$) | $\sim 15\%$ | $\sim 45\%$ | Highest DAC resolution for holding steady at $50\text{--}70\text{ mK}$, but saturates at $168\text{ mA}$ if the pill gets warm. |


---

## 3. Step-by-Step Transition Procedure

1. **Safety Interlock**: Ensure the system is in `wait_forever` (Idle), Lake Shore heater output is `0.0%`, heater range is `OFF`, and magnet current is confirmed zero ($|I| < 0.05\text{ A}$).
2. **Install Hardware**: Place the $100\ \Omega$ precision resistor in parallel across the Kepco remote programming input terminals.
3. **Update Software Settings in GUI**:
   - Go to the **Utilities** tab $\rightarrow$ **Temperature Control PID (LS370)**.
   - Set **Heater Resistance (R)**: `100.0 Ω`.
   - Set **Current Limit**: Code `6: 10 mA` (or code `7: 31.6 mA` depending on maximum safe threshold).
   - Set **Excitation Range**: `10mA` (for magnet ramping) or calibrated regulation range.
   - Enter the tested **KPAC PID gains** ($P, I, D$).
   - Click **Update and Apply Settings**.
4. **Update Recipe Defaults in Code**:
   - Verify `pid_config` in `gui_settings.json`:
     ```json
     "heater_resistance": 100.0,
     "heater_range": "10mA"
     ```
   - Verify `CSET` write in [`states.py`](file:///home/pcuser/qsp/src/2pac/states.py#L718):
     ```python
     ls.write(f"CSET {ch_val}, 1, 1, 1, 1, {limit_val}, 100.0")
     ```
5. **Verify with Low Setpoint First**: Test with a small setpoint step ($1\text{ to }2\text{ mK}$ or low magnet current) to confirm stable closed-loop response before running a full cycle.

---

## 4. Measurements (2026-11-16/17, 100 Ω shunt, 10 mA range)

| Quantity | Value | Notes |
|---|---|---|
| Magnet current at 58.1 % (RAMP) | 9.25–9.42 A | 59.2 % ≈ 9.5 A (`magnet_max_hout` default) |
| Kepco output voltage at full field | 1.12–1.13 V | V/I ≈ 0.12 Ω (leads) |
| RAMP lag (first-order) | τ ≈ 250–300 s | Ramp guard uses a lagged expectation |
| CONTROL circuit | ≈ 12 Ω series, τ ≈ 2.5 s | ~0.1 A at 60 mK, 50–65 % on 10 mA |
| CONTROL sensitivity | ≈ 15.6 A per A of LS370 current | 0.081 A at 5.4 mA measured |
| Kepco V with the Kepco OFF | ≈ 0.89 V offset | don't use for V/I or wiring-R calibration |
| LS370 `CMODE?` / `HTRRNG?` after a `CMODE 4` write | read 4 / 0 ("off"), front panel off, but the PID output keeps running | not a readback quirk (11/19): re-writing HTRRNG 6 (bumpless) and CMODE 1 (integrator reset, ~2 mK dip) restores them. Never write CMODE 4. |
