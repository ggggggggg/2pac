import time
import numpy as np
import qcodes
import typing
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from imperative_statemachine import state
from world_no_mpl import World

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
                  st.labjack.relay, st.labjack.heatswitch_adr, st.labjack.heatswitch_charcoal, st.labjack.heatswitch_pot, st.labjack.he3_pressure]
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

@dataclass
class StationWorld(World):
    station: qcodes.station.Station = None
    datasaver: typing.Any = None

    def update(self, state):
        update(self.datasaver, state)

@state 
def he3_adr_cycle(world: StationWorld):
    testmode = False
    # 1. check that we're cold enough to start
    # 2. start heating charcoal
    # 3. ramp up adr
    # 4. wait for he3 to condense
    # 5. cool charcoal
    # 6. ramp down adr

    # 1. set heat switches and check that we're cold enough to start
    world.station.labjack.heatswitch_pot("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_adr("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_charcoal("OPEN")
    world.wait(1)
    while True:
        mr = most_recent_measurements()
        if mr.get("cryocon_chC_temperature", 100) < 3.2:
            break
        world.wait(1)

    # 2. start heating charcoal
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
        target_hout= 58.1  # 55 should get to 9.53 A, which is the hardware current limit of the kepco supply
        target_time_s = 30*60
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = target_hout/target_N_steps
    houts_up = np.arange(target_N_steps)*step_size
    for hout in houts_up:
        ramp_controller.out(hout)
        world.wait(target_step_duration_s)
        print("CLOSE THE GREEN HE3 VALVE")

    # 4. wait for he3 to condense
    if testmode:
        world.wait(10)
    else:
        world.wait(3600*3.5) # takes about 2 hours

    # 4. cool charcoal
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
        world.wait(3660*1)
        world.station.cryocon.loop1_setpoint(65) 
        world.wait(1)
        world.station.cryocon.loop2_source("B")
        world.wait(1)
        world.station.cryocon.loop2_setpoint(1) # Charcoal setpoint = 1 K, AKA OFF
        world.wait(1)
        world.station.cryocon.control_enabled(True) # heat 40K stage
        world.wait(3600*0.5) 
        world.station.cryocon.control_enabled(False) # turn off 40K heat after cooling pot
        world.wait(3660*2)

    # 5. ramp down adr
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
    return wait_forever

@state
def wait_forever(world: StationWorld):
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
def warmup_300K(world: StationWorld):
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("CLOSED")
    world.wait(3)
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(295) # Upper stage setpoint = 300 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(295) # Charcoal setpoint = 295 K
    world.station.cryocon.control_enabled(True) # heat charcoal
    world.wait(1e15)

STATES_LIST = [wait_forever, he3_adr_cycle, warmup_300K, ready_for_cooldown, wait_forever2, switch_to_wait_forever_test, open_adr_heatswitch, open_charcoal_heatswitch, open_pot_heatswitch, set_relay_to_ramp]
STATES_DICT = {s.name(): s for s in STATES_LIST}
