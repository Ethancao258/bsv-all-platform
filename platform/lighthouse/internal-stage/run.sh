#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd -P)
cd "$repo"
export PYTHONPATH="$repo"
release=$(dirname "$repo")
case "$1" in
  postgres)
    exec /usr/lib/postgresql/17/bin/postgres -D "$BSV_STAGE_COMPONENT_DATA/pg" \
      -h 127.0.0.1 -p 18764 -k "$BSV_STAGE_COMPONENT_DATA" ;;
  identity)
    export BSV_ACADEMY_MEDIA_ROOT=/var/lib/bsv-all-internal-stage/identity/academy-media
    if [[ -x /usr/bin/clamdscan ]]; then
      export BSV_ACADEMY_CLAMDSCAN=/usr/bin/clamdscan
    fi
    exec "$release/identity/bin/python" -m uvicorn services.api.identity.api:app --host 127.0.0.1 --port 18761 --no-proxy-headers --no-access-log ;;
  pos)
    export BSV_POS_DEVICE_REQUIRED=1
    exec /usr/bin/python3 services/api/bsv1/app.py ;;
  supply)
    exec "$release/supply/bin/python" -m uvicorn services.api.supply.main:app --host 127.0.0.1 --port 18763 --no-proxy-headers --no-access-log ;;
  ingress)
    # The integrated growth candidate SQLite and guest credentials must be private.
    umask 077
    exec "$release/identity/bin/python" -m uvicorn --app-dir platform/lighthouse/internal-stage ingress:app --host 127.0.0.1 --port 18760 --no-proxy-headers --no-access-log ;;
  *) exit 2 ;;
esac
