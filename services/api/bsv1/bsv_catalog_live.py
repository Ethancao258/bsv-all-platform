"""Production catalog mode; only already provisioned, registered relations."""
import os
import hashlib

def live_enabled():
    return os.getenv("BSV_APP_ENV")=="production" and os.getenv("BSV_CATALOG_LIVE")=="1"

def import_enabled():
    return ((os.getenv("BSV_APP_ENV")=="isolated" and os.getenv("BSV_ALLOW_ISOLATED_CATALOG_IMPORT")=="1")
            or (live_enabled() and os.getenv("BSV_ALLOW_PRODUCTION_CATALOG_IMPORT")=="1"))

def require_live_layout(conn):
    from bsv_catalog_import import EXPECTED_MIGRATIONS, EXPECTED_CATALOG_RELATIONS
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(),current_setting('server_version_num')::integer,current_user")
        db,version,role=cur.fetchone()
        if db!="bsv_all_prod" or version//10000!=17 or role!="bsv_catalog_importer":
            raise PermissionError("production requires registered PG17 catalog importer role")
        cur.execute("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user")
        if any(cur.fetchone()):raise PermissionError("catalog importer cannot administer cluster")
        cur.execute("SELECT version,checksum FROM bsv_isolated_migration.applied")
        applied={v:h.strip() for v,h in cur.fetchall()}
        if any(applied.get(v)!=hashlib.sha256(p.read_bytes()).hexdigest() for v,p in EXPECTED_MIGRATIONS):
            raise RuntimeError("registered migrations mismatch; no automatic production DDL")
        cur.execute("""SELECT n.nspname,c.relname,CASE WHEN c.relkind IN ('r','p') THEN 'BASE TABLE'
                       WHEN c.relkind='v' THEN 'VIEW' WHEN c.relkind='S' THEN 'SEQUENCE' ELSE c.relkind::text END
                       FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace""")
        if not EXPECTED_CATALOG_RELATIONS.issubset(set(cur.fetchall())):
            raise RuntimeError("registered catalog layout incomplete")
        cur.execute("SELECT to_regclass('catalog.sale_release')")
        if cur.fetchone()[0] is None:raise RuntimeError("approved sale migration required")
    return "REGISTERED_LIVE_SCHEMA"

def reject_pending_sale(conn):
    if live_enabled():
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM catalog.sale_release WHERE status='PENDING_PROJECTION' LIMIT 1")
            if cur.fetchone():raise RuntimeError("finish pending sale projection before raw revision change")
