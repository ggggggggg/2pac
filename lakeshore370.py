from typing import Any, ClassVar

from pyvisa.highlevel import ResourceManager
from pyvisa.resources.messagebased import MessageBasedResource
import qcodes.validators as vals
from lakeshore370_base import (
    BaseOutput,
    BaseSensorChannel,
    LakeshoreBase,
)
from qcodes.instrument import InstrumentChannel
from qcodes.parameters import Group, GroupParameter
from bisect import bisect


# There are 16 sensors channels (a.k.a. measurement inputs) in Model 372
_n_channels = 16


class LakeshoreModel370Output(InstrumentChannel):
    """An InstrumentChannel for control outputs (heaters) of Lakeshore Model 372"""

    MODES: ClassVar[dict[str, int]] = {
        "closed": 1,
        "zone": 2,
        "open_loop": 3,
        "off": 4,
    }
    POLARITIES: ClassVar[dict[str, int]] = {"unipolar": 0, "bipolar": 1}
    RANGES: ClassVar[dict[str, int]] = {
        "off": 0,
        "31.6uA": 1,
        "100uA": 2,
        "316uA": 3,
        "1mA": 4,
        "3.16mA": 5,
        "10mA": 6,
        "31.6mA": 7,
        "100mA": 8,
    }

    _input_channel_parameter_kwargs: ClassVar[dict[str, Any]] = {
        "get_parser": int,
        "vals": vals.Numbers(1, _n_channels),
    }

    def __init__(self, parent: "LakeshoreModel370", output_name: str) -> None:
        super().__init__(parent, output_name)

        self.add_parameter("out",
                           get_cmd="HTR?",
                           set_cmd="MOUT {}",
                           get_parser=float)
        self.add_parameter("mode",
                           val_mapping=self.MODES,
                           get_cmd="CMODE?",
                           set_cmd=f"CMODE {{}}")
        
        self.add_parameter("range",
                           val_mapping = self.RANGES,
                           get_cmd="HTRRNG?",
                           set_cmd="HTRRNG {}")

        # Add more parameters for CSET command
        # and redefine the corresponding group
        self.add_parameter(
            "channel",
            label="channel to control",
            vals=vals.Numbers(1, _n_channels),
            get_parser=int,
            parameter_class=GroupParameter,
        )
        self.add_parameter(
            "use_filter",
            label="Use filter for readings",
            docstring="Specifies controlling on unfiltered or filtered readings",
            val_mapping={True: 1, False: 0},
            parameter_class=GroupParameter,
        )
        self.add_parameter(
            "delay",
            label="Delay",
            unit="s",
            docstring="Delay in seconds for setpoint change during Autoscanning",
            vals=vals.Ints(0, 255),
            get_parser=int,
            parameter_class=GroupParameter,
        )
        self.output_group = Group(
            [
                self.channel,
                self.use_filter,
                self.delay,
            ],
            set_cmd=f"CSET {{channel}}, {{use_filter}}, {{delay}}, 1, 8, 50",
            get_cmd=f"CSET?",
        )
        self.add_parameter('P',
                               label='Proportional (closed-loop)',
                               docstring='The value for closed control loop '
                                         'Proportional (gain)',
                               vals=vals.Numbers(0, 1000),
                               get_parser=float,
                               parameter_class=GroupParameter)
        self.add_parameter('I',
                            label='Integral (closed-loop)',
                            docstring='The value for closed control loop '
                                        'Integral (reset)',
                            vals=vals.Numbers(0, 1000),
                            get_parser=float,
                            parameter_class=GroupParameter)
        self.add_parameter('D',
                            label='Derivative (closed-loop)',
                            docstring='The value for closed control loop '
                                        'Derivative (rate)',
                            vals=vals.Numbers(0, 1000),
                            get_parser=float,
                            parameter_class=GroupParameter)
        self.pid_group = Group([self.P, self.I, self.D],
                                set_cmd=f'PID {{P}}, {{I}}, {{D}}',
                                get_cmd=f'PID?')
        
        self.add_parameter(
            "setpoint",
            label="Setpoint value (in sensor units)",
            docstring="The value of the setpoint in the "
            "preferred units of the control loop",
            unit="K",
            vals=vals.Numbers(0, 300),
            get_parser=float,
            set_cmd=f"SETP {{}}",
            get_cmd=f"SETP?",
        )

        self.add_parameter('wait_cycle_time',
                           set_cmd=None,
                           get_cmd=None,
                           vals=vals.Numbers(0, 100),
                           label='Waiting cycle time',
                           docstring='Time between two readings when waiting '
                                     'for temperature to equilibrate',
                           unit='s')
        self.wait_cycle_time(0.1)

        self.add_parameter('wait_tolerance',
                           set_cmd=None,
                           get_cmd=None,
                           vals=vals.Numbers(0, 100),
                           label='Waiting tolerance',
                           docstring='Acceptable tolerance when waiting for '
                                     'temperature to equilibrate',
                           unit='')
        self.wait_tolerance(0.1)

        self.add_parameter('wait_equilibration_time',
                           set_cmd=None,
                           get_cmd=None,
                           vals=vals.Numbers(0, 100),
                           label='Waiting equilibration time',
                           docstring='Duration during which temperature has to '
                                     'be within tolerance',
                           unit='s')
        self.wait_equilibration_time(0.5)

        self.add_parameter('blocking_t',
                           label='Setpoint value with blocking until it is '
                                 'reached',
                           docstring='Sets the setpoint value, and input '
                                     'range, and waits until it is reached. '
                                     'Added for compatibility with Loop. Note '
                                     'that if the setpoint value is in '
                                     'a different range, this function may '
                                     'wait forever because that setpoint '
                                     'cannot be reached within the current '
                                     'range.',
                           vals=vals.Numbers(0, 400),
                           set_cmd=self._set_blocking_t,
                           snapshot_exclude=True)
    def _set_blocking_t(self, temperature: float) -> None:
        self.set_range_from_temperature(temperature)
        self.setpoint(temperature)
        self.wait_until_set_point_reached()
        
    def set_range_from_temperature(self, temperature: float) -> str:
        """
        Sets the output range of this given heater from a given temperature.

        The output range is determined by the limits given through the parameter
        `range_limits`. The output range is used for temperatures between
        the limits `range_limits[i-1]` and `range_limits[i]`; that is
        `range_limits` is the upper limit for using a certain heater current.

        Args:
            temperature:
                temperature to set the range from

        Returns:
            the value of the resulting `output_range`, that is also available
            from the `output_range` parameter itself
        """
        if self.range_limits.get_latest() is None:
            raise RuntimeError('Error when calling set_range_from_temperature: '
                               'You must specify the output range limits '
                               'before automatically setting the range '
                               '(e.g. inst.range_limits([0.021, 0.1, 0.2, '
                               '1.1, 2, 4, 8]))')
        range_limits = self.range_limits.get_latest()
        i = bisect(range_limits, temperature)
        # if temperature is larger than the highest range, then bisect returns
        # an index that is +1 from the needed index, hence we need to take
        # care of this corner case here:
        i = min(i, len(range_limits) - 1)
        # there is a `+1` because `self.RANGES` includes `'off'` as the first
        # value.
        orange = self.INVERSE_RANGES[i+1] # this is `output range` not the fruit
        self.log.debug(f'setting output range from temperature '
                       f'({temperature} K) to {orange}.')
        self.output_range(orange)
        return self.output_range()




class LakeshoreModel370Channel(BaseSensorChannel):
    """
    An InstrumentChannel representing a single sensor on a Lakeshore Model 372.

    """

    SENSOR_STATUSES: ClassVar[dict[int, str]] = {
        0: "OK",
        1: "CS OVL",
        2: "VCM OVL",
        4: "VMIX OVL",
        8: "VDIF OVL",
        16: "R. OVER",
        32: "R. UNDER",
        64: "T. OVER",
        128: "T. UNDER",
    }

    def __init__(self, parent: "LakeshoreModel370", name: str, channel: str):
        super().__init__(parent, name, channel)

        # Parameters related to Input Channel Parameter Command (INSET)
        self.add_parameter(
            "enabled",
            label="Enabled",
            docstring="Specifies whether the input/channel is "
            "enabled or disabled. At least one "
            "measurement input channel must be "
            "enabled. If all are configured to "
            "disabled, channel 1 will change to "
            "enabled.",
            val_mapping={True: 1, False: 0},
            parameter_class=GroupParameter,
        )
        self.add_parameter(
            "dwell",
            label="Dwell",
            docstring="Specifies a value for the autoscanning dwell time.",
            unit="s",
            get_parser=int,
            vals=vals.Numbers(1, 200),
            parameter_class=GroupParameter,
        )
        self.add_parameter(
            "pause",
            label="Change pause time",
            docstring="Specifies a value for the change pause time",
            unit="s",
            get_parser=int,
            vals=vals.Numbers(3, 200),
            parameter_class=GroupParameter,
        )
        self.add_parameter(
            "curve_number",
            label="Curve",
            docstring="Specifies which curve the channel uses: "
            "0 = no curve, 1 to 59 = standard/user "
            "curves. Do not change this parameter "
            "unless you know what you are doing.",
            get_parser=int,
            vals=vals.Numbers(0, 59),
            parameter_class=GroupParameter,
        )
        self.add_parameter(
            "temperature_coefficient",
            label="Change pause time",
            docstring="Sets the temperature coefficient that "
            "will be used for temperature control if "
            "no curve is selected (negative or "
            "positive). Do not change this parameter "
            "unless you know what you are doing.",
            val_mapping={"negative": 1, "positive": 2},
            parameter_class=GroupParameter,
        )
        self.output_group = Group(
            [
                self.enabled,
                self.dwell,
                self.pause,
                self.curve_number,
                self.temperature_coefficient,
            ],
            set_cmd=f"INSET {self._channel}, "
            f"{{enabled}}, {{dwell}}, {{pause}}, "
            f"{{curve_number}}, "
            f"{{temperature_coefficient}}",
            get_cmd=f"INSET? {self._channel}",
        )

        # Parameters related to Input Setup Command (INTYPE)
        # self.add_parameter(
        #     "excitation_mode",
        #     label="Excitation mode",
        #     docstring="Specifies excitation mode",
        #     val_mapping={"voltage": 0, "current": 1},
        #     parameter_class=GroupParameter,
        # )
        # # The allowed values for this parameter change based on the value of
        # # the 'excitation_mode' parameter. Moreover, there is a table in the
        # # manual that assigns the numbers to particular voltage/current ranges.
        # # Once this parameter is heavily used, it can be implemented properly
        # # (i.e. using val_mapping, and that val_mapping is updated based on the
        # # value of 'excitation_mode'). At the moment, this parameter is added
        # # only because it is a part of a group.
        # self.add_parameter(
        #     "excitation_range_number",
        #     label="Excitation range number",
        #     docstring="Specifies excitation range number "
        #     "(1-12 for voltage excitation, 1-22 for "
        #     "current excitation); refer to the manual "
        #     "for the table of ranges",
        #     get_parser=int,
        #     vals=vals.Numbers(1, 22),
        #     parameter_class=GroupParameter,
        # )
        # self.add_parameter(
        #     "auto_range",
        #     label="Auto range",
        #     docstring="Specifies auto range setting",
        #     val_mapping={"off": 0, "current": 1},
        #     parameter_class=GroupParameter,
        # )
        # self.add_parameter(
        #     "range",
        #     label="Range",
        #     val_mapping={
        #         "2.0 mOhm": 1,
        #         "6.32 mOhm": 2,
        #         "20.0 mOhm": 3,
        #         "63.2 mOhm": 4,
        #         "200 mOhm": 5,
        #         "632 mOhm": 6,
        #         "2.00 Ohm": 7,
        #         "6.32 Ohm": 8,
        #         "20.0 Ohm": 9,
        #         "63.2 Ohm": 10,
        #         "200 Ohm": 11,
        #         "632 Ohm": 12,
        #         "2.00 kOhm": 13,
        #         "6.32 kOhm": 14,
        #         "20.0 kOhm": 15,
        #         "63.2 kOhm": 16,
        #         "200 kOhm": 17,
        #         "632 kOhm": 18,
        #         "2.0 MOhm": 19,
        #         "6.32 MOhm": 20,
        #         "20.0 MOhm": 21,
        #         "63.2 MOhm": 22,
        #     },
        #     parameter_class=GroupParameter,
        # )
        # self.add_parameter(
        #     "current_source_shunted",
        #     label="Current source shunt",
        #     docstring="Current source either not shunted "
        #     "(excitation on), or shunted "
        #     "(excitation off)",
        #     val_mapping={False: 0, True: 1},
        #     parameter_class=GroupParameter,
        # )
        # self.add_parameter(
        #     "units",
        #     label="Preferred units",
        #     docstring="Specifies the preferred units parameter "
        #     "for sensor readings and for the control "
        #     "setpoint (kelvin or ohms)",
        #     val_mapping={"kelvin": 1, "ohms": 2},
        #     parameter_class=GroupParameter,
        # )
        # self.output_group = Group(
        #     [
        #         self.excitation_mode,
        #         self.excitation_range_number,
        #         self.auto_range,
        #         self.range,
        #         self.current_source_shunted,
        #         self.units,
        #     ],
        #     set_cmd=f"INTYPE {self._channel}, "
        #     f"{{excitation_mode}}, "
        #     f"{{excitation_range_number}}, "
        #     f"{{auto_range}}, {{range}}, "
        #     f"{{current_source_shunted}}, "
        #     f"{{units}}",
        #     get_cmd=f"INTYPE? {self._channel}",
        # )


class LakeshoreModel370(LakeshoreBase):
    """
    QCoDeS driver for Lakeshore Model 370 Temperature Controller.

    Note that interaction with the control input (referred to as 'A' in the
    Computer Interface Operation section of the manual) is not implemented.
    """

    channel_name_command: ClassVar[dict[str, str]] = {
        f"ch{i:02}": str(i) for i in range(1, 1 + _n_channels)
    }
    input_channel_parameter_values_to_channel_name_on_instrument: ClassVar[
        dict[int, str]
    ] = {i: f"ch{i:02}" for i in range(1, 1 + _n_channels)}

    CHANNEL_CLASS = LakeshoreModel370Channel

    def __init__(self, name: str, address: str, **kwargs: Any) -> None:
        super().__init__(name, address, **kwargs)

        self.add_submodule("heater", LakeshoreModel370Output(self, output_name="heater"))

    def _open_resource(self, address: str, visalib: str | None) -> tuple[MessageBasedResource, str, ResourceManager]:
        # first call the existing _open_resource method
        resource, visabackend, resource_manager = super()._open_resource(address, visalib)
        # then set the odd communication settings that can't be passed by argument with the current api
        from pyvisa import constants
        resource.parity = constants.Parity.odd
        resource.data_bits = 7
        return resource, visabackend, resource_manager
    