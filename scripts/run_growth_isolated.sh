#!/usr/bin/env bash
set -euo pipefail
export BSV_GROWTH_ENV=isolated
export BSV_GROWTH_DB_URL="sqlite:////tmp/bsv-growth-isolated-$(id -u).sqlite3"
export BSV_GROWTH_SIGNING_KEY="ISOLATED-ONLY-NOT-SECRET-key-012345678912345"
export BSV_GROWTH_PAYMENT_SIGNING_KEY="ISOLATED-ONLY-PAYMENT-NOT-SECRET-key-0001"
export BSV_GROWTH_STORE_IDS="BSVM,BSVS,BSVT"
exec python3 -m uvicorn services.api.customer_growth.app:app --host 127.0.0.1 --port 8767
