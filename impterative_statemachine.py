from dataclasses import dataclass, field
import inspect
from typing import Callable, Union


# how to compile function from text
# https://stackoverflow.com/questions/32429154/how-to-compile-a-function-at-run-time
# how to get function source
# https://stackoverflow.com/questions/427453/how-can-i-get-the-source-code-of-a-python-function


def collect_exits(source: str) -> list[str]:
    exits = []
    for line in source.splitlines():
        stripped = line.lstrip()  # Remove leading whitespace
        if stripped.startswith("return"):  # Check if the line starts with "return"
            after_return = stripped.split(" ", 1)[-1].strip()  # Split the line at the first space and take the rest
            if after_return:  # If there's content after "return"
                exits.append(after_return)  # Add the state name after "return" to the exits list
            else:  # If it's a bare return
                exits.append(None)  # Append None to indicate a bare return
    return exits  # Return the list of exit states

def insert_line_number_yields(source: str) -> str:
    new_source = ""
    i = 0
    for line in source.splitlines():
        new_source += f"{line}\n"
        stripped = line.lstrip()
        n_leading_whitespace = len(line) - len(stripped)
        if stripped.startswith("def") or stripped.startswith("for") or stripped.startswith("if"):
            n_leading_whitespace += 4
        whitespace = " " * n_leading_whitespace
        if not line.startswith("@"): # dont annotate decorator lines
            new_source += f"{whitespace}yield {i}\n"
        i+=1
    return new_source

def remove_decorators(source: str) -> str:
    lines = source.splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("@"):
            new_lines.append(line)
    return "\n".join(new_lines)

# a decorator to create an imperative state from a function
def state(func):
    source = remove_decorators(inspect.getsource(func))
    new_source = insert_line_number_yields(source)
    exits = collect_exits(source)
    filename_for_errors = f"""virtual file created by imperative_statemachine for {func.__name__} in {__file__}

{new_source}"""
    new_code = compile(new_source, filename_for_errors, "exec")
    # env = {}
    # exec(new_code, env)
    # exec(new_code)
    frame = inspect.currentframe().f_back  # Get the frame of the caller (where func is defined)
    globals_from_func_definition = frame.f_globals  # Get the globals from where func was defined
    exec(new_code, globals_from_func_definition)  # Pass the globals from where func was defined

    return State(exits, source, new_source, globals_from_func_definition[func.__name__])
    
def highlight_line(text: str, line_index: int) -> str:
    """
    Highlight a specific line in a multiline string by adding an arrow or indentation.

    Args:
        text (str): The multiline string.
        line_index (int): The index of the line to highlight (0-based).

    Returns:
        str: The modified string with the specified line highlighted.

    Example:
        >>> multiline_string = \"\"\"This is a multiline
        ... string in Python.
        ... It has multiple lines.\"\"\"
        >>> highlighted_text = highlight_line(multiline_string, 1)
        >>> print(highlighted_text)
            This is a multiline
        --> string in Python.
            It has multiple lines.
    """
    lines = text.split('\n')
    highlighted_lines = []
    for i, line in enumerate(lines):
        if i == line_index:
            highlighted_lines.append("--> " + line)
        else:
            highlighted_lines.append("    " + line)
    return '\n'.join(highlighted_lines)

@dataclass 
class State:
    exits: list[str]
    raw_source: str
    new_source: str
    func_to_make_generator: Callable

    def run_until_complete(self) -> tuple[list[int], Union['State', None]]:
        gen = self.func_to_make_generator()
        line_numbers = []
        while True:
            try:
                line_number = gen.send(None)
                line_numbers.append(line_number)
            except StopIteration as e:
                next_state = e.value
                return line_numbers, next_state
            
    def run_state_then_next_and_so_on(self, state):
        while True:
            if state is None:
                return
            line_numbers, state = state.run_until_complete()

    def name(self):
        return self.func_to_make_generator.__name__
    
    def code_line(self, line_number):
        lines = self.raw_source.splitlines()
        return lines[line_number]
    
    def code_highlighted(self, line_number):
        return highlight_line(self.raw_source, line_number)


