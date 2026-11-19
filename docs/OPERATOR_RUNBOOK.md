# 2PAC Operator Runbook (one page)

For whoever runs the cryostat day to day. Details and history: `POST_CYCLE_FIXES.md`, `KEPCO_SHUNT_AND_PID_NOTES.md`.

## Before a He-3 + ADR cycle
1. **Kepco ON** (front panel), output enabled, current limit above 9.5 A.
2. 3K stage (Ch C) below 3.2 K. Green He-3 valve **closed**.
3. Magnet current ~0 A (`Kepco I` tile). The cycle refuses to start above 0.2 A (RAMP) / 0.6 A (CONTROL).
4. Start **He-3 + ADR Cycle**. It zeroes the LS370, waits for < 10 mA, switches the relay to RAMP and ramps to
   `magnet_max_hout` (59.2 % ≈ 9.5 A) over 45–60 min.

## What the banners mean
| Banner | Meaning | What to do |
|---|---|---|
| MAGNET NOT FOLLOWING | Current far below the (lagged) expectation for > 60 s. Kepco off, or LS370 range clamped. | Output is ramped back to 0; Cryo-con stays on. Fix, then **He-3 + ADR: Resume at Magnet Ramp** (3K stage must be < 5 K). |
| MAGNET CURRENT TOO HIGH | Current well above the command: wrong range or shunt missing. | Output is **held**. Check LS370 range and the 100 Ω shunt, then **Ramp Down Magnet**. |
| Relay … V/I = … Ω | The latching relay may not be where the software thinks (RAMP ≈ 0.12 Ω, CONTROL ≈ 12 Ω). | Don't ramp. Check the relay; switch it from Utils with the current at zero. |
| Launch wait timed out | FAA hasn't settled below the launch temperature in `launch_timeout_h`. Magnet still at field. | **Confirm Step Done** to demag anyway, or Stop / Ramp Down Magnet. |
| Magnet current still … after demag | Current hasn't decayed below 10 mA; relay not switched. | Wait; check Kepco / LabJack reading. |
| Setpoint below post-demag base | Heater will sit at 0 %. | Raise the regulation setpoint a few mK. |
| Regulation: output … but current < 10 mA | Range / CSET limit wrong, or Kepco not responding. | Utils: range 10 mA, limit 7. Check Kepco. |
| LS370 front panel says … but its PID is driving the output | CMODE/HTRRNG registers say off while the loop runs. | Press **Regulate** (adopts and fixes). Don't use the front panel to turn it off: use Stop → Output to 0 %. |
| Telemetry stalled / NaN | No instrument update for > 60 s, or FAA/Kepco reading NaN > 5 min. | Check USB/serial cables; restart the GUI if it is hung (instruments hold their settings). |

Banners, procedure errors and watchdog alerts are also sent to phone/chat if `alerts` is set in
`~/2pac_logs/gui_settings.json` (`webhook_url` or `ntfy_url`).

## Resume at Magnet Ramp
Use when the charcoal is already heating but the magnet did not ramp (e.g. Kepco was off). Skips the heat-switch
reset and the 3.2 K gate, keeps the Cryo-con on, ramps from 0.

## Regulation
- Best settings (true CONTROL): **10 mA range, CSET limit 7, P 7, I 80 s, D 0** → ~25 µK rms at 60 mK.
- The LS370 front panel must show **closed loop, 10 mA** while regulating. If the relay tile turns red ("PID
  running, LS370 panel says OFF"), the registers were set to off while the PID kept running (the old Stop button
  did this). Press **Regulate**: it adopts the loop and fixes the registers (costs a ~2 mK dip for a few minutes).
- **Stop** during regulation asks: *Keep LS370 regulating* (the PID runs inside the LS370; the software just stops
  supervising) or *Output to 0 %* (open loop 0 %, the magnet current decays through the 12 Ω in seconds).
- Restarting the GUI does not stop regulation. After a restart, press **Regulate**: it adopts the running loop
  without pulsing the relay or zeroing the output.
- Hold time at 60 mK after a 9.3 A cycle: ~75–85 h; a large heat event can cost half the remaining capacity.

## Safe to touch mid-cycle?
| Safe | Not safe during a ramp / demag |
|---|---|
| Plots, time range, theme, snapshots | Utils → Update and Apply Settings / Read from Instrument |
| Regulation setpoint while regulating | Relay buttons (refused above 10 mA anyway) |
| Wiring R boxes (plot only) | Heat switch buttons (ADR switch at field!) |
| Closing the GUI (instruments hold) | Editing code / restarting while a ramp is advancing (it stops advancing) |

## The relay
The 12 Ω resistor is in parallel with the relay contact. RAMP = contact closed (12 Ω shorted, ~0.12 Ω circuit);
CONTROL = contact open (12 Ω + wiring). Only switch with ~0 A **and** the LS370 output at 0 %: switching to RAMP with
regulation output still applied would drive the magnet toward ~8 A. The buttons refuse otherwise.

## After a GUI restart
The relay position and heat switches are restored from `~/2pac_logs/last_hardware_state.json` (no pulses). The
latching relay has no position feedback: if in doubt, check Kepco V/I (RAMP ≈ 0.12 Ω, CONTROL ≈ 12 Ω).
