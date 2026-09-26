#!/usr/bin/env bash
# Launch the SPY LEAPS bot from anywhere (double-click, a symlink, or systemd).
# leaps_spy.py resolves .env, leaps_state.json and git info relative to cwd,
# so always run it from the repo root with the repo's venv.
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

if [[ ! -x venv/bin/python ]]; then
    echo "run.sh: $PWD/venv/bin/python not found. Create it with:" >&2
    echo "  python3 -m venv venv && venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

exec venv/bin/python -u leaps_spy.py "$@"
