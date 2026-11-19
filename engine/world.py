from collections import OrderedDict
import time
from dataclasses import dataclass, field
import types
import inspect
try:
    from .imperative_statemachine import state, State
except ImportError:
    from imperative_statemachine import state, State
from typing import Callable, Union, Any
import random
import numpy as np
import sys
import select

def nonblocking_readline():
    """Non-blocking read of a single line from sys.stdin."""
    try:
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.readline()
    except Exception:
        pass
    return None

# how to compile function from text
# https://stackoverflow.com/questions/32429154/how-to-compile-a-function-at-run-time
# how to get function source
# https://stackoverflow.com/questions/427453/how-can-i-get-the-source-code-of-a-python-function

@dataclass
class WaitUntil:
    time_s: float

@dataclass
class WaitForInput:
    target_input: str

@dataclass
class World:
    last_update_time_s: float = field(default=None,init=False)
    time: Any = field(default = time, init=False)
    command: Union[Any, None] = None
    target_tick_rate_s: float = 1.0
    state_start_time: float = field(default=0.0, init=False)
    to_wait_for_process_line: float = 0.0
    current_phase: str = "Holding steady"
    phase_step: int = 1
    total_steps: int = 1
    wait_duration_s: float = 0.0
    operator_action_required: bool = False
    operator_action_confirmed: bool = False
    operator_action_message: str = ""

    def request_operator_action(self, message: str):
        """Prompt operator for an action and mark that acknowledgment is required."""
        self.operator_action_required = True
        self.operator_action_confirmed = False
        self.operator_action_message = str(message)
        print(f"\n{'='*70}\n⚠️ OPERATOR ACTION REQUIRED:\n{message}\n{'='*70}\n")
        if hasattr(self, "_data_thread") and self._data_thread is not None:
            state_name = getattr(self._data_thread.state, "name", lambda: "procedure")()
            self._data_thread.operator_action.emit(state_name, message)

    def confirm_operator_action(self):
        """Called when operator acknowledges the banner in the GUI."""
        self.operator_action_confirmed = True
        self.operator_action_required = False
        self.operator_action_message = ""
        print("✔ Operator action confirmed.")

    def is_operator_action_confirmed(self) -> bool:
        """Returns True if operator has confirmed the required action."""
        return self.operator_action_confirmed

    def set_phase(self, phase_name: str, step: int = 1, total_steps: int = 1):
        self.current_phase = str(phase_name)
        self.phase_step = int(step)
        self.total_steps = int(total_steps)

    # do not overload
    def _update(self, state):
        now = self.time.time()
        self.update(state)
        if self.last_update_time_s is not None:
            elapsed_s = now-self.last_update_time_s
            self.update_with_elapsed(elapsed_s=elapsed_s)
        self.last_update_time_s = now

    # meant to read updates from instruments in an async way
    # overload
    def update(self, state):
        pass

    # overload
    def update_with_elapsed(self, elapsed_s):
        pass

    def state_elapsed_s(self):
        return self.time.time()-self.state_start_time

    def switch_to_state(self, target_state):
        """Programmatically switch state machine to a target state."""
        if hasattr(self, "_data_thread") and self._data_thread is not None:
            if isinstance(target_state, str):
                self._data_thread.set_combo_value(target_state)
            else:
                self._data_thread.next_state = target_state
                self._data_thread.paused = False

    def state_runner(self, state: State):
        self.command = None
        state_gen = state.func_to_make_generator(self)
        self.state_start_time = self.time.time()
        line_number = 0
        self._update(state)
        while True:
            should_update, should_run_line = self.process_command_and_decide_execution()
            if should_update:
                self._update(state)
            try: 
                if should_run_line:
                    self._step_seq += 1
                    self._in_state_step = True
                    try:
                        line_number = state_gen.send(None)
                    finally:
                        self._in_state_step = False
                yield state, line_number
            except StopIteration as e:
                next_state = e.value
                if next_state is None:
                    return
                elif next_state != state:
                    self.state_start_time = self.time.time()
                state = next_state
                state_gen = state.func_to_make_generator(self)
                line_number = 0
            # except KeyboardInterrupt:
            #     print("KeyboardInterrupt: exiting")
            #     return
            
    def next_tick_target_time_s(self):
        if self.last_update_time_s is None:
            return self.time.time()
        return self.last_update_time_s + self.target_tick_rate_s
    

    def process_command_and_decide_execution(self):
        # 1. If no command is waiting, execute next state machine line immediately
        if self.command is None:
            should_update = False
            should_process_line = True
            return should_update, should_process_line

        # 2. If command is WaitUntil, check if wait duration has completed
        if isinstance(self.command, WaitUntil):
            self.to_wait_for_process_line = self.command.time_s - self.time.time()
            if self.to_wait_for_process_line <= 0:
                self.command = None
                should_update = False
                should_process_line = True
                return should_update, should_process_line

            to_wait_for_tick_s = self.next_tick_target_time_s() - self.time.time()
            # Sleep at least 0.1 s (a 0.01 s floor made the LS370 HTR? read land ~10 ms after each MOUT
            # write during ramps, so it timed out every tick: POST_CYCLE_FIXES P0-1). Cap at 0.5 s so the
            # thread stays responsive to GUI aborts/pauses.
            sleep_duration = min(self.to_wait_for_process_line, max(0.1, to_wait_for_tick_s), 0.5)
            self.time.sleep(sleep_duration)
            should_update = (self.next_tick_target_time_s() - self.time.time() <= 0)
            should_process_line = False
            return should_update, should_process_line

        # 3. If command is WaitForInput, check non-blocking stdin
        elif isinstance(self.command, WaitForInput):
            line = nonblocking_readline()
            if line is not None:
                line = line.strip()
                print(f"got line! {self.command.target_input=}")
                print(line)
                if line == self.command.target_input:
                    self.command = None
                    should_update = False
                    should_process_line = True
                    return should_update, should_process_line

            self.time.sleep(max(0.1, self.target_tick_rate_s))
            should_update = True
            should_process_line = False
            return should_update, should_process_line

        return False, True


    # Guard state for wait() (see wait()). Plain class attributes so dataclass fields stay unchanged.
    _step_seq = 0
    _wait_seq = -1
    _in_state_step = False
    strict_wait = True

    def wait(self, seconds):
        """
        Schedule a wait. It only takes effect at the next `yield`, i.e. after the current line of the
        running @state body. Raises if called twice in one step: that means a loop calling wait() inside
        a plain helper function (no yields), which spins forever, stops telemetry and can't be aborted
        (the 2026-11-16 pre-cool deadlock). Put such loops in the @state body instead.
        """
        if self.strict_wait and self._in_state_step and self._wait_seq == self._step_seq:
            raise RuntimeError("world.wait() called twice without yielding: wait loops must live in the "
                               "@state body, not in a helper function (see docs/POST_CYCLE_FIXES.md P1-1).")
        self._wait_seq = self._step_seq
        self.wait_duration_s = float(seconds)
        self.command = WaitUntil(time_s=self.time.time() + float(seconds))

    def wait_for_input(self, target_input):
        self.command = WaitForInput(target_input)
            

    def run_state(self, state: State):
        runner = self.state_runner(state)
        time.sleep(self.next_tick_target_time_s()-time.time())
        self._update(state)
        tstart = self.last_update_time_s
        for (state, line_number) in runner:
            elapsed = self.last_update_time_s-tstart
            print(f"state={state.name()} {line_number=} {elapsed=:.2f} state_elapsed_s={self.state_elapsed_s():.2f}")
            print(state.code_highlighted(line_number))
            # print(f"I={self.current_A:.2f} V={self.voltage_V:.2f}")



@dataclass 
class FakeAdrWorld(World):
    current_A: float = 0
    voltage_V: float = 0
    inductance_H: float = 1
    resistance_Ohm: float = 0.2

    def update_with_elapsed(self, elapsed_s):
        # v = l*didt
        didt = (self.voltage_V-self.current_A*self.resistance_Ohm)/self.inductance_H
        # print(f"{elapsed_s=:.2f} {didt=:.4f} {self.current_A*self.resistance_Ohm=:.4f}")

        self.current_A += didt*elapsed_s

    def set_voltage(self, v):
        self.voltage_V=v
    


@state
def zero_current(world: FakeAdrWorld):
    world.wait(seconds=5)
    return ramp_up

@state 
def ramp_up(world: FakeAdrWorld):
    target_voltage = 2
    target_time_s = 20
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = target_voltage/target_N_steps
    for i in range(target_N_steps):
        world.set_voltage(step_size*(i+1))
        world.wait(seconds=target_step_duration_s)
    return soak

@state
def soak(world: FakeAdrWorld):
    world.wait(20)
    return ramp_down

@state
def ramp_down(world: FakeAdrWorld):
    Vstart = world.voltage_V
    target_time_s = 20
    max_voltage = 2
    target_step_duration_s = 1
    target_N_steps = int(target_time_s/target_step_duration_s)
    step_size = -np.sign(Vstart)*Vstart/target_N_steps
    volts = np.arange(Vstart, step_size, step_size)
    for v in volts:
        world.set_voltage(v)
        world.wait(target_step_duration_s)
    return chill_after_ramp_down

@state
def chill_after_ramp_down(world: FakeAdrWorld):
    world.wait(10)
    return

if __name__ == "__main__":
    world = FakeAdrWorld()
    result = world.run_state(zero_current)
    print(result)


# features to add
# 1. world argument DONE
# 2. world.wait(seconds=) DONE
# 3. world.wait_for_input_or_time(message, seconds)
# 4. adr-ish demo DONE
# 5. duck db data log
