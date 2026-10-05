import os
import re
from pathlib import Path
from imperative_statemachine import State, insert_line_number_yields, collect_exits, remove_decorators
import states as states_module

DESKTOP_SCRIPTS_DIR = Path.home() / "Desktop" / "custom_scripts"

def pseudocode_to_python_line(line: str) -> str:
    """
    Convert a single line of pseudocode into a standard Python statement.
    If line is already standard Python code or comment/blank, return as-is.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line

    indent = line[:len(line) - len(line.lstrip())]

    # Don't touch lines that are already standard Python statements
    if (stripped.startswith("world.") or stripped.startswith("print(") or 
        stripped.startswith("def ") or stripped.startswith("if ") or 
        stripped.startswith("while ") or stripped.startswith("for ") or 
        stripped.startswith("return ")):
        return line

    # Pattern: close/open heatswitch <name> OR close/open <name> heatswitch (allows "heat switch" or "heatswitch")
    m_hs1 = re.match(r'^(close|open)\s+heat\s*switch\s+(\w+)$', stripped, re.IGNORECASE)
    m_hs2 = re.match(r'^(close|open)\s+(\w+)\s+heat\s*switch$', stripped, re.IGNORECASE)
    if m_hs1 or m_hs2:
        m = m_hs1 or m_hs2
        action, hs_name = m.groups()
        state_str = "CLOSED" if action.lower() == "close" else "OPEN"
        return f'{indent}world.station.labjack.heatswitch_{hs_name.lower()}("{state_str}")'

    # Pattern: set heatswitch <name> [to] <state> OR set <name> heatswitch [to] <state>
    m_set_hs1 = re.match(r'^set\s+heat\s*switch\s+(\w+)\s+(?:to\s+)?(CLOSED|OPEN)$', stripped, re.IGNORECASE)
    m_set_hs2 = re.match(r'^set\s+(\w+)\s+heat\s*switch\s+(?:to\s+)?(CLOSED|OPEN)$', stripped, re.IGNORECASE)
    if m_set_hs1 or m_set_hs2:
        m = m_set_hs1 or m_set_hs2
        hs_name, state_str = m.groups()
        return f'{indent}world.station.labjack.heatswitch_{hs_name.lower()}("{state_str.upper()}")'

    # Pattern: set relay [to] <mode>
    m_relay = re.match(r'^set\s+relay\s+(?:to\s+)?(\w+)$', stripped, re.IGNORECASE)
    if m_relay:
        mode = m_relay.group(1).upper()
        return f'{indent}world.station.labjack.relay("{mode}")'

    # Pattern: wait/sleep <N> [s|sec|seconds|m|min|minutes|h|hr|hours]
    m_wait = re.match(r'^(?:wait|sleep)\s+([\d\.e\+]+)\s*(s|sec|seconds|m|min|minutes|h|hr|hours)?$', stripped, re.IGNORECASE)
    if m_wait:
        val_str, unit = m_wait.groups()
        val = float(val_str)
        unit = (unit or "").lower()
        if unit in ("m", "min", "minutes"):
            val *= 60
        elif unit in ("h", "hr", "hours"):
            val *= 3600
        val_repr = int(val) if val.is_integer() else f"{val:.4g}"
        return f'{indent}world.wait({val_repr})'

    # Pattern: print <message> (without parens)
    m_print = re.match(r'^print\s+(.*)$', stripped, re.IGNORECASE)
    if m_print:
        msg = m_print.group(1).strip()
        if (msg.startswith('"') and msg.endswith('"')) or (msg.startswith("'") and msg.endswith("'")):
            msg = msg[1:-1]
        return f'{indent}print("{msg}")'

    # Pattern: return <state>
    m_ret = re.match(r'^return\s+(\w+)$', stripped, re.IGNORECASE)
    if m_ret:
        target = m_ret.group(1)
        return f'{indent}return {target}'

    return line

def parse_txt_to_python(script_name: str, txt_content: str) -> str:
    """
    Wraps line-by-line pseudocode or Python statements into a function:
    `def {script_name}(world: StationWorld):`
    """
    lines = txt_content.splitlines()
    has_def = any(l.strip().startswith("def ") for l in lines)
    
    if has_def:
        py_lines = [pseudocode_to_python_line(l) for l in lines]
        return "\n".join(py_lines)
    else:
        py_lines = [f"def {script_name}(world: StationWorld):"]
        for l in lines:
            converted = pseudocode_to_python_line(l)
            if converted.strip():
                py_lines.append(f"    {converted}")
            else:
                py_lines.append("")
        return "\n".join(py_lines)

def load_state_from_txt(txt_path: Path) -> tuple[str, State]:
    """
    Load a .txt file from disk, translate pseudocode to Python, and compile into a State object.
    """
    script_name = txt_path.stem
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()

    py_source = parse_txt_to_python(script_name, content)
    source_clean = remove_decorators(py_source)
    new_source = insert_line_number_yields(source_clean)
    exits = collect_exits(source_clean)

    exec_globals = dict(states_module.__dict__)
    new_code = compile(new_source, str(txt_path), "exec")
    exec(new_code, exec_globals)

    if script_name in exec_globals:
        func = exec_globals[script_name]
        st_obj = State(exits, source_clean, new_source, func, display_source=content)
        return script_name, st_obj
    else:
        raise ValueError(f"Function {script_name} not found after compiling {txt_path.name}")

def load_all_desktop_scripts() -> dict[str, State]:
    """
    Loads all .txt custom scripts from ~/Desktop/custom_scripts/.
    Returns a dict mapping script_name -> State object.
    """
    DESKTOP_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    custom_states = {}
    for p in sorted(DESKTOP_SCRIPTS_DIR.glob("*.txt")):
        try:
            name, st_obj = load_state_from_txt(p)
            custom_states[name] = st_obj
        except Exception as e:
            print(f"Error loading desktop script {p.name}: {e}")
    return custom_states
