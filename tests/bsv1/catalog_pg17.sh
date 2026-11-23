#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
name="bsv-catalog-pg17-${RANDOM}-$$"
cleanup() { docker rm -fv "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$name" -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=bsv_all_prod postgres:17 >/dev/null
port=$(docker port "$name" 5432 | sed -n 's/^127\.0\.0\.1://p')
for attempt in {1..40}; do
  if docker exec "$name" pg_isready -h 127.0.0.1 -U postgres -d bsv_all_prod >/dev/null; then break; fi
  sleep 0.5
done
docker exec "$name" psql -U postgres -d bsv_all_prod -v ON_ERROR_STOP=1 -c \
  "CREATE ROLE bsv_catalog_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE bsv_catalog_confidential_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE bsv_catalog_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE; GRANT bsv_catalog_reader TO bsv_catalog_confidential_reader; GRANT bsv_catalog_reader,bsv_catalog_confidential_reader TO bsv_catalog_runtime;" >/dev/null
export BSV_APP_ENV=isolated BSV_ALLOW_ISOLATED_CATALOG_IMPORT=1 BSV_CATALOG_READ_SOURCE=postgres
export BSV_CATALOG_PG17_TEST=1
export BSV_DB_URL="postgresql://postgres@127.0.0.1:${port}/bsv_all_prod?sslmode=disable"
export BSV_CATALOG_ADMIN_DB_URL="$BSV_DB_URL"
python3 -m unittest tests.bsv1.test_catalog_pg17 -v
