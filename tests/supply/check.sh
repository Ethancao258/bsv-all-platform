#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONDONTWRITEBYTECODE=1
node --check apps/hq-console/supply/app.js
python -m pytest -q -p no:cacheprovider tests/supply
tmp=$(mktemp -d)
pid=
cleanup(){
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
    rm -rf "$tmp"
}
trap cleanup EXIT
export BSV_MODE=demo BSV_SUPPLY_STATE_DIR="$tmp/state" BSV_SUPPLY_PORT=0
unset BSV_SOURCES_CONFIG
bash -n platform/lighthouse/supply/launch.sh
bash platform/lighthouse/supply/launch.sh --dry-run
bash platform/lighthouse/supply/launch.sh > "$tmp/server.log" 2>&1 &
pid=$!
port=
for attempt in {1..30}; do
    port=$(sed -n 's/.*127\.0\.0\.1:\([0-9]*\) (Press CTRL+C.*/\1/p' "$tmp/server.log" | tail -1)
    [[ -z "$port" ]] || break
    sleep 0.2
done
if [[ -z "$port" ]]; then cat "$tmp/server.log"; exit 1; fi
python - "$port" <<'PY'
import json, sys
from urllib.request import ProxyHandler, build_opener
open_local = build_opener(ProxyHandler({})).open
base = "http://127.0.0.1:" + sys.argv[1]
with open_local(base + "/api/health", timeout=5) as response:
    checks = json.load(response)
assert checks["status"] == "OK" and checks["production_connected"] is False
for path in ("/store/supply", "/hq/supply", "/inspector/supply", "/assets/app.js"):
    with open_local(base + path, timeout=5) as response:
        assert response.status == 200 and response.read()
print("PASS: configured-port Uvicorn, loopback health and three entrypoints")
PY
