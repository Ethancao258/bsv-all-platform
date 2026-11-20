#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
tmp=$(mktemp -d)
name="bsv-identity-test-${tmp##*.}-$$"
cleanup() { docker rm -fv "$name" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
docker run -d --name "$name" -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data:rw,size=256m -e POSTGRES_HOST_AUTH_METHOD=trust \
    -e POSTGRES_DB=bsv_identity_isolated postgres:17 >/dev/null
port=$(docker port "$name" 5432 | sed -n 's/^127.0.0.1://p')
export BSV_APP_ENV=isolated BSV_AUTH_PROVIDER=isolated BSV_DB_SSLMODE=disable BSV_PG_TEST_CONTAINER="$name"
export BSV_DB_A_URL="postgresql+psycopg://postgres@127.0.0.1:$port/bsv_identity_isolated"
export BSV_DB_B_READONLY_URL="postgresql+psycopg://bsv_reference@127.0.0.1:$port/bsv_identity_isolated"
export BSV_IDENTITY_PG_RESTORE_URL="postgresql+psycopg://postgres@127.0.0.1:$port/bsv_identity_isolated_restore"
export BSV_LOCAL_ARCHIVE_DIR="$tmp/archives" BSV_BACKUP_KEY_FILE="$tmp/key"
unset BSV_DATA_SOURCES_FILE
for attempt in {1..40}; do
    if docker exec "$name" pg_isready -h 127.0.0.1 -U postgres -d bsv_identity_isolated >/dev/null; then break; fi
    sleep 0.5
done
docker exec "$name" createdb -U postgres bsv_identity_isolated_restore
docker exec "$name" psql -U postgres -d bsv_identity_isolated -v ON_ERROR_STOP=1 \
    -c 'CREATE ROLE bsv_reference LOGIN; ALTER ROLE bsv_reference SET default_transaction_read_only = on;'
python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
python -m alembic -c platform/lighthouse/identity/alembic.ini downgrade base
python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
# Run matching PG17 clients inside the same disposable container.
mkdir "$tmp/bin"
cat > "$tmp/bin/pg_dump" <<'SH'
#!/usr/bin/env bash
exec docker exec -i -e PGHOST -e PGUSER -e PGDATABASE -e PGSSLMODE -e PGPORT=5432 "$BSV_PG_TEST_CONTAINER" pg_dump "$@"
SH
cat > "$tmp/bin/pg_restore" <<'SH'
#!/usr/bin/env bash
argv=("$@")
n=$(($#-1))
exec docker exec -i -e PGHOST -e PGUSER -e PGDATABASE -e PGSSLMODE -e PGPORT=5432 "$BSV_PG_TEST_CONTAINER" pg_restore "${argv[@]:0:n}" < "${argv[n]}"
SH
chmod 700 "$tmp/bin/"*
PATH="$tmp/bin:$PATH" python tests/identity/pg/check.py
if [[ "${1:-}" == --with-apps ]]; then
    docker exec "$name" createdb -U postgres bsv_identity_isolated_clients
    export BSV_DB_PREFLIGHT_CLIENT_URL="postgresql+psycopg://postgres@127.0.0.1:$port/bsv_identity_isolated_clients"
    BSV_DB_A_URL="$BSV_DB_PREFLIGHT_CLIENT_URL" python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
    python -m pytest -q -p no:cacheprovider tests/identity/test_consumers.py
    if [[ -n "${BSV_STAGE_SUPPLY_PYTHON:-}" ]]; then
        python -m pytest -q -p no:cacheprovider tests/identity/test_internal_stage.py tests/identity/test_acceptance_v3.py
    fi
    python -m pytest -q -p no:cacheprovider tests/db_preflight
    if [[ "${2:-}" == --update ]]; then
        python tests/db_preflight/schema_dictionary.py --update
    else
        python tests/db_preflight/schema_dictionary.py
    fi
fi
