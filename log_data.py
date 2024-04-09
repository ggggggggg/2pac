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
import pylab as plt
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

# import IPython.lib.backgroundjobs as bg
# from plottr.apps import inspectr

# jobs = bg.BackgroundJobManager()
# jobs.new(inspectr.main, db_file_path)

with meas.run() as datasaver:
    for i in range(100):
        print(i)
        update(meas, datasaver)
print("done")

dataset = datasaver.dataset
plot_dataset(dataset)

