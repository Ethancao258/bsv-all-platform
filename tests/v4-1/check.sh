#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1
tmp=$(mktemp -d)
pg="bsv-v41-${tmp##*.}-$$"
trap 'docker rm -fv "$pg" >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
docker run -d --name "$pg" -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data:rw,size=256m -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e POSTGRES_DB=bsv_identity_isolated_v41 postgres:17 >/dev/null
port=$(docker port "$pg" 5432 | sed -n 's/^127.0.0.1://p')
for attempt in {1..40}; do
  if docker exec "$pg" pg_isready -h 127.0.0.1 -U postgres -d bsv_identity_isolated_v41 >/dev/null; then break; fi
  sleep 0.5
done
export BSV_APP_ENV=isolated BSV_AUTH_PROVIDER=isolated BSV_DB_SSLMODE=disable
export BSV_DB_A_URL="postgresql+psycopg://postgres@127.0.0.1:$port/bsv_identity_isolated_v41"
export BSV_V41_TEST_ACTIVE=1
unset BSV_DB_B_READONLY_URL BSV_DATA_SOURCES_FILE
python3 -m pytest -q -p no:cacheprovider tests/v4-1
