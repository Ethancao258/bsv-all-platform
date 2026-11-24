#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
name="bsv-catalog-pg17-${RANDOM}-$$"
tmp=$(mktemp -d)
cleanup() { docker rm -fv "$name" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
pg_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker run -d --name "$name" -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_PASSWORD="$pg_password" -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
  -e POSTGRES_INITDB_ARGS='--auth-local=peer' -e POSTGRES_DB=bsv_all_prod postgres:17 >/dev/null
port=$(docker port "$name" 5432 | sed -n 's/^127\.0\.0\.1://p')
for attempt in {1..40}; do
  if docker exec "$name" pg_isready -U postgres -d bsv_all_prod >/dev/null; then break; fi
  sleep 0.5
done
gateway=$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')
cat > "$tmp/pg_hba.conf" <<EOF
local all all peer
host bsv_all_prod bsv_catalog_importer 127.0.0.1/32 scram-sha-256
host bsv_all_prod bsv_catalog_importer ${gateway}/32 scram-sha-256
host bsv_all_prod bsv_catalog_runtime 127.0.0.1/32 scram-sha-256
host bsv_all_prod bsv_catalog_runtime ${gateway}/32 scram-sha-256
EOF
chmod 600 "$tmp/pg_hba.conf"
docker cp "$tmp/pg_hba.conf" "$name:/tmp/pg_hba.conf"
docker exec "$name" chown postgres:postgres /tmp/pg_hba.conf
docker exec "$name" chmod 600 /tmp/pg_hba.conf
docker exec "$name" mv /tmp/pg_hba.conf /var/lib/postgresql/data/pg_hba.conf
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'SELECT pg_reload_conf()' >/dev/null
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN IF EXISTS (SELECT 1 FROM pg_hba_file_rules WHERE error IS NOT NULL) THEN RAISE EXCEPTION 'invalid HBA'; END IF; END \$\$;" >/dev/null
docker exec --user postgres "$name" psql -U postgres -d bsv_all_prod -v ON_ERROR_STOP=1 -c \
  "CREATE ROLE bsv_catalog_importer LOGIN PASSWORD 'importpw' NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE bsv_catalog_runtime LOGIN PASSWORD 'runtimepw' NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE bsv_catalog_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE bsv_catalog_confidential_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; GRANT bsv_catalog_reader TO bsv_catalog_confidential_reader; GRANT bsv_catalog_reader,bsv_catalog_confidential_reader TO bsv_catalog_runtime;" >/dev/null
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'ALTER DATABASE bsv_all_prod OWNER TO bsv_catalog_importer' >/dev/null
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'REVOKE CONNECT ON DATABASE bsv_all_prod FROM PUBLIC; GRANT CONNECT ON DATABASE bsv_all_prod TO bsv_catalog_importer,bsv_catalog_runtime' >/dev/null
export BSV_APP_ENV=isolated BSV_ALLOW_ISOLATED_CATALOG_IMPORT=1 BSV_CATALOG_READ_SOURCE=postgres
export BSV_CATALOG_PG17_TEST=1 BSV_DB_SSLMODE=disable
export BSV_DB_URL="postgresql://bsv_catalog_runtime:runtimepw@127.0.0.1:${port}/bsv_all_prod?sslmode=disable"
export BSV_CATALOG_ADMIN_DB_URL="postgresql://bsv_catalog_importer:importpw@127.0.0.1:${port}/bsv_all_prod?sslmode=disable"
python3 -m unittest tests.bsv1.test_catalog_pg17 -v
