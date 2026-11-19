import time
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


class _CsetFormatter:
    """
    qcodes Group only accepts a format string as set_cmd. This object quacks like one: format() reads
    CSET? and keeps the instrument's current heater limit and resistance, changing only the grouped
    fields (channel, filter, delay).
    """

    def __init__(self, output: "LakeshoreModel370Output") -> None:
        self._out = output

    def format(self, channel, use_filter, delay, **_ignored) -> str:
        parts = [x.strip() for x in self._out.ask("CSET?").split(",")]
        limit = int(float(parts[5])) if len(parts) >= 7 else 6
        r_ohm = float(parts[6]) if len(parts) >= 7 else 100.0
        return f"CSET {int(channel)}, {int(use_filter)}, 1, {int(delay)}, 1, {limit}, {r_ohm:.1f}"


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
        # 2026-11-19: CMODE? = 4 / HTRRNG? = 0 ("off", also on the front panel) with a live closed-loop output
        # was NOT a readback quirk. Writing CMODE 4 (the old Stop button) sets both registers to "off" on this
        # unit (fw 04102008) but the PID output keeps running. Re-writing HTRRNG 6 restored the readback with no
        # bump (re-writing CMODE 1 does bump: it resets the integrator). So the getters return what the instrument says (that is what the operator sees on the front
        # panel), setters verify the readback, and "off" is not a settable mode: use output_off().
        self.commanded_mode = None   # "closed" / "open_loop" / ... as last written by this process
        self.commanded_range = None  # "10mA" / ... as last written by this process
        self._inv_modes = {v: k for k, v in self.MODES.items()}
        self._inv_ranges = {v: k for k, v in self.RANGES.items()}

        self.add_parameter("mode",
                           vals=vals.Enum(*self.MODES.keys()),
                           get_cmd=self._get_mode,
                           set_cmd=self._set_mode)
        self.add_parameter("mode_raw",
                           val_mapping=self.MODES,
                           get_cmd="CMODE?",
                           set_cmd=False)

        self.add_parameter("range",
                           vals=vals.Enum(*self.RANGES.keys()),
                           get_cmd=self._get_range,
                           set_cmd=self._set_range)
        self.add_parameter("range_raw",
                           val_mapping=self.RANGES,
                           get_cmd="HTRRNG?",
                           set_cmd=False)

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
            # Read-modify-write: the old format string hard-coded heater limit 4 (1 mA) and R = 100,
            # which silently clamped the 10 mA ramp / regulation ranges whenever this group was set.
            set_cmd=_CsetFormatter(self),
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

    # ---- mode / range: write, then verify against the instrument (see note in __init__) ----
    def _readback(self, query: str, inv: dict) -> str:
        return inv.get(int(float(self.ask(query))), "off")

    def _write_verified(self, cmd: str, query: str, inv: dict, want: str) -> None:
        got = None
        for _attempt in range(2):
            self.write(cmd)
            time.sleep(0.3)
            try:
                got = self._readback(query, inv)
            except Exception as e:  # noqa: BLE001 - readback failure is reported, not fatal
                got = f"unreadable ({e})"
            if got == want:
                return
        print(f"[LS370] WARNING: wrote '{cmd}' but {query} reads {got!r} (wanted {want!r})")

    def _set_mode(self, val: str) -> None:
        if val == "off":
            raise ValueError(
                "CMODE 4 ('off') does not stop the output on this LS370, it only blanks the front panel. "
                "Use heater.output_off() (open loop, 0 %).")
        self._write_verified(f"CMODE {self.MODES[val]}", "CMODE?", self._inv_modes, val)
        self.commanded_mode = val

    def _get_mode(self) -> str:
        return self._readback("CMODE?", self._inv_modes)

    def _set_range(self, val: str) -> None:
        self._write_verified(f"HTRRNG {self.RANGES[val]}", "HTRRNG?", self._inv_ranges, val)
        self.commanded_range = val

    def _get_range(self) -> str:
        return self._readback("HTRRNG?", self._inv_ranges)

    def output_off(self) -> None:
        """Heater output to 0 %: MOUT 0 then open loop (CMODE 3). The front panel then shows open loop, 0 %."""
        self.write("MOUT 0")
        time.sleep(0.2)
        self.mode("open_loop")
        self.write("MOUT 0")

    def loop_status(self) -> dict:
        """
        Instrument registers plus a liveness test. `stale` = the PID is driving the output but CMODE?/HTRRNG?
        say otherwise (front panel misleading); fix by re-writing the mode and range.
        """
        mode = self._get_mode()
        rng = self._get_range()
        htr = float(self.ask("HTR?"))
        mout = float(self.ask("MOUT?"))
        live_closed = abs(htr - mout) > 0.5
        stale = live_closed and (mode != "closed" or rng == "off")
        return {"mode": mode, "range": rng, "htr": htr, "mout": mout,
                "closed_loop": mode == "closed" or live_closed, "stale": stale}

    def closed_loop_active(self) -> bool:
        """True if the closed-loop PID is driving the output (CMODE? = 1, or HTR? != MOUT? with stale registers)."""
        return bool(self.loop_status()["closed_loop"])

    def setup_control(self, channel: int = 4, p: float = 7.0, i: float = 80.0, d: float = 0.0,
                      limit: int = 7, r_ohm: float = 100.0) -> None:
        """Configure Lake Shore 370 closed loop control channel (Kelvin units), heater limit and PID gains."""
        self.write(f"CSET {int(channel)}, 1, 1, 1, 1, {int(limit)}, {float(r_ohm):.1f}")
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