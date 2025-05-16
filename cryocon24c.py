from qcodes import VisaInstrument
from qcodes.utils.validators import Numbers, Enum, Ints, Bool


# get parsers
def floatk(x):
    if x[-1]=="K":
        return float(x[:-1])

def strip(x):
    return x.strip()

def float_perc(x):
    if x[-1]  == "%":
        return float(strip(x[:-1]))

class Cryocon24C(VisaInstrument):
    """
    Driver for the Cryo-con Model 24 C temperature controller.
    """
    def __init__(self, name, address, terminator='\r\n', **kwargs):
        super().__init__(name, address, terminator=terminator, **kwargs)
        self.visa_handle.query_delay = 0.1 # cryocon has been unreliable on reruning temperatures
        # maybe a delay will help?
        # first pass says it doesn't help much

        for channel in ['A', 'B', 'C', 'D']:
            c = 'ch{}_'.format(channel)

            self.add_parameter(c + 'temperature',
                               get_cmd='input? {}'.format(channel),
                               get_parser=float)

            self.add_parameter(c + 'units',
                               get_cmd='input {}:units?'.format(channel),
                               get_parser=str.upper,
                               set_cmd='input {}:units {{}}'.format(channel),
                               vals=Enum('K', 'C', 'F', 'S'))

            self.add_parameter(c + 'sensor',
                               get_cmd='input {}:sensor?'.format(channel),
                               get_parser=int,
                               set_cmd='input {}:sensor {{}}'.format(channel),
                               vals=Ints(0))

            # self.add_parameter(c + 'sensor_power',
            #                    get_cmd='input {}:sensp?'.format(channel),
            #                    get_parser=float)

            self.add_parameter(c + 'min',
                               get_cmd='input? {}:min'.format(channel),
                               get_parser=float)

            self.add_parameter(c + 'max',
                               get_cmd='input? {}:max'.format(channel),
                               get_parser=float)

            self.add_parameter(c + 'variance',
                               get_cmd='input? {}:variance'.format(channel),
                               get_parser=float)

            self.add_parameter(c + 'slope',
                               get_cmd='input? {}:slope'.format(channel),
                               get_parser=float)

            self.add_parameter(c + 'offset',
                               get_cmd='input? {}:offset'.format(channel),
                               get_parser=float)



        # TODO: check case of returned strings
        self.add_parameter('control_enabled',
                           get_cmd='control?',
                           set_cmd=self._set_control,
                           get_parser=self._get_control_parser,
                           vals=Bool())

        def make_set_cmd_source(loop):
            # to avoid annoying loop capture rules
            return lambda x: self.ask((f"loop {loop}:source {{}}").format(x))

        def make_set_cmd_setpoint(loop):
            # to avoid annoying loop capture rules
            return lambda x: self.ask((f"loop {loop}:setpt {{}}").format(x))

        for loop in [1, 2, 3, 4]:
            l = 'loop{}_'.format(loop)

            self.add_parameter(l + 'source',
                            get_cmd='loop {}:source?'.format(loop),
                            get_parser=str.upper,
                        #    set_cmd='loop {}:source {{}}'.format(loop),
                        # the cryocon returns a response to set commands, so we need to use ask
                            set_cmd=make_set_cmd_source(loop),
                            vals=Enum('A', 'B', 'C', 'D'))

            self.add_parameter(l + 'setpoint',
                            get_cmd='loop {loop}:setpt?',
                            get_parser=floatk,
                        #    set_cmd='loop {}:setpt {{}}'.format(loop),
                        # the cryocon returns a response to set commands, so we need to use ask
                            set_cmd=make_set_cmd_setpoint(loop),
                            vals=Numbers(), 
                            unit = "K")

            self.add_parameter(l + 'type',
                               get_cmd=f'loop {loop}:type?',
                               set_cmd=f'loop {loop}:type {{}}',
                               get_parser=strip,
                               val_mapping={'off': 'OFF',
                                            'manual': 'MAN',
                                            'PID': 'PID',
                                            'table': 'TABLE',
                                            'ramp': 'RAMPP'})

            if loop in [1,2]:
                mapping = {'high': 'HI', 'medium': 'MID', 'low': 'LOW'}

            if loop in [3,4]:
                mapping = {"5V":"5V","10V":"10V"}

            self.add_parameter(l + 'range',
                               get_cmd=f'loop {loop}:range?',
                               set_cmd=f'loop {loop}:range {{}}',
                               get_parser=strip,
                               val_mapping=mapping)

            # self.add_parameter(l + 'is_ramping',
            #                    get_cmd=f'loop {loop}:ramp?',
            #                    get_parser=strip,
            #                    val_mapping=on_off_map)

            self.add_parameter(l + 'ramp_rate',
                               get_cmd=f'loop {loop}:rate?',
                               get_parser=float,
                               set_cmd=f'loop {loop}:rate {{}}',
                               vals=Numbers(0, 100),
                               unit='units/min')

            self.add_parameter(l + 'P',
                               get_cmd=f'loop {loop}:pgain?',
                               get_parser=float,
                               set_cmd=f'loop {loop}:pgain {{}}',
                               vals=Numbers(0, 1000),
                               unit='-')

            self.add_parameter(l + 'I',
                               get_cmd='loop {}:igain?'.format(loop),
                               get_parser=float,
                               set_cmd='loop {}:igain {{}}'.format(loop),
                               vals=Numbers(0, 1000),
                               unit='s')

            self.add_parameter(l + 'D',
                               get_cmd='loop {}:dgain?'.format(loop),
                               get_parser=float,
                               set_cmd='loop {}:dgain {{}}'.format(loop),
                               vals=Numbers(0, 1000),
                               unit='1/s')

            self.add_parameter(l + 'manual_power',
                               get_cmd=f'loop {loop}:pman?',
                               get_parser=float,
                               set_cmd='loop {}:pman {{}}'.format(loop),
                               vals=Numbers(0, 100),
                               unit='%')

            self.add_parameter(l + 'output_power',
                               get_cmd=f'loop {loop}:outp?',
                               get_parser=float,
                               unit='%')

            self.add_parameter(l + 'read_heater',
                               get_cmd=f'loop {loop}:htrread?',
                               get_parser=float_perc,
                               unit='%')

            self.add_parameter(l + 'max_power',
                               get_cmd=f'loop {loop}:maxp?',
                               get_parser=float,
                               set_cmd='loop {}:maxp {{}}'.format(loop),
                               vals=Numbers(0, 100),
                               unit='%')
            

    def _set_control(self, x):
        if x == True:
            self.ask("control")
        elif x == False:
            self.ask("stop")
        else:
            raise ValueError()
        
    def _get_control_parser(self, x):
        return {"ON":True, "OFF":False}[x]