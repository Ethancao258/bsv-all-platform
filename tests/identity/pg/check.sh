#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 && "${BSV_IDENTITY_PG_ROOT_TEST:-}" != 1 ]]; then
    root_env=("PATH=$PATH" "PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
              "BSV_IDENTITY_PG_ROOT_TEST=1")
    for key in BSV_STAGE_SUPPLY_PYTHON BSV_STAGE_BROWSER BSV_STAGE_UI_ARTIFACTS BSV_G1_UI_ARTIFACTS; do
        if [[ -n "${!key:-}" ]]; then root_env+=("$key=${!key}"); fi
    done
    exec sudo env "${root_env[@]}" bash "$0" "$@"
fi
cd "$(dirname "$0")/../../.."
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"
tmp=$(mktemp -d)
name="bsv-identity-test-${tmp##*.}-$$"
cleanup() { docker rm -fv "$name" >/dev/null 2>&1 || true; rm -rf "$tmp"; }
trap cleanup EXIT
pg_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker run -d --name "$name" -p 127.0.0.1::5432 --tmpfs /var/lib/postgresql/data:rw,size=256m \
    -e POSTGRES_PASSWORD="$pg_password" -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
    -e POSTGRES_INITDB_ARGS='--auth-local=peer' -e POSTGRES_DB=bsv_identity_isolated postgres:17 >/dev/null
port=$(docker port "$name" 5432 | sed -n 's/^127.0.0.1://p')
export BSV_APP_ENV=isolated BSV_AUTH_PROVIDER=isolated BSV_DB_SSLMODE=disable BSV_PG_TEST_CONTAINER="$name" BSV_PG_TEST_PASSWORD="$pg_password" BSV_PG_TEST_PORT="$port"
export BSV_DB_A_URL="postgresql+psycopg://bsv_internal_app:apppw@127.0.0.1:$port/bsv_identity_isolated"
export BSV_DB_B_READONLY_URL="postgresql+psycopg://bsv_reference:referencepw@127.0.0.1:$port/bsv_identity_isolated"
export BSV_IDENTITY_PG_RESTORE_URL="postgresql+psycopg://bsv_internal_app:apppw@127.0.0.1:$port/bsv_identity_isolated_restore"
export BSV_CATALOG_PG_URL="postgresql+psycopg://bsv_catalog_importer:catalogpw@127.0.0.1:$port/bsv_all_prod"
catalog_restore_db="bsv_identity_isolated_catalog_restore_${tmp##*.}_$$"
export BSV_CATALOG_PG_RESTORE_URL="postgresql+psycopg://bsvint-postgres@127.0.0.1:18764/$catalog_restore_db"
export BSV_LOCAL_ARCHIVE_DIR="$tmp/archives" BSV_BACKUP_KEY_FILE="$tmp/key"
unset BSV_DATA_SOURCES_FILE
for attempt in {1..40}; do
    if docker exec "$name" pg_isready -U postgres -d bsv_identity_isolated >/dev/null; then break; fi
    sleep 0.5
done
docker_gateway=$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')
cat > "$tmp/pg_hba.conf" <<EOF
local all all peer
host bsv_identity_isolated bsv_internal_app 127.0.0.1/32 scram-sha-256
host bsv_identity_isolated bsv_internal_app ${docker_gateway}/32 scram-sha-256
host bsv_identity_isolated bsv_reference 127.0.0.1/32 scram-sha-256
host bsv_identity_isolated bsv_reference ${docker_gateway}/32 scram-sha-256
host bsv_identity_isolated_restore bsv_internal_app 127.0.0.1/32 scram-sha-256
host bsv_identity_isolated_restore bsv_internal_app ${docker_gateway}/32 scram-sha-256
host bsv_identity_isolated_clients bsv_internal_app 127.0.0.1/32 scram-sha-256
host bsv_identity_isolated_clients bsv_internal_app ${docker_gateway}/32 scram-sha-256
host bsv_identity_isolated_stage bsv_internal_app 127.0.0.1/32 scram-sha-256
host bsv_identity_isolated_stage bsv_internal_app ${docker_gateway}/32 scram-sha-256
host bsv_all_prod bsv_catalog_importer 127.0.0.1/32 scram-sha-256
host bsv_all_prod bsv_catalog_importer ${docker_gateway}/32 scram-sha-256
EOF
chmod 600 "$tmp/pg_hba.conf"
docker cp "$tmp/pg_hba.conf" "$name:/tmp/pg_hba.conf"
docker exec "$name" chown postgres:postgres /tmp/pg_hba.conf
docker exec "$name" chmod 600 /tmp/pg_hba.conf
docker exec "$name" mv /tmp/pg_hba.conf /var/lib/postgresql/data/pg_hba.conf
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c 'SELECT pg_reload_conf()' >/dev/null
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN IF EXISTS (SELECT 1 FROM pg_hba_file_rules WHERE error IS NOT NULL) THEN RAISE EXCEPTION 'invalid HBA'; END IF; END \$\$;" >/dev/null
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
    "CREATE ROLE bsv_internal_app LOGIN PASSWORD 'apppw' NOSUPERUSER NOCREATEDB NOCREATEROLE; CREATE ROLE bsv_catalog_importer LOGIN PASSWORD 'catalogpw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;" >/dev/null
docker exec --user postgres "$name" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
    'ALTER DATABASE bsv_identity_isolated OWNER TO bsv_internal_app' >/dev/null
docker exec --user postgres "$name" createdb -U postgres -T template0 -O bsv_internal_app bsv_identity_isolated_restore
docker exec --user postgres "$name" createdb -U postgres -T template0 -O bsv_catalog_importer bsv_all_prod
docker exec --user postgres "$name" createdb -U postgres -T template0 -O bsv_catalog_importer "$catalog_restore_db"
docker exec --user postgres "$name" psql -U postgres -d bsv_identity_isolated -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE bsv_reference LOGIN PASSWORD 'referencepw'; ALTER ROLE bsv_reference SET default_transaction_read_only = on;"
python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
python -m alembic -c platform/lighthouse/identity/alembic.ini downgrade base
python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
# Run matching PG17 clients inside the same disposable container.
mkdir "$tmp/bin"
cat > "$tmp/bin/pg_dump" <<'SH'
#!/usr/bin/env bash
exec docker exec -i -e PGHOST -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE -e PGPORT=5432 "$BSV_PG_TEST_CONTAINER" pg_dump "$@"
SH
cat > "$tmp/bin/pg_restore" <<'SH'
#!/usr/bin/env bash
argv=("$@")
n=$(($#-1))
exec docker exec -i -e PGHOST -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE -e PGPORT=5432 "$BSV_PG_TEST_CONTAINER" pg_restore "${argv[@]:0:n}" < "${argv[n]}"
SH
chmod 700 "$tmp/bin/"*
if ! id -u bsvint-postgres >/dev/null 2>&1; then sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin bsvint-postgres; fi
docker_group=$(stat -c '%G' /var/run/docker.sock)
sudo usermod -a -G "$docker_group" bsvint-postgres
sudo -u bsvint-postgres docker info >/dev/null
install -d -m 0700 "$tmp/restore-socket"
sudo chown bsvint-postgres:bsvint-postgres "$tmp/restore-socket"
cat > "$tmp/bin/pg_restore_peer" <<SH
#!/usr/bin/env bash
set -euo pipefail
args=("\$@")
exec docker exec -i --user postgres -e PGHOST=/var/run/postgresql -e PGPORT=5432 \
    -e PGUSER=postgres -e PGDATABASE="\$PGDATABASE" "$name" pg_restore "\${args[@]}"
SH
chmod 711 "$tmp"
chmod 755 "$tmp/bin" "$tmp/bin/pg_restore_peer"
export BSV_PG_RESTORE_TEST_SOCKET="$tmp/restore-socket" BSV_PG_RESTORE_TEST_BINARY="$tmp/bin/pg_restore_peer"
PATH="$tmp/bin:$PATH" python tests/identity/pg/check.py
if [[ "${1:-}" == --with-apps ]]; then
    docker exec --user postgres "$name" createdb -U postgres -O bsv_internal_app bsv_identity_isolated_clients
    export BSV_DB_PREFLIGHT_CLIENT_URL="postgresql+psycopg://bsv_internal_app:apppw@127.0.0.1:$port/bsv_identity_isolated_clients"
    BSV_DB_A_URL="$BSV_DB_PREFLIGHT_CLIENT_URL" python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_identity_0001
    python -m pytest -q -p no:cacheprovider tests/identity/test_consumers.py
    if [[ -n "${BSV_STAGE_SUPPLY_PYTHON:-}" ]]; then
        # The full internal-stage UI includes Academy and must use the current
        # isolated Academy migration. Keep the field-dictionary DB at the
        # historical identity-only revision used by the existing contract.
        docker exec --user postgres "$name" createdb -U postgres -O bsv_internal_app bsv_identity_isolated_stage
        stage_db_url="postgresql+psycopg://bsv_internal_app:apppw@127.0.0.1:$port/bsv_identity_isolated_stage"
        export BSV_DB_A_URL="$stage_db_url"
        python -m alembic -c platform/lighthouse/identity/alembic.ini upgrade bsv_academy_0002
        BSV_DB_PREFLIGHT_STAGE_URL="$stage_db_url" python -m pytest -q -p no:cacheprovider tests/identity/test_internal_stage.py tests/identity/test_acceptance_v3.py
        export BSV_DB_A_URL="$BSV_DB_PREFLIGHT_CLIENT_URL"
    fi
    python -m pytest -q -p no:cacheprovider tests/db_preflight
    if [[ "${2:-}" == --update ]]; then
        python tests/db_preflight/schema_dictionary.py --update
    else
        python tests/db_preflight/schema_dictionary.py
    fi
fi
