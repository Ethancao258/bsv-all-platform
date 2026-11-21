#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONDONTWRITEBYTECODE=1
for js in apps/staff-center/identity/assets/*.js apps/hq-console/identity/*.js; do node --check "$js"; done
node --check apps/hq-console/bsv1/hq.js
python -m pytest -q -p no:cacheprovider tests/identity
tmp=$(mktemp -d)
pid=
cleanup(){ if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi; rm -rf "$tmp"; }
trap cleanup EXIT
unset BSV_DB_B_READONLY_URL BSV_DATA_SOURCES_FILE BSV_ALLOWED_ORIGINS_JSON BSV_REGISTRATION_ENTITIES_JSON
export BSV_APP_ENV=isolated BSV_AUTH_PROVIDER=isolated BSV_IDENTITY_PORT=0
export BSV_DB_A_URL="sqlite+pysqlite:///$tmp/identity.sqlite3"
bash -n platform/lighthouse/identity/launch.sh
bash platform/lighthouse/identity/launch.sh --dry-run
python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
bash platform/lighthouse/identity/launch.sh > "$tmp/http.log" 2>&1 &
pid=$!
port=
for attempt in {1..30}; do
    port=$(sed -n 's/.*127\.0\.0\.1:\([0-9]*\) (Press CTRL+C.*/\1/p' "$tmp/http.log" | tail -1)
    [[ -z "$port" ]] || break
    sleep 0.2
done
if [[ -z "$port" ]]; then cat "$tmp/http.log"; exit 1; fi
python - "$port" <<'PY'
import json,sys
from urllib.request import build_opener,ProxyHandler
open_local=build_opener(ProxyHandler({})).open
base="http://127.0.0.1:"+sys.argv[1]
with open_local(base+"/health/ready",timeout=3) as response:
    assert response.status==200
for path in ("/staff","/hq","/hq-assets/hq.js"):
    with open_local(base+path,timeout=3) as response:
        assert response.status==200 and response.read()
with open_local(base+"/openapi.json",timeout=3) as response:
    from pathlib import Path
    expected=json.loads(Path("contracts/identity/identity.openapi.json").read_bytes())
    assert json.load(response)==expected
print("PASS: staging launcher, migrated health, UI, and OpenAPI")
PY
