"""Real PostgreSQL 17 migration, typed-ID, read-role, API repository and rollback test."""
import os
import json
import secrets
import sys
import tempfile
import threading
import http.client
import importlib.util
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
sys.path.insert(0, str(ROOT))
if os.environ.get("BSV_CATALOG_PG17_TEST") == "1":
    import psycopg
    from psycopg.types.json import Jsonb
else:
    psycopg = None
    Jsonb = None
import bsv_catalog_import as importer
from bsv_catalog_repository import PostgresCatalogReadRepository
import app
_stage_spec = importlib.util.spec_from_file_location(
    "catalog_test_stage", ROOT / "platform/lighthouse/internal-stage/stage.py")
stage = importlib.util.module_from_spec(_stage_spec)
_stage_spec.loader.exec_module(stage)

SHA = "a" * 64


@unittest.skipUnless(os.environ.get("BSV_CATALOG_PG17_TEST") == "1", "requires isolated PostgreSQL 17 container")
class CatalogPostgres17Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = importer._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_setting('server_version_num')::integer")
                version = cur.fetchone()[0]
            if version // 10000 != 17:
                raise AssertionError(f"PostgreSQL 17 required, received {version}")
            cls.migration = importer.migrate(conn)
            if cls.migration not in {"APPLIED+APPLIED+APPLIED", "ALREADY_APPLIED+ALREADY_APPLIED+ALREADY_APPLIED",
                                     "ALREADY_APPLIED+ALREADY_APPLIED+APPLIED"}:
                raise AssertionError(cls.migration)
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO audit.import_batch(batch_id,source_sha256,package_sha256,package_version,status,counts) VALUES (%s,%s,%s,'V2.2','COMMITTED_RAW',%s)",
                                ("11111111-1111-4111-8111-111111111111", SHA, "b" * 64, Jsonb({"synthetic_test_fixture": True})))
                    cur.execute("INSERT INTO core.store(store_id,store_name_zh,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('BSVM','演练店','IMPORTED_RAW',%s,1,'T')", (SHA,))
                    cur.execute("INSERT INTO catalog.product(product_id,name_zh,recipe_text,prep_steps_full,locator_guide,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('C000001','边车','白兰地45ml','摇匀12秒','后酒架一层','IMPORTED_RAW',%s,9,'C')", (SHA,))
                    cur.execute("INSERT INTO catalog.semifinished(semifinished_id,name_zh,storage_condition,transport_condition,content_review_status,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('P000003','油浸章鱼足备料','待核','待核','待审批','IMPORTED_RAW',%s,48,'P')", (SHA,))
                    cur.execute("INSERT INTO catalog.semifinished(semifinished_id,name_zh,storage_condition,transport_condition,content_review_status,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('P000004','romesco酱','待核','待核','待审批','IMPORTED_RAW',%s,51,'P')", (SHA,))
                    cur.execute("INSERT INTO catalog.material(material_id,name_zh,purchase_price_raw,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('M000001','演练物料','30元原文','IMPORTED_RAW',%s,10,'M')", (SHA,))
                    cur.execute("INSERT INTO catalog.bundle(bundle_id,name_zh,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('K000001','演练套餐','IMPORTED_RAW',%s,9,'K')", (SHA,))
                    for rid, output, product, semifinished, row in (
                        ('R000001','C000001','C000001',None,9),
                        ('R000048','P000003',None,'P000003',48),
                        ('R000051','P000004',None,'P000004',51),
                    ):
                        cur.execute("""INSERT INTO catalog.recipe_step(recipe_step_id,record_name,output_link_id,output_product_id,output_semifinished_id,
                                     recipe_text_step,prep_steps_full_step,locator_guide_step,ingest_status,_source_sha256,_excel_row,_source_sheet)
                                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'IMPORTED_RAW',%s,%s,'R')""",
                                    (rid, rid, output, product, semifinished, "制作文字", "完整制作步骤", "寻料指引", SHA, row))
                    fields = [
                        ("catalog.product.product_id", "catalog.product", "商品ID", "PUBLIC"),
                        ("catalog.product.name_zh", "catalog.product", "商品名称", "PUBLIC"),
                        ("catalog.product.recipe_text", "catalog.product", "配方文字", "CONFIDENTIAL"),
                        ("catalog.product.prep_steps_full", "catalog.product", "完整制作步骤", "CONFIDENTIAL"),
                        ("catalog.product.locator_guide", "catalog.product", "寻酒指引", "CONFIDENTIAL"),
                        ("catalog.material.material_id", "catalog.material", "物料ID", "PUBLIC"),
                        ("catalog.material.name_zh", "catalog.material", "物料名称", "INTERNAL"),
                        ("catalog.material.purchase_price_raw", "catalog.material", "采购价", "RESTRICTED"),
                    ]
                    for index, (key, table, header, permission) in enumerate(fields, 1):
                        cur.execute("""INSERT INTO audit.field_dictionary(source_sha256,dictionary_row,semantic_key,target_table,column_name,source_sheet,source_col,source_header_zh,data_type,permission_class)
                                     VALUES (%s,%s,%s,%s,%s,'C','A',%s,'TEXT',%s)""",
                                    (SHA, index, key, table, key.rsplit('.', 1)[1], header, permission))
                    records = [
                        ("core.store", "BSVM", 1, {"门店ID":"BSVM","门店名称":"演练店"}),
                        ("catalog.product", "C000001", 9, {"商品ID":"C000001","商品名称":"边车","配方文字":"白兰地45ml","完整制作步骤":"摇匀12秒","寻酒指引":"后酒架一层"}),
                        ("catalog.semifinished", "P000003", 48, {"半成品ID":"P000003","半成品名称":"油浸章鱼足备料"}),
                        ("catalog.semifinished", "P000004", 51, {"半成品ID":"P000004","半成品名称":"romesco酱"}),
                        ("catalog.material", "M000001", 10, {"物料ID":"M000001","物料名称":"演练物料","采购价":"30元原文"}),
                        ("catalog.bundle", "K000001", 9, {"套餐ID":"K000001","套餐名称":"演练套餐"}),
                        ("catalog.recipe_step", "R000001", 9, {"工序记录ID":"R000001","完整制作步骤｜制作记录":"完整制作步骤"}),
                        ("catalog.recipe_step", "R000048", 48, {"工序记录ID":"R000048","完整制作步骤｜制作记录":"P关联步骤"}),
                        ("catalog.recipe_step", "R000051", 51, {"工序记录ID":"R000051","完整制作步骤｜制作记录":"P关联步骤2"}),
                    ]
                    for table, rid, rowno, raw in records:
                        cur.execute("INSERT INTO audit.source_record(source_sha256,entity_table,record_id,excel_row,raw_fields) VALUES (%s,%s,%s,%s,%s)",
                                    (SHA, table, rid, rowno, Jsonb(raw)))
                    cur.execute("INSERT INTO catalog.active_content(singleton_id,source_sha256,content_revision,activation_status) VALUES (1,%s,1,'IMPORTED_RAW')", (SHA,))
        finally:
            conn.close()
        cls.sqlite_temp = tempfile.TemporaryDirectory(prefix="bsv-pos-pg-catalog-http-")
        app.DB_PATH = Path(cls.sqlite_temp.name) / "operational.sqlite3"
        app.MODE = "local"
        app.init_db()
        with app.tx() as db:
            salt = secrets.token_bytes(16)
            db.execute("INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES(?,?,?,?,?,1)",
                       ("PG-CATALOG-STAFF", "PG-CATALOG-STAFF", salt.hex(), app.pin_hash("975310", salt), "STAFF"))
            db.execute("INSERT INTO staff_store_access(staff_id,store_id) VALUES(?,?)", ("PG-CATALOG-STAFF", "BSVM"))
        cls.http_server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.http_thread = threading.Thread(target=cls.http_server.serve_forever, daemon=True)
        cls.http_thread.start()
        cls.http_port = cls.http_server.server_address[1]

    def test_migration_replay_and_pg_read_role(self):
        admin_conn = importer._connect()
        try:
            self.assertEqual(importer.migrate(admin_conn), "ALREADY_APPLIED+ALREADY_APPLIED+ALREADY_APPLIED")
            layout, relations = importer._catalog_layout_state(admin_conn)
            self.assertEqual(layout, "MANAGED_SCHEMA")
            self.assertEqual(relations, importer.EXPECTED_CATALOG_RELATIONS)
            self.assertIn(("audit", "excel_formula_index_formula_id_seq", "SEQUENCE"), relations)
            owned_sequence = admin_conn.execute(
                "SELECT pg_get_serial_sequence('audit.excel_formula_index','formula_id')"
            ).fetchone()[0]
            self.assertEqual(owned_sequence, "audit.excel_formula_index_formula_id_seq")
        finally:
            admin_conn.close()
        # Exercise a real SCRAM login as the exact non-superuser used by the
        # service. SET SESSION AUTHORIZATION requires superuser and would hide
        # mistakes in the runtime connection contract.
        conn = psycopg.connect(os.environ["BSV_DB_URL"])
        try:
            conn.autocommit = True
            conn.execute("SET ROLE bsv_catalog_reader")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("UPDATE catalog.product SET name_zh='must fail' WHERE product_id='C000001'")
            conn.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT raw_fields FROM audit.source_record LIMIT 1")
            conn.rollback()
            staff_fields = conn.execute("SELECT raw_fields FROM audit.source_record_staff WHERE record_id='C000001'").fetchone()[0]
            self.assertNotIn("配方文字", staff_fields)
            self.assertNotIn("采购价", staff_fields)
            conn.execute("SET ROLE bsv_catalog_confidential_reader")
            fields = conn.execute("SELECT raw_fields FROM audit.source_record_confidential WHERE record_id='C000001'").fetchone()[0]
            self.assertIn("配方文字", fields)
            restricted = conn.execute("SELECT raw_fields FROM audit.source_record_confidential WHERE record_id='M000001'").fetchone()[0]
            self.assertNotIn("采购价", restricted)
        finally:
            conn.close()

    def test_pg_api_repository_reads_active_pg_rows_and_both_recipe_targets(self):
        repo = PostgresCatalogReadRepository()
        self.assertEqual(repo.source()["source"], "postgresql")
        product = repo.get_product("C000001", allow_confidential=True)
        self.assertEqual(product["name"], "边车")
        self.assertEqual(product["attributes"]["recipe_text"], "白兰地45ml")
        self.assertEqual(product["source"]["source"], "postgresql")
        self.assertFalse(product["sale_enabled"])
        search = repo.search("C000001", "C")
        self.assertEqual(search["items"][0]["product_id"], "C000001")
        recipe = repo.recipe("P000003", allow_confidential=True)
        self.assertEqual([item["record_id"] for item in recipe["recipe_operations"]], ["R000048"])
        recipe2 = repo.recipe("P000004", allow_confidential=True)
        self.assertEqual([item["record_id"] for item in recipe2["recipe_operations"]], ["R000051"])
        low = repo.get_product("M000001")
        high = repo.get_product("M000001", allow_confidential=True)
        self.assertNotIn("采购价", low["fields"])
        self.assertIn("采购价", low["withheld_fields"])
        self.assertNotIn("采购价", high["fields"])
        self.assertIn("采购价", high["withheld_fields"])

    def test_real_pos_http_reads_postgres_not_excel_or_sqlite_and_fails_closed(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.http_port, timeout=5)
        try:
            connection.request("GET", "/api/v1/catalog/products/C000001")
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            connection.request("POST", "/api/login", json.dumps({"store_id":"BSVM","confirmed_store_id":"BSVM",
                              "staff_code":"PG-CATALOG-STAFF","pin":"975310"}),
                              {"Content-Type":"application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            cookie = response.getheader("Set-Cookie").split(";",1)[0]
            response.read()
            connection.request("GET", "/api/v1/catalog/products/C000001", headers={"Cookie":cookie})
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(body["source"]["source"], "postgresql")
            self.assertEqual(body["name"], "边车")
            self.assertEqual(body["attributes"]["recipe_steps"], "摇匀12秒")
            connection.request("GET", "/api/v1/catalog/products/P000003/recipe", headers={"Cookie":cookie})
            recipe = json.loads(connection.getresponse().read())
            self.assertEqual(recipe["recipe_operations"][0]["record_id"], "R000048")
            connection.request("GET", "/api/v1/catalog/products/M000001", headers={"Cookie":cookie})
            material = json.loads(connection.getresponse().read())
            self.assertNotIn("采购价", material["fields"])
            with app.db_read() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='bsv_v9_record'").fetchone()[0], 0)
            connection.request("GET", "/api/menu-preview?store_id=BSVM", headers={"Cookie":cookie})
            menu = json.loads(connection.getresponse().read())
            self.assertEqual(menu["catalog_publication"], "BLOCKED_RAW_NOT_APPROVED")
            self.assertEqual(menu["products"], [])
            self.assertNotIn("C000001", {item["id"] for item in menu["products"]})
            with mock.patch.dict(os.environ, {"BSV_DB_URL": "postgresql://postgres@127.0.0.1:1/bsv_all_prod"}):
                connection.request("GET", "/api/v1/catalog/products/C000001", headers={"Cookie":cookie})
                unavailable = connection.getresponse()
                result = json.loads(unavailable.read())
                self.assertEqual(unavailable.status, 503)
                self.assertEqual(result["code"], "CATALOG_SOURCE_UNAVAILABLE")
        finally:
            connection.close()

    def test_real_employee_browser_reads_pg_catalog_without_order_creation(self):
        """The employee catalog screen renders PG17 API data through the real POS page."""
        import shutil
        from playwright.sync_api import expect, sync_playwright

        with sync_playwright() as playwright:
            chromium = shutil.which("chromium")
            executable = chromium if chromium else None
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="zh-CN")
                page.goto(f"http://127.0.0.1:{self.http_port}/")
                page.locator("#loginDistrict").select_option("北京市密云区")
                page.locator("#loginStore").select_option("BSVM")
                page.locator("#staffCode").fill("PG-CATALOG-STAFF")
                page.locator("#staffPin").fill("975310")
                page.locator("#loginForm button[type=submit]").click()
                page.locator("#modalConfirm").click()
                expect(page.locator("#staffIdentity")).to_contain_text("BSVM")
                page.get_by_role("button", name="商品资料库").click()
                page.get_by_role("textbox", name="搜索商品").fill("C000001")
                product = page.locator('[data-cid="C000001"]')
                expect(product).to_be_visible()
                expect(page.locator("#catalogSummary")).to_contain_text("PostgreSQL 17")
                product.click()
                expect(page.locator("#catalogDetailModal")).to_contain_text("边车")
                expect(page.locator("#catalogDetailModal")).to_contain_text("白兰地45ml")
                expect(page.locator("#catalogDetailModal")).to_contain_text("摇匀12秒")
                expect(page.locator("#catalogDetailModal")).to_contain_text("后酒架一层")
                with app.db_read() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
            finally:
                browser.close()

    def test_failed_import_transaction_is_atomic_and_revision_activation_rolls_back(self):
        conn = importer._connect()
        try:
            broken_sha = "c" * 64
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with conn.transaction():
                    conn.execute("INSERT INTO audit.import_batch(batch_id,source_sha256,package_sha256,package_version,status,counts) VALUES (%s,%s,%s,'V2.2','COMMITTED_RAW',%s)",
                                 ("22222222-2222-4222-8222-222222222222", broken_sha, "d" * 64, Jsonb({})))
                    conn.execute("INSERT INTO catalog.recipe_step(recipe_step_id,output_link_id,output_product_id,ingest_status,_source_sha256,_excel_row,_source_sheet) VALUES ('R999999','C999999','C999999','IMPORTED_RAW',%s,999,'R')", (broken_sha,))
            self.assertFalse(conn.execute("SELECT 1 FROM audit.import_batch WHERE source_sha256=%s", (broken_sha,)).fetchone())
            conn.commit()
            next_sha = "e" * 64
            with conn.transaction():
                conn.execute("INSERT INTO audit.import_batch(batch_id,source_sha256,package_sha256,package_version,status,counts) VALUES (%s,%s,%s,'V2.2','COMMITTED_RAW',%s)",
                             ("33333333-3333-4333-8333-333333333333", next_sha, "f" * 64, Jsonb({})))
            fake_approval = {"approval_id": "33333333-3333-4333-8333-333333333334",
                             "approver": "ci-operator", "change_id": "CI-ROLLBACK",
                             "hmac_sha256": "0" * 64}
            with mock.patch.object(importer, "_verified_package", return_value=({"source_sha256": next_sha}, "", {})), \
                 mock.patch.object(importer, "_verify_approval", return_value={**fake_approval,
                     "expected_active_source_sha256": SHA}):
                importer.activate_source_revision(next_sha, Path("/tmp/package"), Path("/tmp/package.zip"), Path("/tmp/approval.json"))
            with mock.patch.object(importer, "_verified_package", return_value=({"source_sha256": SHA}, "", {})), \
                 mock.patch.object(importer, "_verify_approval", return_value={**fake_approval,
                     "expected_active_source_sha256": next_sha}):
                importer.activate_source_revision(SHA, Path("/tmp/package"), Path("/tmp/package.zip"), Path("/tmp/approval.json"))
            self.assertEqual(PostgresCatalogReadRepository().source()["sha256"], SHA)
        finally:
            conn.close()

    def test_retry_audit_accepts_only_same_committed_package_and_contract(self):
        import hmac
        import hashlib
        import time
        from unittest.mock import patch

        manifest = {"version": "V2.2", "source_sha256": SHA, "counts": {
            "source_sha256": SHA,
            "counts": {"catalog_product": 1, "catalog_semifinished": 2, "catalog_material": 1,
                       "catalog_bundle": 1, "catalog_bundle_slot": 0, "catalog_store_nps": 0,
                       "catalog_recipe_step": 3, "catalog_price_quote": 0, "core_store": 1,
                       "audit_source_dictionary": 0, "audit_source_legal_path": 0,
                       "audit_source_calc": 0},
            "fields": 8, "mappings": 0, "formulas": 0}}
        with tempfile.TemporaryDirectory(prefix="bsv-catalog-retry-audit-") as directory:
            root = Path(directory)
            package = root / "package"
            approvals = root / "approvals"
            package.mkdir(mode=0o700)
            approvals.mkdir(mode=0o700)
            manifest_path = package / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            archive = root / "workbuddy.zip"
            archive.write_bytes(b"synthetic package bytes for retry-state audit")
            key_path = root / "approval.key"
            key_path.write_bytes(b"K" * 48)
            key_path.chmod(0o600)
            approval_id = "44444444-4444-4444-8444-444444444444"
            approval = {"approval_id": approval_id, "action": "import",
                        "archive_sha256": importer.sha256(archive),
                        "manifest_sha256": importer.sha256(manifest_path),
                        "source_sha256": SHA,
                        "contract_sha256": importer.sha256(ROOT / "config/data-contracts.json"),
                        "expected_active_source_sha256": None, "approver": "ci-operator",
                        "change_id": "ISSUE-40-RETRY", "issued_at": int(time.time())-10,
                        "expires_at": int(time.time())+600}
            approval["hmac_sha256"] = hmac.new(
                key_path.read_bytes(), json.dumps(approval, sort_keys=True, separators=(",", ":")).encode(),
                hashlib.sha256).hexdigest()
            approval_path = approvals / "approval-initial.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            approval_path.chmod(0o600)

            expected = importer.expected_sql_counts(manifest)
            conn = importer._connect()
            try:
                revision = conn.execute("SELECT content_revision FROM catalog.active_content WHERE singleton_id=1").fetchone()[0]
                conn.execute("""UPDATE audit.import_batch SET package_sha256=%s,approval_id=%s,approver=%s,
                             change_id=%s,manifest_sha256=%s,contract_sha256=%s,
                             expected_active_source_sha256=NULL,approval_hmac_sha256=%s
                             WHERE source_sha256=%s""",
                             (importer.sha256(archive), approval_id, approval["approver"], approval["change_id"],
                              approval["manifest_sha256"], approval["contract_sha256"], approval["hmac_sha256"], SHA))
                conn.execute("""INSERT INTO audit.content_activation_event
                             (event_id,source_sha256,prior_source_sha256,content_revision,operation,approval_id,
                              approver,change_id,approval_hmac_sha256)
                             VALUES (%s,%s,NULL,%s,'IMPORT_RAW',%s,%s,%s,%s)""",
                             ("55555555-5555-4555-8555-555555555555", SHA, revision, approval_id,
                              approval["approver"], approval["change_id"], approval["hmac_sha256"]))
                conn.commit()
                actual = importer.query_counts(conn, SHA, expected)
                self.assertEqual(actual, expected)
            finally:
                conn.close()
            env = {"BSV_APP_ENV": "isolated", "BSV_ALLOW_ISOLATED_CATALOG_IMPORT": "1",
                   "BSV_CATALOG_ADMIN_DB_URL": os.environ["BSV_CATALOG_ADMIN_DB_URL"],
                   "BSV_CATALOG_APPROVAL_KEY_FILE": str(key_path)}
            with patch.dict(os.environ, env, clear=False), \
                 patch.object(importer, "_verified_package", return_value=(manifest, importer.sha256(archive), {})):
                state = importer.inspect_existing_import(package, archive, approvals)
                self.assertEqual(state["status"], "SAFE_RESUME_IDEMPOTENT_NOOP")
                self.assertEqual(state["counts"], expected)

                # The retry gate inventories the whole database, not merely
                # catalog/core/audit. Unknown objects must be preserved and
                # rejected before any migration or import can run.
                conn = importer._connect()
                try:
                    conn.execute("CREATE SCHEMA preflight_unregistered")
                    conn.commit()
                    with self.assertRaisesRegex(RuntimeError, "unregistered schemas"):
                        importer.inspect_existing_import(package, archive, approvals)
                    conn.execute("CREATE TABLE preflight_unregistered.keep_me (value TEXT)")
                    conn.commit()
                    with self.assertRaisesRegex(RuntimeError, "unregistered schemas"):
                        importer.inspect_existing_import(package, archive, approvals)
                    conn.execute("DROP SCHEMA preflight_unregistered CASCADE")
                    conn.commit()
                    conn.execute("CREATE SEQUENCE audit.unregistered_preflight_seq")
                    conn.commit()
                    with self.assertRaisesRegex(RuntimeError, "relations are partial or unregistered"):
                        importer.inspect_existing_import(package, archive, approvals)
                    self.assertTrue(conn.execute(
                        "SELECT to_regclass('audit.unregistered_preflight_seq') IS NOT NULL"
                    ).fetchone()[0], "the rejected unknown sequence must remain untouched")
                    conn.execute("DROP SEQUENCE audit.unregistered_preflight_seq")
                    conn.commit()
                    conn.execute("CREATE FUNCTION public.unregistered_preflight_fn() RETURNS integer "
                                 "LANGUAGE SQL AS 'SELECT 1'")
                    conn.commit()
                    with self.assertRaisesRegex(RuntimeError, "callable/type objects"):
                        importer.inspect_existing_import(package, archive, approvals)
                    conn.execute("DROP FUNCTION public.unregistered_preflight_fn()")
                    conn.commit()
                    missing = conn.execute(
                        "SELECT checksum FROM bsv_isolated_migration.applied WHERE version=%s",
                        ("0003_recipe_order_read",)).fetchone()[0].strip()
                    conn.execute("DELETE FROM bsv_isolated_migration.applied WHERE version=%s",
                                 ("0003_recipe_order_read",))
                    conn.commit()
                    with self.assertRaisesRegex(RuntimeError, "migration ledger is incomplete"):
                        importer.inspect_existing_import(package, archive, approvals)
                    conn.execute("INSERT INTO bsv_isolated_migration.applied(version,checksum) VALUES (%s,%s)",
                                 ("0003_recipe_order_read", missing))
                    conn.commit()
                finally:
                    conn.close()

                changed_counts = dict(expected)
                changed_counts["catalog.product"] += 1
                with patch.object(importer, "expected_sql_counts", return_value=changed_counts):
                    with self.assertRaisesRegex(RuntimeError, "persisted catalog rows differ"):
                        importer.inspect_existing_import(package, archive, approvals)

                wrong_manifest = {**manifest, "source_sha256": "c" * 64}
                with patch.object(importer, "_verified_package", return_value=(wrong_manifest, "d" * 64, {})):
                    with self.assertRaisesRegex(RuntimeError, "active catalog state differs"):
                        importer.inspect_existing_import(package, archive, approvals)

    def test_restore_database_identifier_uses_live_pg17_limit(self):
        conn = importer._connect()
        try:
            limit = int(conn.execute("SHOW max_identifier_length").fetchone()[0])
        finally:
            conn.close()
        name = stage.catalog_restore_database_name(
            "a" * 40, limit, timestamp="20261124123456", nonce="0123456789abcdef")
        self.assertEqual(name, "bsvr_aaaaaaaa_20261124123456_0123456789abcdef")
        self.assertLessEqual(len(name.encode("ascii")), limit)
        with self.assertRaisesRegex(RuntimeError, "too small"):
            stage.catalog_restore_database_name(
                "a" * 40, 8, timestamp="20261124123456", nonce="0123456789abcdef")
    def test_zz_production_sale_ledger_preserves_other_domains(self):
        # Synthetic PG17 only. Exercise the live migration and actual production
        # schema gate without changing the isolated fixture's existing relations.
        from bsv_catalog_live import require_live_layout,reject_pending_sale
        migration=ROOT/"platform/lighthouse/bsv1/catalog/live_migrations/0001_sale_release.sql"
        conn=importer._connect()
        try:
            conn.execute(migration.read_text(encoding="utf-8"),prepare=False)
            conn.execute("CREATE SCHEMA IF NOT EXISTS live_other_domain")
            conn.execute("CREATE TABLE live_other_domain.sentinel(id integer PRIMARY KEY)")
            conn.execute("INSERT INTO live_other_domain.sentinel VALUES(1)")
            conn.commit()
            self.assertEqual(require_live_layout(conn),"REGISTERED_LIVE_SCHEMA")
            conn.commit()
            with conn.transaction():
                conn.execute("""INSERT INTO catalog.sale_release(release_id,source_sha256,draft_id,created_by,reviewed_by,legal_entity_id,decisions,items,status)
                                VALUES(%s,%s,%s,'TRA0001','TRA0002','TEST',%s,%s,'PENDING_PROJECTION')""",
                             ("88888888-8888-4888-8888-888888888888",SHA,"f"*32,Jsonb({"C000001":"LIST"}),Jsonb({})))
                with mock.patch.dict(os.environ,{"BSV_APP_ENV":"production","BSV_CATALOG_LIVE":"1"}):
                    with self.assertRaisesRegex(RuntimeError,"pending sale"):reject_pending_sale(conn)
                self.assertEqual(conn.execute("SELECT id FROM live_other_domain.sentinel").fetchone()[0],1)
        finally:
            conn.rollback()
            conn.execute("DROP TABLE IF EXISTS catalog.sale_release")
            conn.execute("DROP SCHEMA IF EXISTS live_other_domain CASCADE")
            conn.commit();conn.close()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "http_server"):
            cls.http_server.shutdown()
            cls.http_server.server_close()
        if hasattr(cls, "sqlite_temp"):
            cls.sqlite_temp.cleanup()


if __name__ == "__main__":
    unittest.main()
