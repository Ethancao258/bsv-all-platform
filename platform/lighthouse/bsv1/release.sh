#!/usr/bin/env bash
# Preflight only, or simulate a version switch in a newly created temp directory.
set -euo pipefail
cd "$(dirname "$0")/../../.."
case "${1:---dry-run}" in
    --dry-run)
        [[ $# -le 1 ]]
        python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)'
        command -v ss >/dev/null
        command -v systemctl >/dev/null
        [[ -z $(ss -H -ltn 'sport = :8767') ]] || { echo 'Staging port already occupied'; exit 1; }
        for path in /opt/bsv-all-bsv1-stage /var/lib/bsv-all-bsv1-stage /etc/bsv-all-bsv1-stage.env /etc/systemd/system/bsv-all-bsv1-stage.service; do
            [[ ! -e "$path" && ! -L "$path" ]] || { echo "Existing staging path: $path"; exit 1; }
        done
        systemctl show -p LoadState -p ActiveState bsv1-preview.service bsv-all-bsv1-stage.service
        echo 'Preflight only. Verify V2.9 service and reverse-proxy routes with the host operator.'
        ;;
    --simulate)
        [[ $# = 1 ]]
        tmp=$(mktemp -d)
        pid=
        cleanup() {
            if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
            rm -rf "$tmp"
        }
        trap cleanup EXIT
        mkdir -p "$tmp/releases/previous" "$tmp/releases/candidate"
        cp -R apps services "$tmp/releases/candidate/"
        export BSV_V9_XLSX="$tmp/test-v9.xlsx" BSV_DB_PATH="$tmp/test.sqlite3"
        export BSV_MODE=local BSV_PORT=0 PYTHONDONTWRITEBYTECODE=1
        python3 tests/bsv1/make_fixture.py "$BSV_V9_XLSX"
        ln -s releases/previous "$tmp/current"
        switch() { ln -s "$1" "$tmp/next"; mv -Tf "$tmp/next" "$tmp/current"; }
        switch releases/candidate
        python3 -u - "$tmp/current/services/api/bsv1" > "$tmp/stage.log" 2>&1 <<'PY' &
import sys
sys.path.insert(0, sys.argv[1])
import app
app.init_db()
with app.ThreadingHTTPServer((app.HOST, 0), app.Handler) as server:
    print("PORT=" + str(server.server_port), flush=True)
    server.serve_forever()
PY
        pid=$!
        port=
        for attempt in {1..30}; do
            port=$(sed -n 's/^PORT=//p' "$tmp/stage.log")
            [[ -z "$port" ]] || break
            sleep 0.2
        done
        if [[ -z "$port" ]] || ! python3 platform/lighthouse/bsv1/health.py "$port"; then
            switch releases/previous
            cat "$tmp/stage.log"
            exit 1
        fi
        # Simulate a rejected follow-up release and verify rollback.
        mkdir "$tmp/releases/rejected"
        switch releases/rejected
        if [[ ! -f "$tmp/current/services/api/bsv1/app.py" ]]; then switch releases/candidate; fi
        [[ $(readlink "$tmp/current") == releases/candidate ]]
        kill "$pid"
        wait "$pid" 2>/dev/null || true
        pid=
        python3 -u "$tmp/current/services/api/bsv1/app.py" > "$tmp/boot.log" 2>&1 &
        pid=$!
        for attempt in {1..30}; do
            if grep -q 'BSV1 3.1.0' "$tmp/boot.log"; then break; fi
            sleep 0.2
        done
        kill -0 "$pid"
        grep -q 'BSV1 3.1.0' "$tmp/boot.log"
        echo 'PASS: version switch, health, simulated rollback, and packaged launcher'
        ;;
    *) echo 'Usage: release.sh --dry-run | --simulate' >&2; exit 2 ;;
esac
