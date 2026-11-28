"""Read-only SUP59 inventory-authority metadata preflight; never print DSN or rows."""
import json
import os
import sys

from services.api.supply.config import load_settings
from services.api.supply.central_d_runtime import schema_report
from services.api.supply.central_source_adapter import organization_from_env, pinned

def main():
    result={"checks":{},"production_ready":False}
    checks=result["checks"]
    try:
        settings=load_settings()
        checks["remote_configuration"]={"ok":settings.mode=="remote","configured":{k:bool(v.primary) for k,v in settings.sources.items()}}
    except Exception as exc:
        checks["remote_configuration"]={"ok":False,"error_type":type(exc).__name__}
    try:
        org=organization_from_env()
        checks["organization_projection"]={"ok":True,"store_count":len(org["stores"])}
    except Exception as exc:
        checks["organization_projection"]={"ok":False,"error_type":type(exc).__name__}
    try:
        policy=pinned(os.environ["BSV_SUP59_POLICY_FILE"],os.environ["BSV_SUP59_POLICY_SHA256"])
        checks["policy_projection"]={"ok":isinstance(policy.get("policies"),list),"policy_count":len(policy["policies"])}
    except Exception as exc:
        checks["policy_projection"]={"ok":False,"error_type":type(exc).__name__}
    try:
        import psycopg
        with psycopg.connect(os.environ["BSV_SUP59_D_DSN"],connect_timeout=5,options="-c default_transaction_read_only=on") as conn:
            report=schema_report(conn)
            checks["inventory_schema"]={"ok":report["compatible_columns"],**report}
    except Exception as exc:
        checks["inventory_schema"]={"ok":False,"error_type":type(exc).__name__}
    result["metadata_ready"]=all(x.get("ok") is True for x in checks.values())
    result["next"]="OWNER_MAPPING_AND_REAL_E2E_REQUIRED"
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["metadata_ready"] else 2

if __name__=="__main__":
    sys.exit(main())
