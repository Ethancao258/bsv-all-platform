#!/usr/bin/env bash
# The caller assigns the state root and port via the supervisor environment.
set -euo pipefail
cd "$(dirname "$0")/../../.."
: "${BSV_SUPPLY_PORT:?Set a supervisor-assigned port, or 0 for an isolated local port}"
: "${BSV_SUPPLY_STATE_DIR:?Set a private state directory outside the Git checkout}"
: "${BSV_MODE:?Set demo or remote explicitly}"
python - <<'PY'
from pathlib import Path
import os, socket
port = int(os.environ["BSV_SUPPLY_PORT"])
if not 0 <= port <= 65535 or (port == 0 and os.environ["BSV_MODE"] != "demo"):
    raise SystemExit("Invalid supply port")
state = Path(os.environ["BSV_SUPPLY_STATE_DIR"])
if not state.is_absolute() or state.resolve().is_relative_to(Path.cwd()):
    raise SystemExit("Supply state must be absolute and outside the checkout")
with socket.socket() as probe:
    probe.bind(("127.0.0.1", port))
print("Loopback port and state configuration pass preflight", flush=True)
PY
if [[ ${1:-} == --dry-run ]]; then
    python -c 'from services.api.supply.config import load_settings; load_settings()'
    exit
fi
exec python -m uvicorn services.api.supply.main:app --host 127.0.0.1 --port "$BSV_SUPPLY_PORT" --no-proxy-headers
