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
plt.close("all")
plt.ion()

db_file_path = Path.home() / ".2pac_logs" / "2pac.db"
initialise_or_create_database_at(Path.home() / ".2pac_logs" / "2pac.db")
exp = load_or_create_experiment(
    experiment_name='running 2pac adr',
    sample_name="no sample"
)

st = get_station()

time = ElapsedTimeParameter('time')
meas = Measurement(exp=exp, name='adr run', station=st)
meas.register_parameter(time)  # register the first independent parameter
meas.register_parameter(st.ls370.ch02.temperature, setpoints=[time])  # now register the dependent oone
meas.register_parameter(st.cryocon.chA_temperature, setpoints=[time])
meas.register_parameter(st.cryocon.chB_temperature, setpoints=[time])
meas.register_parameter(st.cryocon.chC_temperature, setpoints=[time])
meas.register_parameter(st.cryocon.chD_temperature, setpoints=[time])
meas.register_parameter(st.labjack.kepco_current, setpoints=[time])
meas.register_parameter(st.labjack.kepco_voltage, setpoints=[time])
meas.register_parameter(st.labjack.relay, paramtype="text")

def update(meas, datasaver):
    parameters = [time, st.ls370.ch02.temperature, st.cryocon.chA_temperature, st.cryocon.chB_temperature,
                  st.cryocon.chC_temperature, st.cryocon.chD_temperature, st.labjack.kepco_current, st.labjack.kepco_voltage,
                  st.labjack.relay]
    datasaver.add_result(*[(param,param()) for param in parameters])

datasaver = meas.run()

from imperative_statemachine import state
from world import World
from dataclasses import dataclass
import typing

@dataclass
class StationWorld(World):
    station: qcodes.station.Station = None
    datasaver: typing.Any = None

    def update(self):
        update(meas, self.datasaver)
    

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

heater = st.ls370.heater

# with meas.run( ) as datasaver:
#     world.datasaver = datasaver
#     world.run_state(chill_after_ramp_down)
# dataset = datasaver.dataset
# plot_dataset(dataset)
# plt.pause(30)

