#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python" main.py "$@"
elif command -v uv &> /dev/null; then
    exec uv run python main.py "$@"
elif [ -n "$VIRTUAL_ENV" ]; then
    exec python main.py "$@"
else
    exec python3 main.py "$@"
fi
