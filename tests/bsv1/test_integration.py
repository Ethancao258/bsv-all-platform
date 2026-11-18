"""Exercise BSV1 through HTTP on an ephemeral port and isolated SQLite."""
import http.client
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/api/bsv1"))
import app
import bsv_one


class StoreFlow(unittest.TestCase):
    def test_order_production_and_demo_checkout(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DB_PATH", Path(tmp) / "integration.sqlite3"):
            app.init_db()
            pin = str(secrets.randbelow(900000000) + 100000000)
            with app.tx() as db:
                staff_id = app.uid()
                salt = secrets.token_bytes(16)
                db.execute("INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES(?,?,?,?,?,1)",
                           (staff_id, "TEST-INTEGRATION", salt.hex(), app.pin_hash(pin, salt), "MANAGER"))
                db.execute("INSERT INTO staff_store_access(staff_id,store_id) VALUES(?,?)", (staff_id, "BSVM"))
                db.execute("INSERT INTO bsv_hq_roles(staff_id,role,granted_at) VALUES(?,'HQ_ADMIN',?)",
                           (staff_id, bsv_one.now()))
                current = bsv_one.current(db, "BSVM")
                staff = dict(db.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone())
                draft = bsv_one.draft(db, staff, "BSVM", current["layout"], current["version"])
                bsv_one.publish(db, staff, "BSVM", draft["revision_id"])
            with app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler) as server:
                worker = threading.Thread(target=server.serve_forever)
                worker.start()
                conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                cookie = csrf = ""
                def request(path, payload=None, status=200):
                    headers = {"Cookie": cookie, "X-BSV-CSRF": csrf, "Content-Type": "application/json"}
                    conn.request("GET" if payload is None else "POST", path,
                                 None if payload is None else json.dumps(payload), headers)
                    response = conn.getresponse()
                    body = json.loads(response.read())
                    self.assertEqual(response.status, status, body)
                    return body, response
                try:
                    login = dict(store_id="BSVS", confirmed_store_id="BSVS", staff_code="TEST-INTEGRATION", pin=pin)
                    request("/api/login", login, status=401)
                    login.update(store_id="BSVM", confirmed_store_id="BSVM")
                    _, response = request("/api/login", login)
                    cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                    state, _ = request("/api/state")
                    csrf = state["csrf"]
                    opened, _ = request("/api/seats/open", {"seat_id": "BSVM-SEAT-0001"})
                    visit = {"visit_id": opened["visit_id"]}
                    request("/api/drafts/add", dict(visit, product_id="C000001"))
                    order, _ = request("/api/orders/submit", dict(visit, pay_now=False))
                    self.assertGreater(order["amount_cents"], 0)
                    self.assertFalse(order["payment_verified"])
                    with app.db_read() as db:
                        line = db.execute("SELECT id,product_id FROM order_lines").fetchone()
                        self.assertEqual(line["product_id"], "C000001")
                        task = {"line_id": line["id"]}
                    recipe, _ = request("/api/production/recipe?line_id=" + line["id"])
                    self.assertEqual(recipe["fixed_id"], "C000001")
                    request("/api/production/claim", task)
                    request("/api/production/finished", task)
                    request("/api/production/serve", dict(task, confirmed_delivered=True))
                    checkout, _ = request("/api/checkouts/settle-demo", visit)
                    self.assertEqual(checkout["amount_cents"], order["amount_cents"])
                    self.assertFalse(checkout["payment_verified"])
                    request("/api/visits/depart-demo", dict(visit, print_preference="NONE"))
                    with app.db_read() as db:
                        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                finally:
                    conn.close()
                    server.shutdown()
                    worker.join()


class ReferenceRouting(unittest.TestCase):
    def test_verified_fallback_is_read_only_and_scoped(self):
        from bsv_data_router import Unavailable
        from reference_adapter import read_reference

        class Stub:
            def __init__(self, label):
                self.label = label

            def read(self, domain, key):
                return self.label, domain, key

        args = ("published_catalog", "C000001", Stub("primary"), Stub("snapshot"))
        route, payload = read_reference(*args, primary_healthy=True, snapshot_valid=True)
        self.assertEqual((route.source, payload[0]), ("DB_A", "primary"))
        route, payload = read_reference(*args, primary_healthy=False, snapshot_valid=True)
        self.assertEqual((route.source, payload[0]), ("DB_B", "snapshot"))
        self.assertTrue(route.read_only and route.stale)
        with self.assertRaises(Unavailable):
            read_reference(*args, primary_healthy=False, snapshot_valid=False)
        with self.assertRaises(Unavailable):
            read_reference("orders", *args[1:], primary_healthy=False, snapshot_valid=True)
