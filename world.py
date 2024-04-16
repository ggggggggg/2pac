from collections import OrderedDict
import time
from dataclasses import dataclass, field
import types
import inspect
from imperative_statemachine import state, State
from typing import Callable, Union, Any
import random
import numpy as np

# how to compile function from text
# https://stackoverflow.com/questions/32429154/how-to-compile-a-function-at-run-time
# how to get function source
# https://stackoverflow.com/questions/427453/how-can-i-get-the-source-code-of-a-python-function

@dataclass
class WaitUntil:
    time_s: float

@dataclass
class World:
    last_update_time_s: float = field(default=None,init=False)
    time: Any = field(default = time, init=False)
    command: Union[Any, None] = None
    target_tick_rate_s: int = 1
    state_start_time: float = field(default=0.0, init=False)
    def wait(self, seconds):
        self.waiting_for = self.time.time() + seconds

    # do not overload
    def _update(self):
        now = self.time.time()
        self.update()
        if self.last_update_time_s is not None:
            elapsed_s = now-self.last_update_time_s
            self.update_with_elapsed(elapsed_s=elapsed_s)
        self.last_update_time_s = now

    # meant to read updates from instruments in an async way
    # overload
    def update(self):
        pass

    # overload
    def update_with_elapsed(self, elapsed_s):
        pass

    def state_elapsed_s(self):
        return self.time.time()-self.state_start_time

    def state_runner(self, state: State):
        state_gen = state.func_to_make_generator(self)
        self.state_start_time = self.time.time()
        line_number = 0
        while True:
            should_update, should_run_line = self.process_command_and_decide_execution()
            if should_update:
                self._update()
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
            to_wait_for_process_line = self.command.time_s-self.time.time()
            # print(f"{to_wait_for_process_line=}")
            if to_wait_for_process_line<0:
                self.command = None
                should_update = False
                should_process_line = True
                return should_update, should_process_line
        self.time.sleep(to_wait_for_tick_s)
        should_update = True
        should_process_line = False
        return should_update, should_process_line        
            
    



    def wait(self, seconds):
        self.command=WaitUntil(time_s = time.time()+seconds)
            

    def run_state(self, state: State):
        runner = self.state_runner(state)
        time.sleep(self.next_tick_target_time_s()-time.time())
        self._update()
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
