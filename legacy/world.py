from collections import OrderedDict
import time
from dataclasses import dataclass, field
import types
import inspect
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
                    line_number = state_gen.send(None)
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
            return np.ceil(self.time.time())
        return np.floor(self.last_update_time_s+self.target_tick_rate_s)
    

    def process_command_and_decide_execution(self):
        # either command is None or has a command
        # if it is a wait command, we may not execute a line
        # if to_wait is negative, we'll update
        to_wait_for_tick_s = self.next_tick_target_time_s()-self.time.time()
        # print(f"{to_wait_for_tick_s=}")
        if to_wait_for_tick_s < 0:
            should_update = True
            should_process_line = False
            return should_update, should_process_line
        # print(f"{self.command=}")
        if self.command is None:
            should_update = False
            should_process_line = True
            return should_update, should_process_line    
        elif isinstance(self.command, WaitUntil):
            self.to_wait_for_process_line = self.command.time_s-self.time.time()
            # print(f"{to_wait_for_process_line=}")
            if self.to_wait_for_process_line<0:
                self.command = None
                should_update = False
                should_process_line = True
                return should_update, should_process_line
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


        sleep_chunk = min(max(0.01, to_wait_for_tick_s), 0.5)
        self.time.sleep(sleep_chunk)
        should_update = (self.next_tick_target_time_s() - self.time.time() <= 0)
        should_process_line = False
        return should_update, should_process_line        
            
    



    def wait(self, seconds):
        self.wait_duration_s = float(seconds)
        self.command = WaitUntil(time_s=time.time() + seconds)

    def wait_for_input(self, target_input):
        self.command=WaitForInput(target_input)
            

    def run_state(self, state: State):
        runner = self.state_runner(state)
        time.sleep(self.next_tick_target_time_s()-time.time())
        self._update(state)
        tstart = self.last_update_time_s
        for (state, line_number) in runner:
            elapsed = self.last_update_time_s-tstart