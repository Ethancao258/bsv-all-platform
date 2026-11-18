#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export PYTHONPYCACHEPREFIX="$tmp/pycache"
if [[ -z ${BSV_V9_XLSX:-} ]]; then
    export BSV_V9_XLSX="$tmp/synthetic-v9.xlsx"
    python3 tests/bsv1/make_fixture.py "$BSV_V9_XLSX"
fi
python3 -m compileall -q services/api/bsv1 tests/bsv1
for script in apps/{store-console,hq-console,guest-web}/bsv1/*.js; do
    node --check "$script"
done
for script in tests/bsv1/*.sh platform/lighthouse/bsv1/*.sh; do
    [[ ! -f "$script" ]] || bash -n "$script"
done
python3 -m unittest discover -s tests/bsv1 -v
