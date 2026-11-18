"""Generate/verify the field dictionary from synthetic SQLite and migrated PG17."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile

from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "contracts/database/field-dictionary.json"


def tables(engine, schema=None):
    inspector = inspect(engine)
    result = {}
    for name in sorted(inspector.get_table_names(schema=schema)):
        if name == "alembic_version":
            continue
        options = {"schema": schema}
        result[name] = {
            "columns": [{"name":c["name"],"type":str(c["type"]),"nullable":c["nullable"],"default":c.get("default")}
                        for c in inspector.get_columns(name, **options)],
            "primary_key": inspector.get_pk_constraint(name, **options)["constrained_columns"],
            "foreign_keys": [{k:f[k] for k in ("constrained_columns","referred_schema","referred_table","referred_columns","options")}
                             for f in inspector.get_foreign_keys(name, **options)],
            "unique": [u["column_names"] for u in inspector.get_unique_constraints(name, **options)],
            "checks": [c["sqltext"] for c in inspector.get_check_constraints(name, **options)],
            "indexes": [{"name":i["name"],"columns":i["column_names"],"unique":i["unique"]}
                        for i in inspector.get_indexes(name, **options)],
        }
    # PG reflection omits procedures/triggers; SQLite includes them in sqlite_schema.
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            rows=connection.exec_driver_sql("SELECT name,tbl_name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY 1")
        else:
            rows=connection.exec_driver_sql("""SELECT t.tgname,c.relname,pg_get_triggerdef(t.oid)
                 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE NOT t.tgisinternal AND n.nspname=%s ORDER BY 2,1""",(schema or "public",))
        for name,table,sql in rows:
            if table in result:
                result[table].setdefault("triggers",[]).append({"name":name,"definition":sql})
    return result


def generate(url):
    from sqlalchemy.engine import make_url

    address = make_url(url)
    if address.host != "127.0.0.1" or address.database != "bsv_identity_isolated_clients":
        raise ValueError("Dictionary must use the disposable preflight database")
    pg=create_engine(url)
    try:
        result={"cloudbase":{"status":"UNKNOWN_G0","tables":None},
                "postgres17_identity_isolated":tables(pg),
                "postgres17_supply_candidate":tables(pg,"supply"),
                "postgres17_quality_test_fixture":tables(pg,"preflight_quality")}
    finally:
        pg.dispose()
    with tempfile.TemporaryDirectory() as folder:
        tmp=Path(folder)
        workbook=tmp/"synthetic.xlsx"
        runpy.run_path(str(ROOT / "tests/bsv1/make_fixture.py"))["write_fixture"](workbook)
        os.environ.update(BSV_V9_XLSX=str(workbook),BSV_DB_PATH=str(tmp/"pos.sqlite3"),BSV_MODE="local")
        sys.path.insert(0,str(ROOT/"services/api/bsv1"))
        from services.api.bsv1 import app
        from services.api.supply.demo import DemoCentral
        from services.api.supply.cache import LocalCache
        app.init_db()
        DemoCentral(tmp/"supply"/"demo.sqlite3")
        cache=LocalCache(tmp/"cache")
        for name,path in {
            "sqlite_pos_local":app.DB_PATH, "sqlite_supply_demo":tmp/"supply"/"demo.sqlite3",
            "sqlite_supply_cache":cache.path,
        }.items():
            engine=create_engine("sqlite:///"+str(path))
            try:
                result[name]=tables(engine)
            finally:
                engine.dispose()
    return result


if __name__=="__main__":
    flags=argparse.ArgumentParser(description=__doc__)
    flags.add_argument("--update",action="store_true")
    args=flags.parse_args()
    data=generate(os.environ["BSV_DB_PREFLIGHT_CLIENT_URL"])
    crosswalk=json.loads((ROOT/"contracts/database/entity-crosswalk.json").read_bytes())["entities"]
    owners=json.loads((ROOT/"config/data-ownership.json").read_bytes())["key_owners"]
    assert {key:row["owner"] for key,row in crosswalk.items()} == owners
    for row in crosswalk.values():
        assert row["cloudbase"] == "UNKNOWN_G0"
        assert set(row["evidence_tables"]) <= set(data.get(row["source_schema"], {}))
    value=json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if args.update:
        OUTPUT.write_text(value)
    else:
        assert OUTPUT.read_text()==value,"Field dictionary changed; review schema diff before updating"
    print("PASS: field dictionary", {key:len(tables) for key,tables in data.items() if key!="cloudbase"})
