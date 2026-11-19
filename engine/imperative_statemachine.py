import ast
import textwrap
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

_NO_YIELD_AFTER = (ast.Return, ast.Raise, ast.Break, ast.Continue, ast.Pass)
_COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)


class _YieldInserter(ast.NodeTransformer):
    """
    Insert `yield <line index>` after every statement of the state function body (recursively into
    if/for/while/with/try blocks), and at the start of every block (so loop iterations always yield).

    The yielded value is the 0-based line index of the statement's first line in the source, which
    is what State.code_line/code_highlighted expect. Works on statement nodes, so multi-line statements
    (wrapped call arguments, long strings) are fine.
    Nested function/class definitions are left untouched (a yield would turn them into generators).
    """

    def _with_yields(self, stmts, header_lineno=None):
        out = []
        if header_lineno is not None:
            out.append(_yield_stmt(header_lineno))
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append(s)
                continue
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
                out.append(s)  # docstring / bare string
                continue
            if isinstance(s, _COMPOUND):
                self._transform_compound(s)
            out.append(s)
            if not isinstance(s, _NO_YIELD_AFTER):
                out.append(_yield_stmt(s.lineno))
        return out

    def _transform_compound(self, node):
        if isinstance(node, ast.Try):
            node.body = self._with_yields(node.body, node.lineno)
            for h in node.handlers:
                h.body = self._with_yields(h.body, h.lineno)
            if node.orelse:
                node.orelse = self._with_yields(node.orelse)
            if node.finalbody:
                node.finalbody = self._with_yields(node.finalbody)
            return
        node.body = self._with_yields(node.body, node.lineno)
        if getattr(node, "orelse", None):
            node.orelse = self._with_yields(node.orelse)

    def transform_function(self, fn):
        fn.body = self._with_yields(fn.body)
        # Guarantee the function is a generator even if no yield was inserted (e.g. only `return x`).
        fn.body.append(ast.If(test=ast.Constant(value=False), body=[_yield_stmt(fn.lineno)], orelse=[]))
        return fn


def _yield_stmt(lineno):
    return ast.Expr(value=ast.Yield(value=ast.Constant(value=int(lineno) - 1)))


def insert_line_number_yields(source: str) -> str:
    """
    AST-based transform (2026-11-18): returns Python source of the function(s) in `source` with a
    `yield <line index>` after every statement. Replaces the old line-based text transform, which
    broke on multi-line statements (SyntaxError at import).
    """
    tree = ast.parse(textwrap.dedent(source))
    inserter = _YieldInserter()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inserter.transform_function(node)
    tree = ast.fix_missing_locations(tree)
    # Keep original line numbers on the yields so tracebacks still point near the right line.
    return _unparse_preserving_lines(tree)


def _unparse_preserving_lines(tree) -> str:
    """ast.unparse loses line numbers; that's fine for exec. Callers that need tracebacks use the raw source."""
    return ast.unparse(tree)


def insert_line_number_yields_legacy(source: str) -> str:
    """Old line-based transform, kept for reference. Breaks on multi-line statements."""
    new_source = ""
    i = 0
    n_leading_whitespace = 0
    in_triple_double = False
    in_triple_single = False

    for line in source.splitlines():
        new_source += f"{line}\n"
        stripped = line.strip()

        # Handle multiline string literals / docstrings
        num_triple_double = stripped.count('"""')
        num_triple_single = stripped.count("'''")
        if num_triple_double % 2 != 0:
            in_triple_double = not in_triple_double
        if num_triple_single % 2 != 0:
            in_triple_single = not in_triple_single

        if in_triple_double or in_triple_single:
            i += 1
            continue

        if not stripped or stripped.startswith("#") or stripped.startswith("@"):
            i += 1
            continue

        line_indent = len(line) - len(line.lstrip())
        n_leading_whitespace = line_indent

        # Check if line opens a new block
        clean_code = stripped.split("#")[0].rstrip()
        if clean_code.endswith(":"):
            n_leading_whitespace = line_indent + 4

        # Skip yield after jump/terminating statements
        if stripped in ("break", "continue", "pass") or stripped.startswith(("break ", "continue ", "pass ", "return", "raise")):
            i += 1
            continue

        whitespace = " " * n_leading_whitespace
        new_source += f"{whitespace}yield {i}\n"
        i += 1

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
    display_source: str = None

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
        src = self.display_source if self.display_source is not None else self.raw_source
        lines = src.splitlines()
        idx = line_number - 1 if self.display_source is not None else line_number
        if 0 <= idx < len(lines):
            return lines[idx]
        return ""
    
    def code_highlighted(self, line_number):
        src = self.display_source if self.display_source is not None else self.raw_source
        if self.display_source is not None:
            idx = max(0, line_number - 1)
            return highlight_line(src, idx)
        return highlight_line(src, line_number)


