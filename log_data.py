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
meas.register_parameter(st.labjack.kepco_voltage, setpoints=[elapsed_time])
meas.register_parameter(st.labjack.relay, paramtype="text")
meas.register_parameter(st.labjack.heatswitch_adr, paramtype="text")
meas.register_parameter(st.labjack.heatswitch_charcoal, paramtype="text")
meas.register_parameter(st.labjack.heatswitch_pot, paramtype="text")
meas.register_custom_parameter("state", paramtype="text")
meas.register_custom_parameter("faa_temperature", unit="K", setpoints=[elapsed_time])
meas.register_custom_parameter("time", unit="s")

def update(datasaver, state):
    parameters = [elapsed_time, st.cryocon.chA_temperature, st.cryocon.chB_temperature,
                  st.cryocon.chC_temperature, st.cryocon.chD_temperature, st.labjack.kepco_current, st.labjack.kepco_voltage,
                  st.labjack.relay, st.labjack.heatswitch_adr, st.labjack.heatswitch_charcoal, st.labjack.heatswitch_pot]
    l=[(param,param()) for param in parameters]+[("state", state.name()),("faa_temperature", st.ls370.ch02.temperature()), ("time", time.time())]
    datasaver.add_result(*l)

datasaver = meas.run()

from imperative_statemachine import state
from world import World
import typing

@dataclass
class LivePlotDataset():
    dataset: qcodes.dataset.data_set.DataSet
    axes: list = field(default=None, init=False)
    fig: plt.matplotlib.figure.Figure = field(default=None, init=False)

    def first_time(self):
        axes,_ = plot_dataset(self.dataset)
        for ax in axes:
            plt.close(ax.figure)
        self.fig = plt.figure(figsize=(18,6))
        self.axes = [plt.subplot(3,3,i) for i in range(1,len(axes)+1)]
        for ax in self.axes:
            ax.grid(True)

    def figure_exists(self):
        if self.fig is None:
            return False
        return plt.fignum_exists(self.fig.number)

    def plot(self):
        if not self.figure_exists():
            self.first_time()
        for ax in self.axes:
            ax.clear()
        plot_dataset(self.dataset, self.axes)
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
def chill_after_ramp_down(world: StationWorld):
    world.wait(10)
    return

@state
def zero_current(world: StationWorld):
    world.wait(seconds=5)
    return ramp_up

@state 
def ramp_up(world: StationWorld):
    target_voltage = 2
    target_time_s = 20
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = target_voltage/target_N_steps
    for i in range(target_N_steps):
        world.set_voltage(step_size*(i+1))
        world.wait(seconds=target_step_duration_s)
    return soak

@state
def soak(world: StationWorld):
    world.wait(20)
    return ramp_down

@state
def ramp_down(world: StationWorld):
    Vstart = world.voltage_V
    target_time_s = 20
    max_voltage = 2
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = -np.sign(Vstart)*Vstart/target_N_steps
    volts = np.arange(Vstart, step_size, step_size)
    for v in volts:
        world.set_voltage(v)
        world.wait(target_step_duration_s)
    return chill_after_ramp_down

@state
def chill_after_ramp_down(world: StationWorld):
    world.wait(10)

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


heater = st.ls370.heater

with meas.run( ) as datasaver:
    world.datasaver = datasaver
    world.run_state(cycle_heatswitches)
dataset = datasaver.dataset
plot_dataset(dataset)
# plt.pause(30)


