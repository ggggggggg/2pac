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
    ramp_control.range("10mA")
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


