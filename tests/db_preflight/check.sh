#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
bash tests/identity/pg/check.sh --with-apps "$@"
# Real HTTP static menu rendering with the same repository IDs.
python -B tests/menu-v13-1/test_projection.py
python -B tests/menu-v13-1/visual_http.py
