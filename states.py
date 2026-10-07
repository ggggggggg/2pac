import time
import numpy as np
import qcodes
import typing
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from imperative_statemachine import state
from world import World

# Initialize globals to be populated by main.py
st = None
elapsed_time = None
datasaver_global = None
log_dir = None  # Set by main.py
ENABLE_TEXT_LOGGING = True

def _get_log_dir():
    """Get or create today's log directory."""
    global log_dir
    today = datetime.now().strftime("%Y-%m-%d")
    d = Path.home() / "2pac_logs" / today
    d.mkdir(parents=True, exist_ok=True)
    log_dir = d
    return d

def _log_to_file(results_list):
    """Append each channel value to its own .log file."""
    d = _get_log_dir()
    now = time.time()
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in results_list:
        if isinstance(item, tuple) and len(item) == 2:
            param, value = item
            # Get the channel name
            if isinstance(param, str):
                name = param
            else:
                name = getattr(param, 'name', str(param))
            # Write to file
            log_file = d / f"{name}.log"
            with open(log_file, "a") as f:
                f.write(f"{now},{local_time},{value}\n")

def retry(f, n=3):
    # try cryocon is being unreliable on returning temp, so try a few times then return nan
    for i in range(n):
        try:
            return f()
        except: 
            pass
    return np.nan

def update(datasaver, state):
    parameters = [elapsed_time, st.cryocon.chA_temperature, st.cryocon.chB_temperature,
                  st.cryocon.chC_temperature, st.cryocon.chD_temperature, st.labjack.kepco_current, st.labjack.kepco_voltage, st.ls370.heater.out,
                  st.labjack.relay, st.labjack.heatswitch_adr, st.labjack.heatswitch_charcoal, st.labjack.heatswitch_pot,
                  st.labjack.he3_pressure, st.labjack.vac_can_pressure_torr]
    faa_val = retry(st.ls370.ch04.temperature, n=2)
    l = [(param, retry(param, n=1)) for param in parameters] + [
        ("state", state.name()),
        ("faa_temperature", faa_val),
        ("time", time.time())
    ]
    try:
        datasaver.add_result(*l)
    except Exception as e:
        print(f"Warning: datasaver.add_result error: {e}")
    if ENABLE_TEXT_LOGGING:
        try:
            _log_to_file(l)
        except Exception as e:
            print(f"Warning: _log_to_file error: {e}")

def most_recent_measurements():
    if datasaver_global is None:
        return {}
    try:
        data = datasaver_global.dataset.cache.data()
        ret = {}
        for key in data.keys():
            if key in data and key in data[key] and len(data[key][key]) > 0:
                v = data[key][key][-1]
                ret[key] = v
        return ret
    except Exception as e:
        print(f"Error reading recent measurements: {e}")
        return {}

def pretty_str_dict(d: dict):
    s = ""
    for key, value in d.items():
        s+= f"{key} {value}\n"
    return s

# Magnet ramp parameters shared by he3_adr_cycle and ramp_down_magnet
MAGNET_MAX_HOUT = 58.1           # LS370 open-loop output (%) at full field (~9.5 A)
MAGNET_RAMP_TIME_S = 30*60       # full-scale ramp duration
MAGNET_START_LIMIT_A = 0.2       # refuse to start a cycle above this magnet current

def check_magnet_deenergized(world):
    """Raise if the magnet is (or may be) energized. NaN / read failure counts as unsafe."""
    try:
        mag_I = float(world.station.labjack.kepco_current())
    except Exception as e:
        raise RuntimeError(f"Refusing to start: cannot read magnet current ({e}).")
    if not np.isfinite(mag_I) or abs(mag_I) > MAGNET_START_LIMIT_A:
        raise RuntimeError(
            f"Refusing to start: magnet current is {mag_I:.3f} A (limit {MAGNET_START_LIMIT_A} A). "
            "Run 'Ramp Down Magnet' first.")
    return mag_I

MAX_HE3_PRESSURE_BAR = 9.5

@dataclass
class StationWorld(World):
    station: qcodes.station.Station = None
    datasaver: typing.Any = None

    def update(self, state):
        update(self.datasaver, state)
        # Continuous hardware safety interlock: if He-3 pressure exceeds limit,
        # immediately cut Cryocon heaters and abort the procedure safely.
        if self.station and hasattr(self.station, "labjack"):
            try:
                p_param = getattr(self.station.labjack, "he3_pressure", None)
                if p_param:
                    p = p_param.cache.get()
                    if p is None:
                        p = float(p_param())
                    if p > MAX_HE3_PRESSURE_BAR:
                        if hasattr(self.station, "cryocon"):
                            try:
                                self.station.cryocon.control_enabled(False)
                            except Exception:
                                pass
                        raise RuntimeError(
                            f"CRITICAL SAFETY INTERLOCK: He-3 pressure reached {p:.2f} bar (exceeds {MAX_HE3_PRESSURE_BAR} bar limit)! "
                            "Cryocon heaters shut off immediately."
                        )
            except RuntimeError:
                raise
            except Exception:
                pass

@state 
def he3_adr_cycle(world: StationWorld):
    testmode = False
    # 1. check that we're cold enough to start
    # 2. start heating charcoal
    # 3. ramp up adr
    # 4. wait for he3 to condense
    # 5. cool charcoal
    # 6. ramp down adr

    # 0. safety: never start (and ramp from 0) while the magnet is energized
    check_magnet_deenergized(world)
    # Operator must close the green He-3 valve BEFORE step 1 (also confirmed in GUI)
    print("CLOSE THE GREEN HE3 VALVE")

    # 1. set heat switches and check that we're cold enough to start
    world.set_phase("1/6: Pre-cooling Check (Pot < 3.2K)", 1, 6)
    world.station.labjack.heatswitch_pot("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_adr("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_charcoal("OPEN")
    world.wait(1)
    while True:
        mr = most_recent_measurements()
        if mr.get("cryocon_chD_temperature", 100) < 3.2 or mr.get("cryocon_chC_temperature", 100) < 3.2:
            break
        world.wait(1)

    # 2. start heating charcoal
    world.set_phase("2/6: Heating Sorption Charcoal (55K)", 2, 6)
    world.station.cryocon.loop1_source("A")
    world.wait(1)
    world.station.cryocon.loop1_setpoint(65) # Upper stage setpoint = 45 K, trying higher so i t actually goes up?
    world.wait(1)
    world.station.cryocon.loop2_source("B")
    world.wait(1)
    world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
    world.wait(1)
    world.station.cryocon.control_enabled(True) # heat charcoal
    world.wait(1)

    # 3. ramp up adr
    world.set_phase("3/6: Ramping ADR Magnet Up (1800s)", 3, 6)
    world.station.labjack.relay("RAMP")
    world.wait(1)
    ramp_controller = world.station.ls370.heater
    ramp_controller.mode('open_loop')
    world.wait(1)
    ramp_controller.range("100uA")
    world.wait(1)
    hout_start = 0
    if testmode:
        target_hout = 1 # small max current
        target_time_s = 30
    else:
        target_hout= MAGNET_MAX_HOUT  # 55 should get to 9.53 A, which is the hardware current limit of the kepco supply
        target_time_s = MAGNET_RAMP_TIME_S
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = target_hout/target_N_steps
    houts_up = np.arange(target_N_steps)*step_size
    for hout in houts_up:
        ramp_controller.out(hout)
        world.wait(target_step_duration_s)

    # 4. wait for he3 to condense
    world.set_phase("4/6: He-3 Condensation Dwell (3.5h)", 4, 6)
    if testmode:
        world.wait(10)
    else:
        world.wait(3600*3.5) # takes about 2 hours

    # 5. cool charcoal
    world.set_phase("5/6: Cooling Charcoal Sorption Pump", 5, 6)
    world.station.labjack.heatswitch_pot("OPEN")
    world.wait(1)
    world.station.cryocon.control_enabled(False) # turn off 40K heat after cooling pot
    if testmode:
        world.wait(1)
    else: 
        world.wait(120) # a bit of cooling before closing charcoal heatswitch
    world.station.labjack.heatswitch_charcoal("CLOSED")  
    world.wait(1)
    
    if testmode:
        world.wait(10)
    else:
        world.wait(3600*1)
        world.station.cryocon.loop1_setpoint(65) 
        world.wait(1)
        world.station.cryocon.loop2_source("B")
        world.wait(1)
        world.station.cryocon.loop2_setpoint(1) # Charcoal setpoint = 1 K, AKA OFF
        world.wait(1)
        world.station.cryocon.control_enabled(True) # heat 40K stage
        world.wait(3600*0.5) 
        world.station.cryocon.control_enabled(False) # turn off 40K heat after cooling pot
        world.wait(3600*2)

    # 6. ramp down adr
    world.set_phase("6/6: Demag Ramp Down & Closed-Loop Control", 6, 6)
    world.station.labjack.heatswitch_adr("OPEN")
    world.wait(1)
    houts_down = houts_up[::-1]
    for hout in houts_down:
        ramp_controller.out(hout)
        world.wait(target_step_duration_s)
    if testmode:
        world.wait(30)
    else:
        world.wait(20*60) # let magnet current get smaller
    world.station.labjack.relay("CONTROL")
    world.wait(30)
    ramp_controller.mode('closed')
    world.wait(1)
    ramp_controller.setpoint(0.05)
    world.wait(1)
    ramp_controller.range("100uA")

    # be done
    world.set_phase("Idle — Holding Steady", 1, 1)
    return wait_forever

@state
def ramp_down_magnet(world: StationWorld):
    # Safely ramps the LS370 open-loop output (magnet current) from its present
    # value to 0 at the standard he3_adr_cycle rate, then holds idle.
    # Heat switches, relay and Cryo-con are left untouched.
    world.set_phase("Safe Ramp Down: reading magnet drive", 1, 1)
    rc = world.station.ls370.heater
    mode_now = rc.mode()
    start_hout = float(rc.out())
    if mode_now != "open_loop":
        print(f"ramp_down_magnet: LS370 heater in '{mode_now}' mode, not open_loop; magnet not under ramp control, nothing to do.")
        world.set_phase("Idle — Holding Steady", 1, 1)
        return wait_forever
    if not np.isfinite(start_hout) or start_hout <= 0:
        world.set_phase("Idle — Holding Steady", 1, 1)
        return wait_forever
    rate_per_s = MAGNET_MAX_HOUT / MAGNET_RAMP_TIME_S
    n_steps = max(1, int(np.ceil(start_hout / rate_per_s)))
    world.set_phase(f"Safe Ramp Down: {start_hout:.1f}% -> 0% ({n_steps} s)", 1, 1)
    for hout in np.linspace(start_hout, 0.0, n_steps + 1)[1:]:
        rc.out(float(hout))
        world.wait(1)
    world.set_phase("Idle — Holding Steady (magnet ramped down)", 1, 1)
    return wait_forever

@state
def wait_forever(world: StationWorld):
    world.set_phase("Idle — Holding Steady", 1, 1)
    while True:
        world.wait(1)

@state
def wait_forever2(world: StationWorld):
    world.wait(1e18)

@state
def switch_to_wait_forever_test(world: StationWorld):
    return wait_forever

@state
def ready_for_cooldown(world:StationWorld):
    # Doesn't really do anything except close HS 
    world.set_phase("Pre-cooling: Heat switches closed", 1, 1)
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("CLOSED")
    world.wait(3)

    # Set He3 setpoints but do nothing
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(45) # Upper stage setpoint = 45 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
    world.station.cryocon.control_enabled(False) 
    print("OPEN THE GREEN HE3 VALVE")
    world.wait(1e6)

@state
def open_charcoal_heatswitch(world: StationWorld):
    world.station.labjack.heatswitch_charcoal("OPEN")
    return wait_forever

@state
def open_pot_heatswitch(world: StationWorld):
    world.station.labjack.heatswitch_pot("OPEN")
    return wait_forever

@state
def open_adr_heatswitch(world: StationWorld):
    world.station.labjack.heatswitch_adr("OPEN")
    return wait_forever

@state
def set_relay_to_ramp(world: StationWorld):
    world.station.labjack.relay("RAMP")
    return wait_forever

@state
def he3_only_cycle(world: StationWorld):
    """
    Helium-3 Sorption Refrigerator Cycle (No Magnet / No ADR).
    Cycles the sorption pump to condense He-3 and achieve ~300 mK base temperature
    at the 1K pot without touching or energizing the superconducting magnet.
    """
    testmode = False
    # 0. safety: check magnet is de-energized
    check_magnet_deenergized(world)
    # Operator must close the green He-3 valve BEFORE step 1
    print("CLOSE THE GREEN HE3 VALVE")

    # 1. set heat switches and check that we're cold enough to start
    world.set_phase("1/4: Pre-cooling Check (Pot < 3.2K)", 1, 4)
    world.station.labjack.heatswitch_pot("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_adr("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_charcoal("OPEN")
    world.wait(1)
    while True:
        mr = most_recent_measurements()
        if mr.get("cryocon_chD_temperature", 100) < 3.2 or mr.get("cryocon_chC_temperature", 100) < 3.2:
            break
        world.wait(1)

    # 2. start heating charcoal
    world.set_phase("2/4: Heating Sorption Charcoal (55K)", 2, 4)
    world.station.cryocon.loop1_source("A")
    world.wait(1)
    world.station.cryocon.loop1_setpoint(65)
    world.wait(1)
    world.station.cryocon.loop2_source("B")
    world.wait(1)
    world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
    world.wait(1)
    world.station.cryocon.control_enabled(True) # heat charcoal
    world.wait(1)

    # 3. wait for he3 to condense
    world.set_phase("3/4: He-3 Condensation Dwell (3.5h)", 3, 4)
    if testmode:
        world.wait(10)
    else:
        world.wait(3600*3.5) # takes about 3.5 hours to condense He-3

    # 4. cool charcoal
    world.set_phase("4/4: Cooling Charcoal Sorption Pump (~3.5h)", 4, 4)
    world.station.labjack.heatswitch_pot("OPEN") # thermally isolate 1K pot
    world.wait(1)
    world.station.cryocon.control_enabled(False) # turn off 40K heat
    if testmode:
        world.wait(1)
    else:
        world.wait(120) # a bit of cooling before closing charcoal heatswitch
    world.station.labjack.heatswitch_charcoal("CLOSED")  
    world.wait(1)
    
    if testmode:
        world.wait(10)
    else:
        world.wait(3600*1)
        world.station.cryocon.loop1_setpoint(65) 
        world.wait(1)
        world.station.cryocon.loop2_source("B")
        world.wait(1)
        world.station.cryocon.loop2_setpoint(1) # Charcoal setpoint = 1 K, AKA OFF
        world.wait(1)
        world.station.cryocon.control_enabled(True) # heat 40K stage
        world.wait(3600*0.5) 
        world.station.cryocon.control_enabled(False) # turn off 40K heat after cooling pot
        world.wait(3600*2)

    # Done — holding steady at base temperature
    world.set_phase("Idle — Holding Steady (He-3 Cycle Complete)", 1, 1)
    return wait_forever

@state
def warmup_300K(world: StationWorld):
    # Safety: ensure magnet is de-energized before warming up
    check_magnet_deenergized(world)
    print("OPEN THE GREEN HE3 VALVE")

    world.set_phase("Warming cryostat to 295 K", 1, 1)
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("CLOSED")
    world.wait(3)
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(295) # Upper stage setpoint = 295 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(295) # Charcoal setpoint = 295 K
    world.station.cryocon.control_enabled(True) # heat charcoal
    world.wait(1e15)

STATES_LIST = [wait_forever, ready_for_cooldown, he3_only_cycle, he3_adr_cycle, ramp_down_magnet, warmup_300K, wait_forever2, switch_to_wait_forever_test, open_adr_heatswitch, open_charcoal_heatswitch, open_pot_heatswitch, set_relay_to_ramp]
STATES_DICT = {s.name(): s for s in STATES_LIST}
