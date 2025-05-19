import numpy as np
from station_2pac import get_station
from qcodes import (initialise_or_create_database_at,
load_or_create_experiment,
Measurement)
from qcodes.parameters import ElapsedTimeParameter, Parameter
from pathlib import Path
from qcodes.logger import start_all_logging
start_all_logging()
from qcodes.dataset import (plot_dataset)
import qcodes
import pylab as plt
import time
from dataclasses import dataclass, field
plt.close("all")
plt.ion()

db_file_path = Path.home() / ".2pac_logs" / "2pac.db"
initialise_or_create_database_at(Path.home() / ".2pac_logs" / "2pac.db")
exp = load_or_create_experiment(
    experiment_name='running 2pac adr',
    sample_name="no sample"
)

st = get_station()

elapsed_time = ElapsedTimeParameter('elapsed_time')
meas = Measurement(exp=exp, name='adr run', station=st)
meas.register_parameter(elapsed_time)  # register the first independent parameter
# meas.register_parameter(st.ls370.ch02.temperature, setpoints=[time],)  # now register the dependent oone
meas.register_parameter(st.cryocon.chA_temperature, setpoints=[elapsed_time])
meas.register_parameter(st.cryocon.chB_temperature, setpoints=[elapsed_time])
meas.register_parameter(st.cryocon.chC_temperature, setpoints=[elapsed_time])
meas.register_parameter(st.cryocon.chD_temperature, setpoints=[elapsed_time])
meas.register_parameter(st.labjack.kepco_current, setpoints=[elapsed_time])
meas.register_parameter(st.labjack.kepco_voltage)
meas.register_parameter(st.ls370.heater.out, setpoints=[elapsed_time])
meas.register_parameter(st.labjack.relay, paramtype="text")
meas.register_parameter(st.labjack.heatswitch_adr, paramtype="text")
meas.register_parameter(st.labjack.heatswitch_charcoal, paramtype="text")
meas.register_parameter(st.labjack.heatswitch_pot, paramtype="text")
meas.register_parameter(st.labjack.he3_pressure, setpoints=[elapsed_time])
meas.register_custom_parameter("state", paramtype="text")
meas.register_custom_parameter("faa_temperature", unit="K", setpoints=[elapsed_time])
meas.register_custom_parameter("time", unit="s")

def retry(f,n=3):
    # try cryocon is being unreliable on returning temp, so try a few times then return nan
    for i in range(n):
        try:
            return f()
        except: 
            pass
            # print(f"RETRYING {i=}")
            # st.cryocon.write("CLR")
            # time.sleep(0.1)
    return np.nan

def update(datasaver, state):
    # st.cryocon.write("CLR") # try to help the cryocon work more reliably
    parameters = [elapsed_time, st.cryocon.chA_temperature, st.cryocon.chB_temperature,
                  st.cryocon.chC_temperature, st.cryocon.chD_temperature, st.labjack.kepco_current, st.labjack.kepco_voltage, st.ls370.heater.out,
                  st.labjack.relay, st.labjack.heatswitch_adr, st.labjack.heatswitch_charcoal, st.labjack.heatswitch_pot, st.labjack.he3_pressure]
    l=[(param,retry(param,n=1)) for param in parameters]+[("state", state.name()),("faa_temperature", st.ls370.ch04.temperature()), ("time", time.time())]
    datasaver.add_result(*l)


datasaver = meas.run()

def most_recent_measurements():
    data = datasaver.dataset.cache.data()
    ret = {}
    for key in data.keys():
        v = data[key][key][-1]
        ret[key]=v
    return ret

def pretty_str_dict(d: dict):
    s = ""
    for key, value in d.items():
        s+= f"{key} {value}\n"
    return s



from imperative_statemachine import state
from world import World
import typing

import matplotlib.pyplot as plt
from qcodes.dataset.plotting import plot_dataset
from dataclasses import dataclass, field
import ipywidgets as widgets
from IPython.display import display
from qcodes.dataset.data_set import DataSet

@dataclass
class LivePlotDataset:
    dataset: DataSet
    axes: list = field(default=None, init=False)
    extra_ax: plt.matplotlib.axes._axes.Axes = field(default=None, init=False)
    fig: plt.matplotlib.figure.Figure = field(default=None, init=False)
    dropdown: widgets.Dropdown = field(default=None, init=False)

    def first_time(self):
        axes, _ = plot_dataset(self.dataset)
        for ax in axes:
            plt.close(ax.figure)
        self.fig = plt.figure(figsize=(18, 6))
        self.axes = [plt.subplot(3, 3, i) for i in range(1, len(axes) + 1)]
        self.extra_ax = plt.subplot(3, 3, len(axes) + 1)
        for ax in self.axes:
            ax.grid(True)

        # Create and display dropdown
        self.dropdown = widgets.Dropdown(
            options=['Option 1', 'Option 2', 'Option 3'],
            value='Option 1',
            description='Select:',
        )
        self.dropdown.observe(self._on_dropdown_change, names='value')
        display(self.dropdown)

    def _on_dropdown_change(self, change):
        # Handle dropdown changes (you can trigger different behavior here)
        print(f"Dropdown changed to: {change['new']}")
        self.plot()  # Re-plot when dropdown changes if needed

    def figure_exists(self):
        return self.fig is not None and plt.fignum_exists(self.fig.number)

    def plot(self):
        if not self.figure_exists():
            self.first_time()
        for ax in self.axes:
            ax.clear()
        plot_dataset(self.dataset, self.axes)
        self.extra_ax.clear()

        # Example: update extra_ax with recent measurement info
        s = pretty_str_dict(most_recent_measurements())
        self.extra_ax.text(0, 0, s, transform=self.extra_ax.transAxes)
        plt.tight_layout()


@dataclass
class StationWorld(World):
    station: qcodes.station.Station = None
    datasaver: typing.Any = None
    liveplot: LivePlotDataset = None

    def update(self, state):
        update(self.datasaver, state)
        if self.liveplot is None:
            self.liveplot = LivePlotDataset(self.datasaver.dataset)
        self.liveplot.plot()

world = StationWorld(station=st)

    

@state
def zero_current(world: StationWorld):
    world.wait(seconds=5)
    return ramp_up

@state 
def ramp_up(world: StationWorld):
    world.station.labjack.heatswitch_adr("CLOSED")
    world.wait(1)
    world.station.labjack.relay("RAMP")
    world.wait(1)
    ramp_controller = world.station.ls370.heater
    ramp_controller.mode('open_loop')
    world.wait(1)
    ramp_controller.range("100uA")
    world.wait(1)
    hout_start =0
    # target_hout= 55  # 55 should get to 9.53 A, which is the hardware current limit of the kepco supply
    target_hout = 5 # low value for testing
    target_time_s = 20*60
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = target_hout/target_N_steps
    houts = np.arange(hout_start, target_hout, step_size)
    for hout in houts:
        ramp_controller.out(hout)
        world.wait(target_step_duration_s)
    return soak

@state
def soak(world: StationWorld, slow_close_charcoal = False):
    # world.wait(10*60)
    
     # Open pot HS -> turn off charcoal heater -> close charcoal HS (default: slow)

    world.station.labjack.heatswitch_pot("OPEN")
    world.station.cryocon.control_enabled(False)
    world.wait(1)
    world.station.labjack.heatswitch_charcoal("CLOSED")  
    world.wait(60) # this is arbitrary, 
    #in reality it takes about 4.8 ks (1hr 20 min) for the pot to get to 1 K after the charcoal HS is closed (run 192).
    #better to open ADR HS and ramp down while tracking pot temp and not on a timer
    return ramp_down # not recommended if magnet is holding full current
    
@state 
def slow_close_charcoal_heatswitch(world: StationWorld):
    # This has a very high rep rate (~ 100 times per he3 cycle) on the heat switch. 

    # world.station.labjack.heatswitch_charcoal("OPEN")
    LIMIT_3K= 5.3 # used ro be 3.5 K -> copying KPAC, magnet doesn't mind too much
    charcoal_temp_target_K = 10  # around charcoal = 30K, the 3K plate starts monotonously cooling off
    pot_target_temp_K = 1
    while True:
        mr = most_recent_measurements()
        charcoal_temp = mr["cryocon_chB_temperature"]
        plate_3k_temp = mr["cryocon_chC_temperature"]
        pot_temp = mr["cryocon_chD_temperature"]
    
        if plate_3k_temp < LIMIT_3K:
            if world.station.labjack.heatswitch_charcoal() == "OPEN":
                world.station.labjack.heatswitch_charcoal("CLOSED")
                world.wait(2)
        else:
            if world.station.labjack.heatswitch_charcoal()=="CLOSED":
                world.station.labjack.heatswitch_charcoal("OPEN")
                world.wait(2)
        if charcoal_temp < charcoal_temp_target_K:
        # if pot_temp < pot_target_temp_K:
            return ramp_down
        


@state
def ramp_down(world: StationWorld):
    world.station.labjack.heatswitch_adr("OPEN")
    mr = most_recent_measurements()
    hout_start = mr["ls370_heater_out"]
    if hout_start:   #edge case where magnet wasn't ramped and heater was always zero (follows from soak state)
        target_time_s = 20*60
        max_hout = 55
        target_hout = 0
        target_step_duration_s = 1
        target_N_steps = int(target_time_s/target_step_duration_s)
        step_size = -np.sign(hout_start)*hout_start/target_N_steps
        houts = np.arange(hout_start, step_size, step_size)
        for hout in houts:
            world.station.ls370.heater.out(hout)
            world.wait(target_step_duration_s)
        
    return chill_after_ramp_down

@state
def chill_after_ramp_down(world: StationWorld):
    world.station.ls370.heater.mode('off')
    world.wait(10*60) # allow magnet to ramp down to about 0.5 A before asking to switch to CONTROL
    while True:
        world.wait(60)
        mr = most_recent_measurements()
        I_mag = mr['labjack_kepco_current']
        print(f'Magnet current is {I_mag}. Waiting...')
        if I_mag < 0.1:
            print('Setpoint reached. Switching relay to CONTROL.')
            world.station.labjack.relay("CONTROL")
            return wait_forever

@state
def cycle_heatswitches(world: StationWorld):
    for i in range(10):
        st.labjack.heatswitch_pot("OPEN")
        world.wait(3)
        st.labjack.heatswitch_adr("OPEN")
        world.wait(3)
        st.labjack.heatswitch_charcoal("OPEN")
        world.wait(3)
        st.labjack.heatswitch_pot("CLOSED")
        world.wait(3)
        st.labjack.heatswitch_adr("CLOSED")
        world.wait(3)
        st.labjack.heatswitch_charcoal("CLOSED")
        world.wait_for_input("yo")

@state 
def start_he3_cycle(world: StationWorld, wait_to_cool = 2*60*60, do_mag_cycle = False):
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("OPEN")

    # Heat charcoal
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(45) # Upper stage setpoint = 45 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
    world.station.cryocon.control_enabled(True) # heat charcoal
    
    # Wait for setpoint to be reached and for plate to cool
    world.wait(wait_to_cool)
    return soak

@state 
def full_cycle_one_state(world: StationWorld):
    testmode = False
    # 1. check that we're cold enough to start
    # 2. start heating charcoal
    # 3. ramp up adr
    # 4. wait for he3 to condense
    # 5. cool charcoal
    # 6. ramp down adr

    # 1. check that we're cold enough to start
    while True:
        mr = most_recent_measurements()
        print(mr)
        # if mr["cryocon_chB_temperature"] > 5:
        #     print("charcoal too hot")
        #     continue

        # if mr["cryocon_chC_temperature"] > 3.2:
        #     print("3K plate too hot")
        #     continue
        world.wait(1)
        break

    world.station.labjack.heatswitch_pot("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_adr("CLOSED")
    world.wait(1)
    world.station.labjack.heatswitch_charcoal("OPEN")
    world.wait(1)


    # 2. start heating charcoal
    world.station.cryocon.loop1_source("A")
    world.wait(1)
    world.station.cryocon.loop1_setpoint(65) # Upper stage setpoint = 45 K, trying higher so i t actually goes up?
    # our base temp is about 60K, so 45K does nothing
    # notices that if i head to 65 K then cool back down the He3 temp drops a lot
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
    hout_start =0
    if testmode:
        target_hout = 1 # small max current
        target_time_s = 30
    else:
        target_hout= 55  # 55 should get to 9.53 A, which is the hardware current limit of the kepco supply
        target_time_s = 30*60
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = target_hout/target_N_steps
    houts_up = np.arange(target_N_steps)*step_size
    for hout in houts_up:
        ramp_controller.out(hout)
        world.wait(target_step_duration_s)

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
    # while True:
    #     mr = most_recent_measurements()
    #     print(mr)
    #     if mr["cryocon_chB_temperature"] < 6:
    #         break
    #     else:
    #         print("charcoal not yet cooled")
    #     world.wait(1)
    if testmode:
        world.wait(10)
    else:
        world.wait(3660*3)
        world.station.cryocon.loop1_setpoint(65) # Upper stage setpoint = 45 K, trying higher so i t actually goes up?
        # our base temp is about 60K, so 45K does nothing
        # notices that if i head to 65 K then cool back down the He3 temp drops a lot
        world.wait(1)
        world.station.cryocon.loop2_source("B")
        world.wait(1)
        world.station.cryocon.loop2_setpoint(1) # Charcoal setpoint = 1 K, AKA OFF
        world.wait(1)
        world.station.cryocon.control_enabled(True) # heat 40K stage
        world.wait(3600*0.5) # takes about 2 hours
        world.station.cryocon.control_enabled(False) # turn off 40K heat after cooling pot
        world.wait(3660*0.5)
        # test based on seeing pot temp drop (400 mK to 300 mK)
        # after heating and cooling 40K stage 60K->65K->60K 

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
    # world.wait(1)
    # ramp_controller.setpoint(0.05)
    # world.wait(1)
    # ramp_controller.mode('closed')


    
    # be done
    return wait_forever

@state 
def cycle_charcoal_hs(world: StationWorld):
    world.station.cryocon.control_enabled(True)
    for i in range(10):
        world.station.labjack.heatswitch_charcoal("OPEN")
        world.wait(100)
        world.station.labjack.heatswitch_charcoal("CLOSED")
        world.wait(100)
    world.station.cryocon.control_enabled(False)

@state
def wait_forever(world: StationWorld):
    world.wait(1e15)

 
@state
def return_immediatley(world: StationWorld):
    world.wait(0.5)   

#heater = st.ls370.heater
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
    world.wait(1e6)

@state
def start_adr_cycle(world:StationWorld):

    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.relay("RAMP")
    ramp_control = world.station.ls370.heater
    ramp_control.mode('open_loop')
    ramp_control.range("100uA")
    n_steps = 1200
    ramp_out = np.linspace(0, 5,n_steps, endpoint=True)
    for v_out in ramp_out:
        ramp_control.out(v_out)
        world.wait(1)
    world.wait(60*15)
    world.station.labjack.heatswitch_pot("OPEN")
    world.station.labjack.heatswitch_adr("OPEN")
    for v_out in np.flip(ramp_out):
        ramp_control.out(v_out)
        world.wait(1)
    world.wait(60*20)

    world.wait_for_input('go')

with meas.run() as datasaver:
    world.datasaver = datasaver
    world.run_state(wait_forever)
    # world.run_state(start_he3_cycle)
    # world.run_state(ready_for_cooldown)
    # world.run_state(ramp_tester)
    # world.run_state(chill_after_ramp_down)
    # world.run_state(cycle_heatswitches)
    # world.run_state(slow_close_charcoal_heatswitch)
    # world.run_state(cycle_heatswitches)
    # world.run_state(soak)
    # world.run_state(full_cycle_one_state)
dataset = datasaver.dataset
# plot_dataset(dataset)
# plt.pause(30)


