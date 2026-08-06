#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
elif [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

"$PYTHON" -m pytest tests "$@"
