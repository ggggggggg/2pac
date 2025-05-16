import sys
import numpy as np
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QComboBox, QTextEdit, QLabel, QHBoxLayout, QLineEdit
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
import matplotlib.pyplot as plt
import time

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
from world_no_mpl import World
import typing

@dataclass
class StationWorld(World):
    station: qcodes.station.Station = None
    datasaver: typing.Any = None

    def update(self, state):
        update(self.datasaver, state)
        print("yo i updated")

@state
def wait_forever(world: StationWorld):
    while True:
        world.wait(1)
@state
def wait_forever2(world: StationWorld):
    world.wait(1e18)

with meas.run() as datasaver:
    world = StationWorld(station=st)

    world.datasaver = datasaver

    # Worker thread that calls get_data in the background
    class DataFetchThread(QThread):
        data_fetched = pyqtSignal(np.ndarray)

        def run(self):
            global wait_forever
            state = wait_forever
            runner = world.state_runner(state)
            time.sleep(world.next_tick_target_time_s()-time.time())
            world._update(state)
            tstart = world.last_update_time_s
            for (state, line_number) in runner:
                elapsed = world.last_update_time_s-tstart
                print(f"state={state.name()} {line_number=} {elapsed=:.2f} state_elapsed_s={world.state_elapsed_s():.2f}")
                print(state.code_highlighted(line_number))
                self.data_fetched.emit(np.zeros(4))

    class MyApp(QWidget):
        def __init__(self):
            super().__init__()

            # Set up the main window layout
            self.setWindowTitle("PyQt5 with Matplotlib")
            main_layout = QHBoxLayout()  # Use HBox to place plot on the left and UI elements on the right

            # Create the plot and canvas
            self.figure = plt.Figure(figsize=(12.5, 10))
            self.ax = self.figure.add_subplot(111)            
            self.canvas = FigureCanvas(self.figure)
            self.toolbar = NavigationToolbar2QT(self.canvas, self)

            # Set up the plot layout
            plot_layout = QVBoxLayout()
            plot_layout.addWidget(self.toolbar)
            plot_layout.addWidget(self.canvas)

            # Set up the right-side layout for UI elements
            right_layout = QVBoxLayout()

            # Create dropdown (ComboBox)
            self.combo_box = QComboBox(self)
            self.combo_box.addItems(["a", "b", "c"])
            self.combo_box.currentTextChanged.connect(self.update_title)
            right_layout.addWidget(self.combo_box)

            # Set up the text output field with a vertical scroll bar
            self.text_output = QTextEdit(self)
            self.text_output.setText("This is a static text line.\n" * 10)  # Static 10 lines of text
            self.text_output.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # Always show the scroll bar
            self.text_output.setReadOnly(True)  # Make the text field non-editable
            right_layout.addWidget(self.text_output)

            # Add elements with "open" / "closed" labels
            self.status_layout = QVBoxLayout()

            # Create labels for "open" / "closed"
            self.labels = [QLabel(f"Item {i+1}: Closed") for i in range(3)]

            for label in self.labels:
                self.status_layout.addWidget(label)  # Add each label to the layout

            right_layout.addLayout(self.status_layout)

            # Add a text input field
            self.text_input = QLineEdit(self)
            self.text_input.setPlaceholderText("Enter some text here...")
            right_layout.addWidget(self.text_input)

            # Add right_layout to the main layout
            main_layout.addLayout(plot_layout)
            main_layout.addLayout(right_layout)

            # Set the layout for the window
            self.setLayout(main_layout)

            # Set up the background thread to fetch data
            self.data_thread = DataFetchThread()
            self.data_thread.data_fetched.connect(self.update_plot)
            self.data_thread.start()

            self.update_plot()

        def update_title(self):
            selected = self.combo_box.currentText()
            self.setWindowTitle(f"Selected: {selected}")

        def update_plot(self):
            try:
                dataset = datasaver.dataset
            except:
                print("dataset doesnt exist")
                return
            # Save the current zoom/pan state
            # xlim = self.ax.get_xlim()
            # ylim = self.ax.get_ylim()

            # Clear the plot and plot the new data
            self.ax.clear()
            data = dataset.cache.data()
            x= dataset.cache.data()["time"]["time"]
            for key in data.keys():
                if key == "time":
                    continue
                v = data[key][key]
                try:
                    self.ax.plot(x, v, label=key)
                except:
                    pass
            self.ax.legend()
            self.ax.set_yscale("log")

            # Restore the zoom/pan state
            # self.ax.set_xlim(xlim)
            # self.ax.set_ylim(ylim)

            # Redraw the canvas
            self.canvas.draw()

    # Initialize the application and show the window
    app = QApplication(sys.argv)
    window = MyApp()
    window.show()
    sys.exit(app.exec_())
