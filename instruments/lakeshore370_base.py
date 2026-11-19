import time
import threading
from bisect import bisect
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

from qcodes import validators as vals
from qcodes.instrument import ChannelList, InstrumentChannel, VisaInstrument
from qcodes.parameters import Group, GroupParameter


class BaseOutput(InstrumentChannel):
    """
    Base class for the outputs of Lakeshore temperature controllers

    Args:
        parent
            instrument that this channel belongs to
        output_name
            name of this output
        output_index
            identifier for this output that is used in VISA commands of the
            instrument
        has_pid
            if True, then the output supports closed loop control,
            hence it will have three parameters to set it up: 'P', 'I', and 'D'
    """

    MODES: ClassVar[dict[str, int]] = {}
    RANGES: ClassVar[dict[str, int]] = {}

    _input_channel_parameter_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(
            self,
            parent: "LakeshoreBase",
            output_name: str,
            output_index: int,
            has_pid: bool = True):
        super().__init__(parent, output_name)

        self.INVERSE_RANGES: dict[int, str] = {v: k for k, v in self.RANGES.items()}

        self._has_pid = has_pid
        self._output_index = output_index

        # self.add_parameter('mode',
        #                    label='Control mode',
        #                    docstring='Specifies the control mode',
        #                    val_mapping=self.MODES,
        #                    parameter_class=GroupParameter)
        # self.add_parameter('input_channel',
        #                    label='Input channel',
        #                    docstring='Specifies which measurement input to '
        #                              'control from (note that only '
        #                              'measurement inputs are available)',
        #                    parameter_class=GroupParameter,
        #                    **self._input_channel_parameter_kwargs)
        # self.add_parameter('powerup_enable',
        #                    label='Power-up enable on/off',
        #                    docstring='Specifies whether the output remains on '
        #                              'or shuts off after power cycle.',
        #                    val_mapping={True: 1, False: 0},
        #                    parameter_class=GroupParameter)
        # self.output_group = Group([self.mode, self.input_channel,
        #                            self.powerup_enable],
        #                           set_cmd=f'OUTMODE {output_index}, {{mode}}, '
        #                                   f'{{input_channel}}, '
        #                                   f'{{powerup_enable}}',
        #                           get_cmd=f'OUTMODE? {output_index}')

        # Parameters for Closed Loop PID Parameter Command
        if self._has_pid:
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
                                   set_cmd=f'PID {output_index}, '
                                           f'{{P}}, {{I}}, {{D}}',
                                   get_cmd=f'PID? {output_index}')

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

    def set_setpoint_and_range(self, temperature: float) -> None:
        """
        Sets the range from the given temperature, and then sets the setpoint
        to this given temperature.

        Note that the preferred units of the heater output are expected to be
        kelvin.

        Args:
            temperature: temperature in K
        """
        self.set_range_from_temperature(temperature)
        self.setpoint(temperature)

    def wait_until_set_point_reached(
            self,
            wait_cycle_time: Optional[float] = None,
            wait_tolerance: Optional[float] = None,
            wait_equilibration_time: Optional[float] = None
    ) -> None:
        """
        Monitors heater input channel until reading is within tolerance of setpoint.
        """
        pass


class BaseSensorChannel(InstrumentChannel):
    """
    Base class for sensor channels of Lakeshore temperature controllers.
    """

    # A dictionary of sensor statuses that assigns a string representation of
    # the status to a status bit weighting (e.g. {4: 'VMIX OVL'})
    SENSOR_STATUSES: ClassVar[dict[int, str]] = {}

    def __init__(
            self,
            parent: "LakeshoreBase",
            name: str,
            channel: str):
        super().__init__(parent, name)

        self._channel = channel  # Channel on the temperature controller

        # Add the various channel parameters

        self.add_parameter('temperature',
                           get_cmd=f'RDGK? {self._channel}',
                           get_parser=float,
                           label='Temperature',
                           unit='K')

        # self.add_parameter('t_limit',
        #                    get_cmd=f'TLIMIT? {self._channel}',
        #                    set_cmd=f'TLIMIT {self._channel}, {{}}',
        #                    get_parser=float,
        #                    label='Temperature limit',
        #                    docstring='The temperature limit in kelvin for '
        #                              'which to shut down all control outputs '
        #                              'when exceeded. A temperature limit of '
        #                              'zero turns the temperature limit '
        #                              'feature off for the given sensor input.',
        #                    unit='K')

        self.add_parameter('sensor_raw',
                           get_cmd=f'RDGR? {self._channel}',
                           get_parser=float,
                           label='Raw reading',
                           unit='Ohms')

        self.add_parameter('sensor_status',
                           get_cmd=f'RDGST? {self._channel}',
                           get_parser=self._decode_sensor_status,
                           label='Sensor status')

        # self.add_parameter('sensor_name',
        #                    get_cmd=f'INNAME? {self._channel}',
        #                    get_parser=str,
        #                    set_cmd=f'INNAME {self._channel},\"{{}}\"',
        #                    vals=vals.Strings(15),
        #                    label='Sensor name')

    def _decode_sensor_status(self, sum_of_codes: str) -> str:
        """
        Parses the sum of status code according to the `SENSOR_STATUSES` using
        an algorithm defined in `_get_sum_terms` method.

        Args:
            sum_of_codes:
                sum of status codes, it is an integer value in the form of a
                string (e.g. "32"), as returned by the corresponding
                instrument command
        """
        codes = self._get_sum_terms(list(self.SENSOR_STATUSES.keys()),
                                    int(sum_of_codes))
        return ", ".join(self.SENSOR_STATUSES[k] for k in codes)

    @staticmethod
    def _get_sum_terms(available_terms: Sequence[int], number: int) -> list[int]:
        """
        Returns a list of terms which make the given number when summed up

        This method is intended to be used for cases where the given list
        of terms contains powers of 2, which corresponds to status codes
        that an instrument returns. With that said, this method is not
        guaranteed to work for an arbitrary number and an arbitrary list of
        available terms.

        """
        terms_in_number: list[int] = []

        # Sort the list of available_terms from largest to smallest
        terms_left = np.sort(available_terms)[::-1]

        # Get rid of the terms that are bigger than the number because they
        # will obviously will not make it to the returned list; and also get
        # rid of '0' as it will make the loop below infinite
        terms_left = np.array(
            [term for term in terms_left if term <= number and term != 0])

        # Handle the special case of number being 0
        if number == 0:
            terms_left = np.empty(0)
            terms_in_number = [0]

        # Keep subtracting the largest term from `number`, and always update
        # the list of available_terms so that they are always smaller than
        # the current value of `number`, until there are no more available_terms
        # to subtract
        while len(terms_left) > 0:
            term = terms_left[0]
            number -= term
            terms_in_number.append(term)
            terms_left = terms_left[terms_left <= number]

        return terms_in_number


class LakeshoreBase(VisaInstrument):
    """
    Base class for Lakeshore temperature controller drivers.
    """
    # Redefine this in the model-specific class in case you want to use a
    # different class for sensor channels
    CHANNEL_CLASS = BaseSensorChannel

    # This dict has channel name in the driver as keys, and channel "name" that
    # is used in instrument commands as values. For example, if channel called
    # "B" is referred to in instrument commands as '2', then this dictionary
    # will contain {'B': '2'} entry.
    channel_name_command: ClassVar[dict[str, str]] = {}

    input_channel_parameter_values_to_channel_name_on_instrument: ClassVar[
        dict[Any, str]
    ]

    def __init__(
        self,
        name: str,
        address: str,
        terminator: str = "\r\n",
        print_connect_message: bool = True,
        **kwargs: Any,
    ) -> None:
        self._io_lock = threading.RLock()
        super().__init__(name, address, terminator=terminator, **kwargs)

        # Allow access to channels either by referring to the channel name
        # or through a channel list, i.e. instr.A.temperature() and
        # instr.channels[0].temperature() refer to the same parameter.
        # Note that `snapshotable` is set to false in order to avoid duplicate
        # snapshotting which otherwise will happen because each channel is also
        # added as a submodule to the instrument.
        channels = ChannelList(self,
                               "TempSensors",
                               self.CHANNEL_CLASS,
                               snapshotable=False)
        for name, command in self.channel_name_command.items():
            channel = self.CHANNEL_CLASS(self, name, command)
            channels.append(channel)
            self.add_submodule(name, channel)
        self.add_submodule("channels", channels.to_channel_tuple())

        # on Model335 we need to change serial port settings
        # before we can communicate
        if print_connect_message:
            self.connect_message()

    # Minimum spacing between serial transactions. The LS370 misses a query sent ~10 ms after a write
    # (HTR? right after MOUT timed out on every ramp tick, POST_CYCLE_FIXES P0-1), so every transaction
    # waits until at least this long after the previous one finished. All threads share _io_lock.
    MIN_GAP_AFTER_WRITE_S = 0.15
    MIN_GAP_AFTER_QUERY_S = 0.05
    _io_ready_at = 0.0

    def _wait_for_bus(self) -> None:
        dt = self._io_ready_at - time.monotonic()
        if dt > 0:
            time.sleep(dt)

    def write_raw(self, cmd: str) -> None:
        with self._io_lock:
            self._wait_for_bus()
            try:
                super().write_raw(cmd)
            finally:
                self._io_ready_at = time.monotonic() + self.MIN_GAP_AFTER_WRITE_S

    def ask_raw(self, cmd: str) -> str:
        with self._io_lock:
            self._wait_for_bus()
            try:
                return super().ask_raw(cmd)
            finally:
                self._io_ready_at = time.monotonic() + self.MIN_GAP_AFTER_QUERY_S