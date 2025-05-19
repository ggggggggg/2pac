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
# plt.close("all")
# plt.ion()

db_file_path = Path.home() / ".2pac_logs" / "2pac.db"
initialise_or_create_database_at(Path.home() / ".2pac_logs" / "2pac.db")
exp = load_or_create_experiment(
    experiment_name='running 2pac adr',
    sample_name="no sample"
)
datasaver_global = None # init this later

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
    data = datasaver_global.dataset.cache.data()
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
        # print(mr)
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




# Worker thread that calls get_data in the background
class DataFetchThread(QThread):
    state_update = pyqtSignal(str, str)
    def __init__(self, world, first_state, states_dict):
        super().__init__()
        self.world = world
        self.next_state = first_state
        self.states_dict = states_dict
        self.state = None
        self.current_combo_value = "a"  # Default value

    def set_combo_value(self, value: str):
        print(f"[Thread] Dropdown updated to: {value}")
        self.current_combo_value = value
        self.next_state = self.states_dict[value]
    
    def run(self):
        runner = self.world.state_runner(self.next_state)
        self.state = self.next_state
        self.next_state = None
        state = self.state
        time.sleep(max(0, self.world.next_tick_target_time_s()-time.time()))
        self.world._update(state)
        tstart = self.world.last_update_time_s
        for (state, line_number) in runner:
            self.state = state
            if self.next_state is not None:
                print("switching state")
                self.run()
            elapsed = self.world.last_update_time_s-tstart
            s1 = f"state={state.name()} {line_number=} {elapsed=:.2f} state_elapsed_s={self.world.state_elapsed_s():.2f}"
            s2 = state.code_highlighted(line_number)
            self.state_update.emit(s1, s2)

def adjust_lightness(color, amount=0.5):
    import matplotlib.colors as mc
    import colorsys
    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, amount * c[1])), c[2])
    
        
def plot_dataset(dataset, ax, xloc_mouse):
    # Save the current zoom/pan state
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()

    # Clear the plot and plot the new data
    ax.clear()
    data = dataset.cache.data()
    # print(data)
    t = dataset.cache.data()["time"]["time"]
    x = t-t[0] 
    if xloc_mouse is None:
        xloc_ind = None
        data_xloc = None
    else:
        xloc_ind = np.argmin(np.abs(x-xloc_mouse))
        data_xloc = {key:data[key][key][xloc_ind] for key in data.keys()}
    data_mr = {key:data[key][key][-1] for key in data.keys()}
    # print(f"{list(data.keys())=}")
    keys_hs = ["labjack_heatswitch_adr", "labjack_heatswitch_charcoal", "labjack_heatswitch_pot", "labjack_relay"]
    units = {param_spec.name:param_spec.unit for param_spec in dataset.get_parameters()}
    for key in data.keys():
        if key == "time" or key =="state" or key in keys_hs:
            continue
        v = data[key][key]
        unit = units[key]
        try:
            val = data_mr[key]
            ax.plot(x, v, label=f"{key}={val:.2f} {unit}")
        except:
            print(f"failed to plot {key}")

    from matplotlib.cm import get_cmap
    from matplotlib.colors import to_rgb
    cmap = get_cmap('tab10')  # or 'tab20', 'Set1', etc.
    base_colors = [cmap(i) for i in range(len(keys_hs))]  # RGBA tuples

    for i, key in enumerate(keys_hs):
        if key == "labjack_relay":
            v_open = np.array([d=="CONTROL" for d in data[key][key]])
            v_closed = np.array([d=="RAMP" for d in data[key][key]])
            v_unknown = np.array([d=="UNKNOWN" for d in data[key][key]])
        else:
            v_open = np.array([d=="OPEN" for d in data[key][key]])
            v_closed = np.array([d=="CLOSED" for d in data[key][key]])
            v_unknown = np.array([d=="UNKNOWN" for d in data[key][key]])            
        yval = (2e-2)*(0.9**i)
        y_open = np.where(v_open, yval, np.nan)
        y_closed = np.where(v_closed, yval, np.nan)
        y_unknown = np.where(v_unknown, yval, np.nan)


        color = base_colors[i]
        color_light = adjust_lightness(color)

        val = data_mr[key]

        ax.plot(x, y_closed, color=color, lw=4, label=f"{key}={val}")
        ax.plot(x, y_open, color=color, lw=2)
        ax.plot(x, y_unknown, "--", color=color, lw=2)



    ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1), borderaxespad=0.)
    # Add text annotation below the plot
    if data_xloc is not None:
        annotation_lines =[]
        val = x[xloc_ind]
        annotation_lines.append(f"{elapsed_time}={val} s")
        for key in data.keys():
            if key in keys_hs+["state"]:
                continue
            val = data_xloc[key]
            unit = units[key]
            line = f"{key}={val:.3f} {unit}"
            annotation_lines.append(line)
        for key in keys_hs+["state"]:
            val = data_xloc[key]
            line = f"{key}={val}"
            annotation_lines.append(line)

        ax.axvline(xloc_mouse)
        annotation_text = "\n".join(annotation_lines)
        ax.text(
            1.05, 0.5,  # x, y in axes coordinates
            annotation_text,
            transform=ax.transAxes,
            fontsize=12,
            verticalalignment='top',
            horizontalalignment='left',
            family='monospace',
        )    
    ax.set_yscale("log")
    ax.grid(True, which="both", axis="both")
    # ax.set_ylim(ylim)
    # ax.set_xlim(xlim)

def get_arrow_linenum(s2):
    # Split the string into lines
    lines = s2.split('\n')

    # Find the index of the line starting with '-->'
    for i, line in enumerate(lines):
        if line.startswith('-->'):
            # print(f"Index of the line starting with '-->': {i}")
            break
    return i

def get_arrow_char_index(s2, plus=0):
    lines = s2.split('\n')
    char_index = 0

    for line in lines:
        if line.startswith('-->'):
            return min(char_index+plus, len(s2)-1)
        # Add length of line + 1 for the newline character
        char_index += len(line) + 1

    return 0  # Not found

def color_line(textedit, line_number, color=None):
    from PyQt5.QtGui import QTextCursor, QTextCharFormat, QColor

    if color is None:
        color = QColor("yellow")  # Default color if none is provided

    # Access the document and validate line number
    doc = textedit.document()
    if line_number < 0 or line_number >= doc.blockCount():
        return  # Out of range

    # Clear all previous highlights by resetting formatting for all blocks
    cursor = QTextCursor(doc)
    cursor.beginEditBlock()  # Group all changes for efficiency

    block = doc.firstBlock()
    while block.isValid():
        block_cursor = QTextCursor(block)
        block_cursor.select(QTextCursor.LineUnderCursor)
        block_cursor.setCharFormat(QTextCharFormat())  # Reset to default
        block = block.next()

    cursor.endEditBlock()

    # Now, highlight the specified line
    block = doc.findBlockByNumber(line_number)
    cursor = QTextCursor(block)

    # Set the background color for the specified line
    fmt = QTextCharFormat()
    fmt.setBackground(color)

    # Select the entire line and apply the format
    cursor.select(QTextCursor.LineUnderCursor)
    cursor.setCharFormat(fmt)




class MyApp(QWidget):
    def __init__(self, world, dataset, states_dict):
        super().__init__()

        screen_geometry = QApplication.desktop().screenGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        # Set the window size: Maximized width, and a fixed height
        self.setGeometry(0, 0, screen_width, int(0.7*screen_height))      

        # dont assign wrold because we pass it to another thread
        # dataset seems thread safe?
        self.world = world # but hey maybe it will work anyway?
        self.dataset = dataset
        self.states_dict = states_dict

        # Set up the main window layout
        self.setWindowTitle("PyQt5 with Matplotlib")
        main_layout = QHBoxLayout()  # Use HBox to place plot on the left and UI elements on the right

        # Create the plot and canvas
        self.figure = plt.Figure(figsize=(12.5, 10))
        self.ax = self.figure.add_subplot(111)            
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.figure.canvas.mpl_connect("motion_notify_event", self.mpl_on_mouse_move)

        # Set up the plot layout
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas)

        # Set up the right-side layout for UI elements
        right_layout = QVBoxLayout()

        # Create dropdown (ComboBox)
        self.combo_box = QComboBox(self)
        self.combo_box.addItems(list(states_dict.keys()))
        self.combo_box.currentTextChanged.connect(self.update_title)
        right_layout.addWidget(self.combo_box)

        # Set up the text output field with a vertical scroll bar
        self.text_output = QTextEdit(self)
        self.text_output.setText("") 
        self.text_output.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # Always show the scroll bar
        self.text_output.setLineWrapMode(QTextEdit.NoWrap)
        self.text_output.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text_output.setMinimumWidth(250)
        
        self.text_output.setReadOnly(True)  # Make the text field non-editable
        right_layout.addWidget(self.text_output)

        # Add elements with "open" / "closed" labels
        self.status_layout = QVBoxLayout()

        # Create labels for "open" / "closed"
        # self.labels = [QLabel(f"Item {i+1}: Closed") for i in range(4)]

        # for label in self.labels:
        #     self.status_layout.addWidget(label)  # Add each label to the layout

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
        self.data_thread = DataFetchThread(world, 
                                           first_state=wait_forever, 
                                           states_dict=states_dict)
        self.data_thread.state_update.connect(self.state_update)
        self.combo_box.currentTextChanged.connect(self.data_thread.set_combo_value)
        self.data_thread.start()

        self.on_mouse_move_event = None
        self.update_plot()

    def update_title(self):
        selected = self.combo_box.currentText()
        self.setWindowTitle(f"Selected: {selected} curent_wait={self.world.to_wait_for_process_line:.6g} s")

    def state_update(self, s1, s2):
        # print(s1)
        self.update_title()
        self.text_output.setText(s2)
        textCursor = self.text_output.textCursor()
        textCursor.setPosition(get_arrow_char_index(s2,plus=100))
        color_line(self.text_output, get_arrow_linenum(s2))
        self.text_output.setTextCursor(textCursor)
        keys_hs = ["labjack_heatswitch_adr", "labjack_heatswitch_charcoal", "labjack_heatswitch_pot", "labjack_relay"]
        # mr = most_recent_measurements()
        # for i, key in enumerate(keys_hs):
        #     value = mr[key]
        #     self.labels[i].setText(f"{key} {value}")
        self.update_plot()

    def update_plot(self):
        dataset = self.dataset
        if self.on_mouse_move_event is None:
            xloc_for_vals = None
        else:
            xloc_for_vals = self.on_mouse_move_event.xdata
        plot_dataset(dataset, self.ax, xloc_for_vals)
        self.figure.tight_layout()
        self.canvas.draw()

    def mpl_on_mouse_move(self, event):
        self.on_mouse_move_event=event



def main():
    with meas.run() as datasaver:
        world = StationWorld(station=st)

        global datasaver_global
        datasaver_global = datasaver
        world.datasaver = datasaver

        states_list = [wait_forever, wait_forever2, switch_to_wait_forever_test, 
                    warmup_300K, full_cycle_one_state,
                    ready_for_cooldown, open_adr_heatswitch, set_relay_to_ramp]
        states_dict = {state.name(): state for state in states_list}
        world._update(wait_forever)
        dataset = datasaver.dataset

        # Initialize the application and show the window
        app = QApplication(sys.argv)
        window = MyApp(world, dataset, states_dict)
        window.show()
        sys.exit(app.exec_())

if __name__ == "__main__":
    main()
