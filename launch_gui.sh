#!/bin/bash
cd /home/pcuser/qsp/src/2pac
if [ -d ".venv" ]; then
    exec .venv/bin/python main.py "$@"
elif command -v uv &> /dev/null; then
    exec uv run python main.py "$@"
else
    source .venv/bin/activate
    exec python main.py "$@"
fi
