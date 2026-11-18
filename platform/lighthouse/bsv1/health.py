"""Check the loopback BSV1 staging process."""
import json
import sys
from urllib.request import ProxyHandler, build_opener

port = int(sys.argv[1])
with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
    result = json.load(response)
if (result.get("service") != "BSV1-multi-store" or result.get("payments") is not False
        or not result.get("checks") or not all(item["ok"] for item in result["checks"])):
    raise SystemExit("BSV1 health check failed")
print("BSV1 healthy")
