#!/usr/bin/env bash
set -euo pipefail

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The dashboard itself only uses Python's standard library. Prefer a native
# WSL virtual environment when present, otherwise run directly from source.
if [[ -x "$plugin_root/.venv/bin/python" ]]; then
  python_bin="$plugin_root/.venv/bin/python"
else
  python_bin="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$plugin_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_bin" -m learning_orchestrator.dashboard "$@"
