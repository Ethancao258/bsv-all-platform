#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONDONTWRITEBYTECODE=1
site=apps/guest-web/bsv1/site
for script in "$site"/entry-redirect.js "$site"/cocktail/assets/*.js; do node --check "$script"; done
python3 tests/menu-v13-1/test_maintenance.py
python3 tests/menu-v13-1/test_projection.py
node tests/menu-v13-1/test_runtime.js
python3 tests/menu-v13-1/browser_smoke.py
python3 tests/menu-v13-1/visual_http.py
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 platform/edgeone/menu/build.py "$tmp/preview.zip"
python3 platform/edgeone/menu/build.py "$tmp/repeat.zip"
cmp "$tmp/preview.zip" "$tmp/repeat.zip"
python3 -m zipfile -t "$tmp/preview.zip"
