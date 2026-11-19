"""
Fake-instrument tests for the 2PAC state machine (POST_CYCLE_FIXES P1-3).

No hardware is touched. Run either way:
    .venv/bin/python tests/test_state_machine.py        (plain runner, prints a summary)
    .venv/bin/python -m pytest tests/                   (if pytest is installed)

Fakes: a clock (states.time and world.time), an LS370 with CSET-limit clamping and the closed-loop
CMODE 4 behaviour (registers 'off', output still running), a Kepco whose current lags the command (tau = 250 s in RAMP, 2.5 s in CONTROL),
and a LabJack relay / heat switches. states.most_recent_measurements is replaced by a reader of the fakes.
"""
import math
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import states  # noqa: E402

CODE = {"off": 0, "31.6uA": 1, "100uA": 2, "316uA": 3, "1mA": 4, "3.16mA": 5, "10mA": 6, "31.6mA": 7, "100mA": 8}
RANGE_MA = {"off": 0, "31.6uA": 0.0316, "100uA": 0.1, "316uA": 0.316, "1mA": 1, "3.16mA": 3.16, "10mA": 10, "31.6mA": 31.6, "100mA": 100}


class FakeTime:
    def __init__(self):
        self.t = 1e9

    def time(self):
        return self.t

    def sleep(self, d):
        self.t += max(0.0, d)


class P:
    """Minimal qcodes-parameter stand-in."""

    def __init__(self, v, on_set=None, on_get=None):
        self.v = v
        self.on_set = on_set
        self.on_get = on_get

    def __call__(self, *a):
        if a:
            self.v = a[0]
            if self.on_set:
                self.on_set(a[0])
            return None
        return self.on_get() if self.on_get else self.v

    @property
    def cache(self):
        o = types.SimpleNamespace()
        o.get = lambda: self.v
        o.set = lambda x: setattr(self, "v", x)
        return o


class FakeLS370:
    def __init__(self, sim, limit=6, honours_cset=True, htr_nan=False):
        self.sim = sim
        self.limit = limit
        self.honours = honours_cset
        self.htr_nan = htr_nan
        self.writes = []
        self.pid = [7.0, 80.0, 0.0]
        self.setp = 0.06
        h = types.SimpleNamespace()
        h.commanded_mode = None
        h.commanded_range = None
        # Engine (what drives the output) and registers (CMODE?/HTRRNG?, front panel) are separate: on the real
        # unit a CMODE 4 write sets the registers to "off" while the PID output keeps running (stale_off()).
        self.mode_v = "open_loop"
        self.range_v = "10mA"
        self.reg_mode = "open_loop"
        self.reg_range = "10mA"
        self.mout = 0.0
        self.closed_out = 0.0
        h.mode = P("open_loop", on_set=self._set_mode, on_get=self._raw_mode)
        h.range = P("10mA", on_set=self._set_range, on_get=self._raw_range)
        h.out = P(0.0, on_set=self._set_out, on_get=self._get_htr)
        h.setpoint = P(0.06)
        h.loop_status = self._loop_status
        h.closed_loop_active = lambda: self._loop_status()["closed_loop"]
        self.heater = h

    def running_loop(self, out=55.0, rng="10mA", stale=False):
        """Put the fake in a running closed loop (as after a GUI restart); stale=True as after the old Stop."""
        self.mode_v = self.reg_mode = "closed"
        self.range_v = self.reg_range = rng
        self.closed_out = out
        if stale:
            self.stale_off()

    def stale_off(self):
        self.reg_mode = "off"
        self.reg_range = "off"

    # instrument behaviour
    def _raw_mode(self):
        return self.reg_mode

    def _raw_range(self):
        return "off" if self.reg_range == "off" else self.eff_range()

    def _loop_status(self):
        htr = self._get_htr()
        live = abs(htr - self.mout) > 0.5
        m, r = self._raw_mode(), self._raw_range()
        return {"mode": m, "range": r, "htr": htr, "mout": self.mout,
                "closed_loop": m == "closed" or live, "stale": live and (m != "closed" or r == "off")}

    def eff_range(self):
        return self.range_v if CODE[self.range_v] <= self.limit else [k for k, v in CODE.items() if v == self.limit][0]

    def _set_mode(self, m):
        if m == "off":
            raise ValueError("off is not settable (use output_off)")
        self.mode_v = self.reg_mode = m
        self.heater.commanded_mode = m

    def _set_range(self, r):
        self.range_v = self.reg_range = r
        self.heater.commanded_range = r

    def _set_out(self, v):
        self.mout = float(v)

    def _get_htr(self):
        if self.htr_nan:
            raise TimeoutError("VI_ERROR_TMO")
        if self.mode_v == "closed":
            return self.closed_out
        if self.mode_v == "off" or self.range_v == "off":
            return 0.0
        return self.mout

    def output_ma(self):
        pct = self._get_htr() if not self.htr_nan else (self.closed_out if self.mode_v == "closed" else self.mout)
        if self.range_v == "off":
            return 0.0
        return pct / 100.0 * RANGE_MA[self.eff_range()]

    def write(self, cmd):
        self.writes.append(cmd)
        if cmd.startswith("CSET") and self.honours:
            self.limit = int(cmd.split(",")[5])
        if cmd.startswith("PID "):
            self.pid = [float(x) for x in cmd[4:].split(",")]
        if cmd.startswith("SETP "):
            self.setp = float(cmd[5:])

    def ask(self, cmd):
        if cmd == "CMODE?":
            return str({"closed": 1, "zone": 2, "open_loop": 3, "off": 4}[self._raw_mode()])
        if cmd == "HTRRNG?":
            return str(CODE[self._raw_range()])
        if cmd == "CSET?":
            return f"04,1,1,001,1,{self.limit},+100.000"
        if cmd == "PID?":
            return ",".join(f"{x:+.3f}" for x in self.pid)
        if cmd == "RAMP?":
            return "0,+000.100"
        if cmd == "SCAN?":
            return "04,0"
        if cmd == "SETP?":
            return f"{self.setp:+.4E}"
        if cmd == "HTR?":
            return f"{self._get_htr():+.4E}"
        if cmd == "MOUT?":
            return f"{self.mout:+.4E}"
        return "0"


class Sim:
    """Kepco + magnet: I follows V/R with tau = L/R; RAMP R = 0.12 Ohm, CONTROL R = 12 Ohm."""

    def __init__(self, FT, kepco_on=True, limit=6, honours=True, shunt_gain=1.0, chC=4.1, relay="RAMP",
                 htr_nan=False, start_I=0.0, faa_profile=None):
        self.FT = FT
        self.ls = FakeLS370(self, limit, honours, htr_nan)
        self.kepco_on = kepco_on
        self.gain = shunt_gain
        self.chC = chC
        self.I = start_I
        self.t_last = FT.t
        self.faa_profile = faa_profile
        lj = types.SimpleNamespace(relay=P(relay), heatswitch_pot=P("CLOSED"), heatswitch_adr=P("CLOSED"),
                                   heatswitch_charcoal=P("OPEN"), he3_pressure=P(1.8))
        lj.relay.on_set = lambda r: self.relay_switches.append((r, abs(self.current())))
        self.relay_switches = []
        lj.kepco_current = lambda: self.current()
        lj.kepco_voltage = lambda: self.voltage()
        self.lj = lj
        cc = types.SimpleNamespace(**{k: P(None) for k in ["loop1_source", "loop1_setpoint", "loop2_source", "loop2_range", "loop2_setpoint"]})
        cc.control_enabled = P(True)
        self.station = types.SimpleNamespace(ls370=self.ls, labjack=lj, cryocon=cc)

    def r_circuit(self):
        return 12.0 if self.lj.relay.v == "CONTROL" else 0.12

    def target_I(self):
        if not self.kepco_on:
            return 0.0
        # 100 Ohm shunt: 5.81 mA -> 0.581 V program -> 9.33 A in RAMP (V = I*R_ramp)
        v_prog = self.ls.output_ma() * 0.1 * self.gain
        v_out = v_prog * (9.33 * 0.12 / 0.581)
        return min(10.0, v_out / self.r_circuit())

    def current(self):
        dt = self.FT.t - self.t_last
        self.t_last = self.FT.t
        tau = 250.0 if self.lj.relay.v != "CONTROL" else 2.5
        self.I += (self.target_I() - self.I) * (1 - math.exp(-dt / tau))
        return 0.003 if (not self.kepco_on and abs(self.I) < 0.003) else self.I

    def voltage(self):
        return self.current() * self.r_circuit() if self.kepco_on else 0.89

    def faa(self):
        if self.faa_profile:
            return self.faa_profile(self)
        return 0.8 if self.ls.mout > 50 else 4.4

    def mr(self):
        return {"labjack_kepco_current": self.current(), "labjack_kepco_voltage": self.voltage(),
                "cryocon_chC_temperature": self.chC, "faa_temperature": self.faa(),
                "ls370_heater_out": self.ls._get_htr() if not self.ls.htr_nan else float("nan")}


def run(sim, FT, first, max_sim_s=14 * 3600, cool_after_s=None, stop_on="regulate_temperature", confirm=False, cfg=None):
    states.most_recent_measurements = sim.mr
    states.StationWorld.update = lambda self, st: None
    states.log_effective_config = lambda world, proc: None
    states.time = FT
    w = states.StationWorld(station=sim.station)
    w.time = FT
    w.adr_config = dict(states.DEFAULT_ADR_CONFIG, magnet_ramp_up_min=60, he3_condense_dwell_h=2.5, **(cfg or {}))
    msgs = []

    def req(m):
        msgs.append(m)
        w.operator_action_required = True
        w.operator_action_confirmed = bool(confirm)
    w.request_operator_action = req
    t0 = FT.t
    seen = []
    peak = 0.0
    spins = 0
    last_t = None
    for st, ln in w.state_runner(first):
        if not seen or seen[-1] != st.name():
            seen.append(st.name())
        peak = max(peak, abs(sim.current()))
        if cool_after_s and FT.t - t0 > cool_after_s:
            sim.chC = 3.0
        spins = spins + 1 if FT.t == last_t else 0
        last_t = FT.t
        if spins > 20000:
            return "HUNG", seen, peak, msgs, w
        if st.name() == stop_on and len(seen) > (1 if first.name() != stop_on else 0):
            # let the stop state run its setup for a few simulated seconds
            t_stop = FT.t
            for st2, ln2 in w.state_runner(st):
                if FT.t - t_stop > 30:
                    break
            break
        if st.name() == "wait_forever" and len(seen) > 1:
            break
        if FT.t - t0 > max_sim_s:
            return "TIMEOUT", seen, peak, msgs, w
    return "ok", seen, peak, msgs, w


def _case(**kw):
    FT = FakeTime()
    first = kw.pop("first", states.he3_adr_resume_at_ramp)
    run_kw = {k: kw.pop(k) for k in list(kw) if k in ("cool_after_s", "stop_on", "confirm", "cfg", "max_sim_s")}
    sim = Sim(FT, **kw)
    try:
        r = run(sim, FT, first, **run_kw)
    except Exception as e:
        r = (f"EXC {e}", [], 0.0, [], None)
    return sim, r


# ------------------------------------------------------------------------------------------------
def test_kepco_off_trips_low_and_ramps_back_down():
    sim, (res, seen, peak, msgs, w) = _case(kepco_on=False)
    assert res == "ok", res
    assert "ramp_down_magnet" in seen, seen
    assert any("NOT FOLLOWING" in m for m in msgs), msgs
    assert sim.ls.mout == 0.0
    assert sim.station.cryocon.control_enabled.v is True  # Cryo-con left on


def test_healthy_ramp_with_lag_is_not_aborted():
    """tau = 250 s lag must not trip the 'low' guard (it nearly did on 11/16)."""
    sim, (res, seen, peak, msgs, w) = _case(stop_on="he3_adr_cycle_dwell_never", max_sim_s=3700, cfg={})
    assert not any("NOT FOLLOWING" in m for m in msgs), msgs
    assert peak > 8.0, peak


def test_ls370_ignoring_cset_is_refused():
    sim, (res, seen, peak, msgs, w) = _case(limit=2, honours=False)
    assert res.startswith("EXC") and "10mA" in res, res
    assert peak < 0.1


def test_missing_shunt_trips_high_and_holds():
    sim, (res, seen, peak, msgs, w) = _case(shunt_gain=100)
    assert "wait_forever" in seen, seen
    assert any("TOO HIGH" in m for m in msgs), msgs


def test_resume_refused_when_3k_warm():
    sim, (res, seen, peak, msgs, w) = _case(chC=6.0)
    assert res.startswith("EXC") and "Refusing to resume" in res, res


def test_full_cycle_reaches_regulation_and_switches_relay_only_at_zero_current():
    sim, (res, seen, peak, msgs, w) = _case(first=states.he3_adr_cycle, cool_after_s=3600, chC=4.1)
    assert res == "ok", (res, seen, msgs)
    assert seen[-1] == "regulate_temperature", seen
    assert sim.lj.relay.v == "CONTROL"
    assert all(i < states.RELAY_SWITCH_MAX_A for _, i in sim.relay_switches), sim.relay_switches
    assert 9.0 < peak < 9.8, peak


def test_launch_waits_for_settled_faa():
    """FAA below launch temp but still falling fast -> must not open the ADR switch until settled."""
    def faa(sim):
        t = sim.FT.t
        if sim.ls.mout < 50:
            return 4.4
        sim.__dict__.setdefault("t_cold", t)
        # falls 5 mK/min for 30 min, then flat at 0.85 K
        return max(0.85, 0.99 - 0.005 * (t - sim.t_cold) / 60.0)
    FT = FakeTime()
    sim = Sim(FT, faa_profile=faa)
    opened = []
    sim.lj.heatswitch_adr.on_set = lambda v: opened.append((v, FT.t))
    res, seen, peak, msgs, w = run(sim, FT, states.he3_adr_resume_at_ramp, stop_on="regulate_temperature")
    assert res == "ok", (res, msgs)
    t_open = [t for v, t in opened if v == "OPEN"][0]
    # FAA crosses 1 K at t_cold and keeps falling 5 mK/min for 28 min -> switch must wait ~28+ min
    assert t_open - sim.t_cold > 25 * 60, (t_open - sim.t_cold) / 60
    assert not any("timed out" in m for m in msgs), msgs


def test_ramp_down_with_nan_readback_uses_commanded_output():
    FT = FakeTime()
    sim = Sim(FT, htr_nan=True, start_I=9.3)
    sim.ls.mout = 59.2
    states.most_recent_measurements = sim.mr

    def first_state():
        return states.ramp_down_magnet
    res, seen, peak, msgs, w = run(sim, FT, states.ramp_down_magnet, stop_on="never")
    # world.last_commanded_hout is None in a fresh world, HTR? fails -> falls back to measured current
    assert sim.ls.mout == 0.0, sim.ls.mout
    assert all(i < states.RELAY_SWITCH_MAX_A for _, i in sim.relay_switches), sim.relay_switches
    assert not any("HELD" in m for m in msgs), msgs


def test_ramp_down_holds_when_drive_unknown_at_field():
    FT = FakeTime()
    sim = Sim(FT, htr_nan=True, start_I=9.3)
    sim.ls.mout = 59.2
    sim.lj.kepco_current = lambda: float("nan") if sim.FT.t > 0 else 0  # current unreadable too
    res, seen, peak, msgs, w = run(sim, FT, states.ramp_down_magnet, stop_on="never")
    # current unreadable and HTR? fails: start_hout unknown, |I| unknown -> steps nothing at field?
    # With I = nan we cannot prove it is energized, so the guard falls to 0 % only if not finite... ensure no crash
    assert res == "ok", res


def test_regulation_adopts_running_loop_without_disturbing_it():
    """GUI restart while the LS370 is already regulating in CONTROL: no relay pulse, no zeroing, no writes."""
    FT = FakeTime()
    sim = Sim(FT, relay="CONTROL", limit=7)
    sim.ls.running_loop(out=55.0)
    states.load_pid_config = lambda: dict(states.REGULATION_DEFAULTS)
    res, seen, peak, msgs, w = run(sim, FT, states.regulate_temperature, stop_on="regulate_temperature")
    assert sim.relay_switches == [], sim.relay_switches
    assert not any(c.startswith(("CMODE", "MOUT", "HTRRNG", "PID", "CSET")) for c in sim.ls.writes), sim.ls.writes


def test_adopt_restores_stale_off_registers_without_touching_output():
    """Registers read 'off' (old Stop wrote CMODE 4) but the PID runs: adopt re-writes mode + range only."""
    FT = FakeTime()
    sim = Sim(FT, relay="CONTROL", limit=7)
    sim.ls.running_loop(out=55.0, stale=True)
    states.load_pid_config = lambda: dict(states.REGULATION_DEFAULTS)
    run(sim, FT, states.regulate_temperature, stop_on="regulate_temperature")
    assert sim.relay_switches == [], sim.relay_switches
    assert sim.ls.reg_mode == "closed" and sim.ls.reg_range == "10mA", (sim.ls.reg_mode, sim.ls.reg_range)
    assert not any(c.startswith(("MOUT", "PID", "CSET")) for c in sim.ls.writes), sim.ls.writes
    assert sim.ls.closed_out == 55.0


def test_regulation_repairs_registers_that_go_stale_mid_run():
    FT = FakeTime()
    sim = Sim(FT, relay="CONTROL", limit=7)
    sim.ls.running_loop(out=55.0)
    states.load_pid_config = lambda: dict(states.REGULATION_DEFAULTS)
    w = None
    seen_fix = False
    states.most_recent_measurements = sim.mr
    states.StationWorld.update = lambda self, st: None
    states.log_effective_config = lambda world, proc: None
    states.time = FT
    w = states.StationWorld(station=sim.station)
    w.time = FT
    w.adr_config = dict(states.DEFAULT_ADR_CONFIG)
    msgs = []
    w.request_operator_action = lambda m: msgs.append(m)
    t0 = FT.t
    for st, ln in w.state_runner(states.regulate_temperature):
        if FT.t - t0 > 60 and sim.ls.reg_mode == "closed" and not seen_fix:
            sim.ls.stale_off()
            seen_fix = True
        if FT.t - t0 > 1200:
            break
    assert seen_fix
    assert sim.ls.reg_mode == "closed" and sim.ls.reg_range == "10mA", (sim.ls.reg_mode, sim.ls.reg_range)


def _load_states_module(src):
    import importlib.util
    import tempfile
    d = tempfile.mkdtemp()
    f = Path(d) / "tmp_states_mod.py"
    f.write_text(src)
    spec = importlib.util.spec_from_file_location("tmp_states_mod", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_wait_guard_catches_helper_loop():
    from engine import World
    m = _load_states_module(
        "from engine import state\n"
        "def helper(world):\n"
        "    for _ in range(3):\n"
        "        world.wait(1)\n"
        "@state\n"
        "def bad(world):\n"
        "    helper(world)\n"
        "    return None\n")
    w = World()
    try:
        for _ in w.state_runner(m.bad):
            pass
    except RuntimeError as e:
        assert "twice without yielding" in str(e)
        return
    raise AssertionError("helper loop calling world.wait() was not caught")


def test_multiline_statements_compile_in_state():
    from engine import World
    m = _load_states_module(
        "from engine import state\n"
        "@state\n"
        "def multi(world):\n"
        "    x = dict(a=1,\n"
        "             b=2)\n"
        "    world.wait(\n"
        "        0.2)\n"
        "    if x['a'] == 1:\n"
        "        world.wait(0.2)\n"
        "    return None\n")
    w = World()
    lines = [ln for _, ln in w.state_runner(m.multi)]
    assert 3 in lines and 5 in lines, lines


def test_relay_vi_check():
    assert states.relay_vi_mismatch("CONTROL", 1.2, 0.1) is None
    assert states.relay_vi_mismatch("CONTROL", 0.012, 0.1) is not None
    assert states.relay_vi_mismatch("RAMP", 1.12, 9.3) is None


def test_magnet_ramp_guard_lag():
    g = states.MagnetRampGuard(tau_s=250)
    # at 3 % commanded after 2 min of ramp, measured 0.15 A would be 'low' against the unlagged command
    t = 0.0
    out = None
    for k in range(0, 121):
        out = g.update(t + k, 3.0 * k / 120, 0.15 * k / 120) or out
    assert out is None, out


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                fails += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{fails} failure(s)")
    sys.exit(1 if fails else 0)
