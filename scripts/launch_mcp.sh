#!/usr/bin/env bash
set -euo pipefail
plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
if [[ -x "$plugin_root/.venv/bin/python" ]]; then
  python_bin="$plugin_root/.venv/bin/python"
fi
export PYTHONPATH="$plugin_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_bin" -m learning_orchestrator.mcp_server
