#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
: "${BSV_IDENTITY_PORT:?Assign an unused identity port}"
: "${BSV_DB_A_URL:?Set the reviewed isolated database connection}"
: "${BSV_APP_ENV:?Select isolated or staging explicitly}"
if [[ "$BSV_APP_ENV" != isolated && "$BSV_APP_ENV" != staging ]]; then
    echo "Template is restricted to staging" >&2
    exit 2
fi
python - <<'PY'
import os, socket
from services.api.identity.config import load_settings
from services.api.identity.cli import isolated_guard
isolated_guard(load_settings())
port = int(os.environ["BSV_IDENTITY_PORT"])
if not 0 <= port <= 65535:
    raise SystemExit("Invalid port")
with socket.socket() as sock:
    sock.bind(("127.0.0.1",port))
print("Identity preflight passes",flush=True)
PY
if [[ "${1:-}" == --dry-run ]]; then exit; fi
exec python -m uvicorn services.api.identity.api:app --host 127.0.0.1 --port "$BSV_IDENTITY_PORT" --no-proxy-headers
