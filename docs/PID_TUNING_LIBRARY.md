# 2PAC Lake Shore 370 PID Parameter Library

> **Auto-generated Reference Library**: Records tested PID settings, thermal stability metrics, and convergence rankings on the 2PAC ADR cryostat with the $100\ \Omega$ Kepco shunt installed.

## True CONTROL (12 Ω series), 10 mA range, CSET limit 7, 60 mK (2026-11-17/18): current reference

Use these. The older table below was measured 10/16–10/18 with the relay most likely stuck in RAMP and
does not apply to real CONTROL (see `POST_CYCLE_FIXES.md` §2b).

| P | I (s) | D | RMS of error (µK) | Notes |
|---|---|---|---|---|
| 3.5 | 60 | 0 | 43–47 per hour (30-min windows 40–52) | slow ~11 min wander; recovers from heat pulses in 6–14 min |
| 3.5 | 120 | 0 | ≈ 44 per hour | 5–20 min band halved, > 20 min drift rose |
| 5.0 | 120 | 0 | ≈ 37–41 per hour | hour without heat pulses |
| 7.0 | 120 | 0 | 25–30 quiet | no ringing; slow pulse recovery (−606 µK undershoot, 20 min) |
| **7.0** | **80** | **0** | **≈ 25 quiet; 24–27 every hour overnight** | **best**; pulse undershoot −155 µK, settles in 8 min |

- LS370 input filter: 10 s settle (default). 4 s made it worse (41 vs 29 µK: reading noise fed into the heater).
- Remaining noise: ~17–22 µK in 20–60 s and ~15 µK in 1–5 min, not correlated with other stages; ~7 µK reading noise.
- Untried: P 8–10 with I 60–80, D 10–20 s, filter 15–20 s.
- External FAA heat pulses (~1 mK over 30 s, daytime) and one large event (11/18 10:06, +40 mK, all stages)
  dominate any hour they fall in; judge settings on quiet RMS and on pulse recovery.

## Summary of Tested Configurations (Ranked by Stability), 10/16–10/18 (relay likely stuck in RAMP: historical)

| Rank | Status / Quality | P (Gain) | I (Reset s) | D (s) | Range | Temp RMS (µK) | Peak-to-Peak (µK) | Offset (mK) | Mean HTR (%) | Date / Time |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **#1** | 🌟 **Top Balanced** | `0.0850` | `220.0` | `0.0` | `1mA` | **44.7 µK** | 183.0 µK | 0.033 mK | 4.82% | 2026-10-16 19:12 |
| **#2** | 🌟 **Top Balanced** | `0.0850` | `220.0` | `0.0` | `1mA` | **49.7 µK** | 221.5 µK | 0.099 mK | 4.82% | 2026-10-16 19:27 |
| **#3** | 🔄 **Active Tuning** | `0.8500` | `280.0` | `0.0` | `100uA` | *(Running)* | *(Targeting <40 µK)* | ~0.03 mK | ~31.8% | 2026-10-17 21:50 |
| **#4** | ✅ **Good (<100 µK)** | `1.2000` | `250.0` | `0.0` | `100uA` | **75.6 µK** | 373.1 µK | 0.009 mK | 32.2% | 2026-10-17 21:44 |
| **#5** | ⚠️ *Overshoot Wave* | `0.0600` | `320.0` | `0.0` | `1mA` | **32.1 µK\*** | 536.0 µK | 0.318 mK | 4.39% | 2026-10-17 07:55 |
| **#5** | ℹ️ Sluggish (Offset) | `0.0387` | `594.1` | `0.0` | `1mA` | **29.4 µK** | 148.9 µK | 0.196 mK | 4.87% | 2026-10-16 18:44 |
| **#6** | ℹ️ Sluggish (Offset) | `0.0387` | `594.1` | `0.0` | `1mA` | **31.8 µK** | 157.1 µK | 0.195 mK | 4.88% | 2026-10-16 18:37 |
| **#7** | ✅ **Good (<100 µK)** | `0.0421` | `594.1` | `0.0` | `1mA` | **71.8 µK** | 286.4 µK | 0.065 mK | 4.89% | 2026-10-16 18:22 |
| **#8** | ℹ️ Suboptimal | `0.0468` | `516.6` | `0.0` | `1mA` | **136.1 µK** | 517.6 µK | 0.244 mK | 4.91% | 2026-10-16 18:07 |
| **#9** | ⚠️ *Hunting / Oscillating* | `0.0520` | `449.2` | `0.0` | `1mA` | **187.3 µK** | 628.9 µK | 0.847 mK | 4.88% | 2026-10-16 17:52 |
| **#10** | ℹ️ Steady But Offset | `0.0578` | `390.6` | `0.0` | `1mA` | **128.8 µK** | 461.4 µK | 2.058 mK | 4.75% | 2026-10-16 17:37 |
| **#11** | ⚠️ *Hunting / Oscillating* | `0.0680` | `312.5` | `0.0` | `1mA` | **857.0 µK** | 2914.4 µK | 0.839 mK | 4.27% | 2026-10-16 17:22 |
| **#12** | ⚠️ *Hunting / Oscillating* | `0.0800` | `250.0` | `0.0` | `1mA` | **1568.1 µK** | 5052.5 µK | 7.049 mK | 4.40% | 2026-10-16 17:07 |

\* *Note on P=0.060, I=320.0s: Initial 15-minute window scored 32.1 µK during a smooth crossing, but the weakened loop lacked braking force against thermal momentum, causing subsequent overshoot up to 80.318 mK.*

---

## Tuning Guidance (historical, stuck-relay period; the I ≥ 200 s rule does not apply to true CONTROL)
1. **Integral Reset Time ($I$)**: In the Lake Shore 370, $I$ is specified in **seconds**. A *smaller* value makes the integrator *faster and more aggressive*. However, setting $I > 300\text{ s}$ slows reset too much, failing to unwind accumulated error and resulting in large overshoots. Keep $I \in [180, 240]\text{ s}$.
2. **Proportional Gain ($P$)**: On the `1mA` range, keep $P \in [0.08, 0.10]$. On the `100uA` range ($10\times$ smaller DAC span), scale $P$ up by $10\times$ to $P \approx 0.85$ to maintain equivalent loop stiffness.
3. **Excitation Range (`100uA` vs `1mA` vs `10mA`)**:
   - `10mA`: Base operating point is $\approx 0.45\%$ output.
   - `1mA`: Base operating point is $\approx 4.5\%$ output (recommended balance of resolution and headroom).
   - `100uA`: Base operating point is $\approx 11\text{--}45\%$ output ($10\times$ finer DAC steps than 1mA).
4. **⚠️ Critical Warning on Reset Time ($I = 30\text{ s}$ vs ADR Thermal Lag)**:
   - Regardless of range, the physical thermal lag of the ADR salt pill is $\tau \sim 350\text{--}500\text{ s}$.
   - Setting $I = 30\text{ s}$ makes integration $>10\times$ faster than the stage, driving violent $20\text{+ mK}$ limit-cycle oscillations between zero-power saturation ($0\%$) and high current ($80\%$). Always maintain $I \ge 200\text{ s}$.

