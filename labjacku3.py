import qcodes
import u3
import time


class LabjackU3(qcodes.Instrument):
    def __init__(self, name):
        super().__init__(name)
        self.lj = u3.U3() # Opens first found u3 over USB

        self.add_parameter("relay",
                           set_cmd=self.set_relay,
                           val_mapping={"CONTROL":"CONTROL", "RAMP":"RAMP", "UNKNOWN":"UNKNOWN"},
                           initial_value="UNKNOWN",
                           )
        
        self.add_parameter("kepco_voltage",
                           get_cmd=self.get_kepco_voltage,
                           unit="V")
        self.add_parameter("kepco_current",
                    get_cmd=self.get_kepco_current,
                    unit="A")
        
        self.add_parameter("pot_hs",
                           set_cmd=self.pot_hs_control,
                           initial_value="UNKNOWN",
                           )
        
    def get_idn(self) -> dict[str, str | int | None]:
        return "a labjack u3"

    def get_kepco_voltage(self):
        return self.lj.getAIN(0)*2

    def get_kepco_current(self):
        return self.lj.getAIN(2)*2

    def set_relay(self, x):
        if x == "CONTROL":
            self.setRelayToControl()
        elif x == "RAMP":
            self.setRelayToRamp()


    def setDACVoltage(self, dac_channel, voltage):
        dac_value = int(voltage * 255/4.95)
        if dac_channel == 0:
            self.lj.getFeedback(u3.DAC0_8(dac_value))
        elif dac_channel == 1:
            self.lj.getFeedback(u3.DAC1_8(dac_value))
        else:
            print('Error: Not a channel')

    def setRelayControl(self, io_channel):
        '''Turn on digital io channel for 2 seconds then turn back off to switch latching relay '''
        
        self.setDigIOState(io_channel=io_channel, state='high')
        time.sleep(0.2)
        self.setDigIOState(io_channel=io_channel, state='low')
        time.sleep(0.5)
        
    def setRelayToRamp(self, io_channel=4):
        '''Switch relay to ramp mode. Default assumes ramp setting is on io=4.'''
        
        self.setRelayControl(io_channel)
        
    def setRelayToControl(self, io_channel=5):
        '''Switch relay to control mode. Default assumes control setting is on io=5.'''
        
        self.setRelayControl(io_channel)

    def setDigIOState(self, io_channel, state):
        '''Set the state of a Digital IO Channel '''
        
        if state == 'high':
            self.lj.getFeedback(u3.BitStateWrite(io_channel, 1))   # Set IO channel to high
        elif state == 'low':
            self.lj.getFeedback(u3.BitStateWrite(io_channel, 0))   # Set IO channel to low
        else:
            print('Error: Direction not valid')

    def pulse_digital_state(self,ch, sleep_s=0.1):
        self.setDigIOState(ch, "high")
        time.sleep(sleep_s)
        self.setDigIOState(ch, "low")

    def open_pot_hs(self):
        self.pulse_digital_state(12)

    def close_pot_hs(self):
        self.pulse_digital_state(11)

    def pot_hs_control(self, x):
        if x =="OPEN":
            self.open_pot_hs()
        elif x=="CLOSE":
            self.close_pot_hs()
        elif x=="UNKNOWN":
            pass
        else:
            raise ValueError(x)