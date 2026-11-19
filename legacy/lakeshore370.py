from typing import Any, ClassVar

from pyvisa.highlevel import ResourceManager
from pyvisa.resources.messagebased import MessageBasedResource
import qcodes.validators as vals
try:
    from .lakeshore370_base import (
        BaseOutput,
        BaseSensorChannel,
        LakeshoreBase,
    )
except ImportError:
    from lakeshore370_base import (
        BaseOutput,
        BaseSensorChannel,
        LakeshoreBase,
    )
from qcodes.instrument import InstrumentChannel
from qcodes.parameters import Group, GroupParameter


# There are 16 sensor channels (measurement inputs) in Model 370
_n_channels = 16


class LakeshoreModel370Output(InstrumentChannel):
    """An InstrumentChannel for control outputs (heaters) of Lakeshore Model 370"""

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
                           get_parser=float,
                           unit="%")
        self.add_parameter("mode",
                           val_mapping=self.MODES,
                           get_cmd="CMODE?",
                           set_cmd="CMODE {}")
        
        self.add_parameter("range",
                           val_mapping=self.RANGES,
                           get_cmd="HTRRNG?",
                           set_cmd="HTRRNG {}")

        # Add parameters for CSET command
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
            set_cmd="CSET {channel}, {use_filter}, 1, {delay}, 1, 4, 100",
            get_cmd="CSET?",
        )
        self.add_parameter('P',
                           label='Proportional (closed-loop)',
                           docstring='The value for closed control loop Proportional (gain)',
                           vals=vals.Numbers(0, 1000),
                           get_parser=float,
                           parameter_class=GroupParameter)
        self.add_parameter('I',
                           label='Integral (closed-loop)',
                           docstring='The value for closed control loop Integral (reset)',
                           vals=vals.Numbers(0, 1000),
                           get_parser=float,
                           parameter_class=GroupParameter)
        self.add_parameter('D',
                           label='Derivative (closed-loop)',
                           docstring='The value for closed control loop Derivative (rate)',
                           vals=vals.Numbers(0, 1000),
                           get_parser=float,
                           parameter_class=GroupParameter)
        self.pid_group = Group([self.P, self.I, self.D],
                               set_cmd='PID {P}, {I}, {D}',
                               get_cmd='PID?')
        
        self.add_parameter(
            "setpoint",
            label="Setpoint value (in sensor units)",
            docstring="The value of the setpoint in the preferred units of the control loop",
            unit="K",
            vals=vals.Numbers(0, 300),
            get_parser=float,
            set_cmd="SETP {}",
            get_cmd="SETP?",
        )

    def setup_control(self, channel: int = 4, p: float = 0.05, i: float = 12.0, d: float = 0.0) -> None:
        """Configure Lake Shore 370 closed loop control channel (Kelvin units) and PID gains."""
        self.write(f"CSET {int(channel)}, 1, 1, 1, 1, 4, 100")
        self.write(f"PID {float(p)}, {float(i)}, {float(d)}")

        self.add_parameter('wait_cycle_time',
                           set_cmd=None,
                           get_cmd=None,
                           initial_value=0.1,
                           vals=vals.Numbers(0, 1),
                           label='Wait cycle time',
                           docstring='Time between readings in wait_until')


class LakeshoreModel370Channel(BaseSensorChannel):
    """
    Sensor channel for Lakeshore Model 370.
    """
    pass


class LakeshoreModel370(LakeshoreBase):
    """
    QCoDeS driver for Lakeshore Model 370 Temperature Controller.
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
        resource, visabackend, resource_manager = super()._open_resource(address, visalib)
        from pyvisa import constants
        resource.parity = constants.Parity.odd
        resource.data_bits = 7
        return resource, visabackend, resource_manager