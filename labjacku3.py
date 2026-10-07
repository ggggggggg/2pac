import qcodes
import u3
import time
import threading
from qcodes.validators import Enum, Numbers



class LabjackU3(qcodes.Instrument):
    def __init__(self, name):
        super().__init__(name)
        # Re-entrant lock serializing ALL USB transactions with the U3. The data
        # thread (analog reads) and the GUI heat-switch thread (relay pulses)
        # share one handle; unsynchronized access can corrupt a transaction.
        self._io_lock = threading.RLock()
        self.lj = u3.U3() # Opens first found u3 over USB

        self.add_parameter("relay",
                           set_cmd=self.set_relay,
                           vals=Enum("CONTROL", "RAMP", "UNKNOWN"),
                           initial_value="UNKNOWN",
                           )
        self.add_parameter("kepco_voltage",
                           get_cmd=self.get_kepco_voltage,
                           vals=Numbers(-20,20),
                           unit="V")
        self.add_parameter("kepco_current",
                    get_cmd=self.get_kepco_current,
                    vals = Numbers(-10,10),
                    unit="A")
        self.add_parameter("he3_pressure",
                    get_cmd=self.get_he3_pressure,
                    vals = Numbers(0,10),
                    unit="bar")
        self.add_parameter("vac_can_pressure_torr",
                    get_cmd=self.get_vac_can_pressure_torr,
                    vals = Numbers(1e-7, 2000),
                    unit="Torr")
        self.add_parameter("heatswitch_pot",
                           set_cmd=self._pot_hs_control,
                           initial_value="UNKNOWN",
                           vals = Enum("OPEN","CLOSED","UNKNOWN")
                           )
        self.add_parameter("heatswitch_adr",
                           set_cmd=self._adr_hs_control,
                           initial_value="UNKNOWN",
                           vals = Enum("OPEN","CLOSED","UNKNOWN")
                           )
        self.add_parameter("heatswitch_charcoal",
                           set_cmd=self._charcoal_hs_control,
                           initial_value="UNKNOWN",
                           vals = Enum("OPEN","CLOSED","UNKNOWN")
                           )
        
    def get_idn(self) -> dict[str, str | int | None]:
        return "a labjack u3"

    def _ain(self, ch):
        with self._io_lock:
            return self.lj.getAIN(ch)

    def get_kepco_voltage(self):
        return self._ain(0)*2

    def get_kepco_current(self):
        return self._ain(2)
    
    def get_he3_pressure(self, VDC_TO_PSIA=50):
        # Omega PX409-250 strain gauge output full range = 0-5 Vdc for 0-250 psi abs
        PSI_TO_BAR = 0.0689476
        return self._ain(1)*VDC_TO_PSIA*PSI_TO_BAR

    def get_vac_can_pressure_torr(self):
        # Kurt J. Lesker KJL27580LL (Convectron 275 series Pirani gauge):
        # Connected to AIN3 (pin 5 analog out +, pin 8 analog out - to GND)
        # Formula: V = log10(P) + 5  =>  P = 10^(V - 5) Torr
        v = self._ain(3)
        if v <= 0.05:
            return 1e-5
        return float(10.0 ** (v - 5.0))

    def set_relay(self, x):
        with self._io_lock:
            if x == "CONTROL":
                self.setRelayToControl()
            elif x == "RAMP":
                self.setRelayToRamp()


    def setDACVoltage(self, dac_channel, voltage):
        dac_value = int(voltage * 255/4.95)
        with self._io_lock:
            if dac_channel == 0:
                self.lj.getFeedback(u3.DAC0_8(dac_value))
            elif dac_channel == 1:
                self.lj.getFeedback(u3.DAC1_8(dac_value))
            else:
                print('Error: Not a channel')

    def setRelayControl(self, io_channel):
        '''Turn on digital io channel for 2 seconds then turn back off to switch latching relay '''
        
        with self._io_lock:
            self.setDigIOState(io_channel=io_channel, state='high')
            time.sleep(0.2)
            self.setDigIOState(io_channel=io_channel, state='low')
            time.sleep(0.5)
        
    def setRelayToRamp(self, io_channel=16):
        '''Switch relay to ramp mode. Default assumes ramp setting is on io=4.'''
        
        self.setRelayControl(io_channel)
        
    def setRelayToControl(self, io_channel=18):
        '''Switch relay to control mode. Default assumes control setting is on io=5.'''
        
        self.setRelayControl(io_channel)

    def setDigIOState(self, io_channel, state):
        '''Set the state of a Digital IO Channel '''
        
        with self._io_lock:
            if state == 'high':
                self.lj.getFeedback(u3.BitStateWrite(io_channel, 1))   # Set IO channel to high
            elif state == 'low':
                self.lj.getFeedback(u3.BitStateWrite(io_channel, 0))   # Set IO channel to low
            else:
                print('Error: Direction not valid')

    def pulse_digital_state(self,ch, sleep_s=0.1):
        # Hold the lock for the whole pulse so the line is never left high
        # by an interleaved transaction from another thread.
        with self._io_lock:
            self.setDigIOState(ch, "high")
            time.sleep(sleep_s)
            self.setDigIOState(ch, "low")

    def _pot_hs_control(self, x):
        if x =="OPEN":
            self.pulse_digital_state(12)
        elif x=="CLOSED":
            self.pulse_digital_state(11)
        elif x=="UNKNOWN":
            pass
        else:
            raise ValueError(x)

    def _adr_hs_control(self, x):
        if x =="OPEN":
            self.pulse_digital_state(8)
        elif x=="CLOSED":
            self.pulse_digital_state(10)
        elif x=="UNKNOWN":
            pass
        else:
            raise ValueError(x)
        
    def _charcoal_hs_control(self, x):
        if x =="OPEN":
            self.pulse_digital_state(19)
        elif x=="CLOSED":
            self.pulse_digital_state(17)
        elif x=="UNKNOWN":
            pass
        else:
            raise ValueError(x)
        

        
