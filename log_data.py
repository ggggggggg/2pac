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
                  st.cryocon.chC_temperature, st.cryocon.chD_temperature, st.labjack.kepco_current, st.labjack.kepco_voltage,
                  st.labjack.relay, st.labjack.heatswitch_adr, st.labjack.heatswitch_charcoal, st.labjack.heatswitch_pot]
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

@dataclass
class LivePlotDataset():
    dataset: qcodes.dataset.data_set.DataSet
    axes: list = field(default=None, init=False)
    extra_ax: plt.matplotlib.axes._axes.Axes = field(default=None, init=False)
    fig: plt.matplotlib.figure.Figure = field(default=None, init=False)

    def first_time(self):
        axes,_ = plot_dataset(self.dataset)
        for ax in axes:
            plt.close(ax.figure)
        self.fig = plt.figure(figsize=(18,6))
        self.axes = [plt.subplot(3,3,i) for i in range(1,len(axes)+1)]
        self.extra_ax = plt.subplot(3,3,len(axes)+1)
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
        self.extra_ax.clear()
        # self.extra_ax.set_axis_off()
        s = pretty_str_dict(most_recent_measurements())
        plt.tight_layout()
        self.extra_ax.text(0,0, s, transform=self.extra_ax.transAxes)


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

@state 
def start_he3_cycle(world: StationWorld):
    world.station.labjack.heatswitch_pot("CLOSED")
    world.station.labjack.heatswitch_adr("CLOSED")
    world.station.labjack.heatswitch_charcoal("OPEN")
    world.wait(3)

    # Heat charcoal
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(46) # Upper stage setpoint = 45 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(55) # Charcoal setpoint = 55 K
    world.station.cryocon.control_enabled(True) # heat charcoal
    
    # Wait for setpoint to be reached and for plate to cool
    world.wait(3600*2)

    # ramp magnet and soak
    # world.wait(5)

    return slow_close_charoal_heatswitch


    # Open pot HS -> turn off charcoal power -> close charcoal HS
    # world.station.labjack.heatswitch_pot("OPEN")
    # world.station.cryocon.control_enabled(False)
    # world.station.labjack.heatswitch_charcoal("CLOSED")
    # world.wait(3)


@state 
def slow_close_charoal_heatswitch(world: StationWorld):
    LIMIT_3K=4.5
    charcoal_temp_target_K = 4
    while True:
        mr = most_recent_measurements()
        charcoal_temp = mr["cryocon_chB_temperature"]
        plate_3k_temp = mr["cryocon_chC_temperature"]
        print(f"{charcoal_temp=} {plate_3k_temp=}")
        if plate_3k_temp < LIMIT_3K:
            if world.station.labjack.heatswitch_charcoal() == "OPEN":
                world.station.labjack.heatswitch_charcoal("CLOSED")
                world.wait(1)
        else:
            if world.station.labjack.heatswitch_charcoal()=="CLOSED":
                world.station.labjack.heatswitch_charcoal("OPEN")
                world.wait(1)
        if charcoal_temp < charcoal_temp_target_K:
            return
        world.wait(1)

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
    world.wait(1e6)

#heater = st.ls370.heater
@state
def warmup_300K(world: StationWorld):
    world.station.cryocon.loop1_source("A")
    world.station.cryocon.loop1_setpoint(300) # Upper stage setpoint = 300 K
    world.station.cryocon.loop2_source("B")
    world.station.cryocon.loop2_setpoint(295) # Charcoal setpoint = 295 K
    world.station.cryocon.control_enabled(True) # heat charcoal


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


with meas.run() as datasaver:
    world.datasaver = datasaver
    world.run_state(start_he3_cycle)
    #world.run_state(warmup_300K)
dataset = datasaver.dataset
# plot_dataset(dataset)
# plt.pause(30)


