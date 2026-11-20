"""V4 binding, command scope and shared-terminal tests on temporary SQLite."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/api/bsv1"))
import app
import bsv_one


class DevicePos(unittest.TestCase):
    def test_terminal_authority_changes_expire_local_session_without_legacy_pin_bypass(self):
        flags = {"BSV_POS_DEVICE_REQUIRED": "1", "BSV_POS_IDENTITY_REQUIRED": "1",
                 "BSV_POS_INTERNAL_STAGE": "1", "BSV_PRIVATE_SSH_TUNNEL": "1"}
        state = {"allowed": True}
        device = "terminal-test"
        device_token = "Synthetic-test-device-BSVT-0001"

        def authoritative(session, store, terminal, token, action):
            if (store, terminal, token) != ("BSVT", device, device_token):
                return {"reason": "DEVICE_UNVERIFIED"}
            if not state["allowed"]:
                return {"reason": "SHIFT_INACTIVE"}
            tr = "TRA0001" if session == "worker-one-cookie" else "TRA0002"
            return {"allowed": True, "tr_code": tr, "store_id": store, "device_id": terminal,
                    "shift_id": "TEST-SHIFT", "role": "bartender"}

        client = type("MockCampus", (), {"authorize_device": staticmethod(authoritative),
                     "revoke_browser_session": staticmethod(lambda session, csrf: True)})
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, flags), \
                patch.object(app, "DB_PATH", Path(folder) / "pos.sqlite3"), patch.object(app, "MODE", "staging"), \
                patch.object(app, "identity_client", return_value=client):
            app.init_db()
            with app.tx() as db:
                setup = "synthetic-test-admin"
                db.execute("INSERT INTO staff VALUES (?,?,'dead','unused','MANAGER',1)", (setup, setup))
                db.execute("INSERT INTO bsv_hq_roles(staff_id,role,granted_at) VALUES (?,'HQ_ADMIN',?)",
                           (setup, bsv_one.now()))
                staff = dict(db.execute("SELECT * FROM staff WHERE id=?", (setup,)).fetchone())
                current = bsv_one.current(db, "BSVT")
                draft = bsv_one.draft(db, staff, "BSVT", current["layout"], current["version"])
                bsv_one.publish(db, staff, "BSVT", draft["revision_id"])
            with app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler) as server:
                worker = Thread(target=server.serve_forever)
                worker.start()
                origin = "http://127.0.0.1:" + str(server.server_port)
                credentials = {"store_id": "BSVT", "confirmed_store_id": "BSVT", "device_id": device,
                               "device_token": device_token}

                def request(path, expected, cookies="", body=None, *, csrf="", site=origin):
                    with_connection = http.client.HTTPConnection(*server.server_address, timeout=4)
                    try:
                        headers = {"Origin": site, "Content-Type": "application/json",
                                   "Cookie": cookies, "X-CSRF-Token": "test-csrf", "X-BSV-CSRF": csrf}
                        with_connection.request("GET" if body is None else "POST", path,
                                                headers=headers, body=None if body is None else json.dumps(body))
                        result = with_connection.getresponse()
                        data = json.loads(result.read())
                        self.assertEqual(result.status, expected, data)
                        return data, [v.split(";",1)[0] for k,v in result.getheaders() if k.lower() == "set-cookie"]
                    finally:
                        with_connection.close()

                def initial(who):
                    return f"bsv_identity_session=worker-{who}-cookie; bsv_csrf=test-csrf"

                try:
                    self.assertTrue(request("/api/bootstrap", 200)[0]["device_required"])
                    request("/api/login", 403, initial("one"), {"staff_code":"STAGEPOS01"})
                    request("/api/pos/device-login", 403, initial("one"), credentials, site="https://elsewhere.invalid")
                    _, added = request("/api/pos/device-login", 200, initial("one"), credentials)
                    # Occurs across two independent HTTP clients taking turns on one registered terminal.
                    first = "; ".join([initial("one"), *added])
                    first_state = request("/api/state", 200, first)[0]
                    self.assertEqual(first_state["staff"]["shift"]["tr_code"], "TRA0001")
                    csrf = first_state["csrf"]
                    opened = request("/api/seats/open", 200, first,
                                     {"seat_id":"BSVT-SEAT-0001","_action_id":"test-open-0001"}, csrf=csrf)[0]
                    visit = opened["visit_id"]
                    request("/api/drafts/add", 200, first,
                            {"visit_id":visit,"product_id":"C000001","_action_id":"test-draft-0001"}, csrf=csrf)
                    submit = {"visit_id":visit,"pay_now":False,"_action_id":"test-submit-0001"}
                    unpaid = request("/api/orders/submit", 200, first, submit, csrf=csrf)[0]
                    self.assertEqual(request("/api/orders/submit", 200, first, submit, csrf=csrf)[0], unpaid)
                    self.assertEqual(unpaid["request_id"], "test-submit-0001")
                    self.assertFalse(unpaid["payment_verified"])
                    self.assertEqual(request("/api/pos/commands/test-submit-0001", 200, first)[0]["result"], unpaid)
                    self.assertEqual(request("/api/orders/submit", 409, first,
                                             dict(submit,pay_now=True),csrf=csrf)[0]["code"],"ACTION_ID_CONFLICT")
                    request("/api/orders/submit", 403, first,
                            dict(submit,pay_now=True,_action_id="test-cash-0001"),csrf=csrf)
                    crossed = first.replace("worker-one-cookie", "worker-two-cookie")
                    self.assertEqual(request("/api/state", 403, crossed)[0]["code"], "POS_SESSION_CHANGED")
                    state["allowed"] = False
                    self.assertEqual(request("/api/state", 403, first)[0]["code"], "SHIFT_INACTIVE")
                    state["allowed"] = True
                    first_device = next(cookie for cookie in added if cookie.startswith("bsv_pos_device="))
                    _, replacement = request("/api/pos/device-login", 200, "; ".join([initial("two"), first_device]),
                                             {"store_id":"BSVT","confirmed_store_id":"BSVT"})
                    request("/api/state", 401, first)
                    current = "; ".join([initial("two"), first_device, *replacement])
                    staff = request("/api/state", 200, current)[0]
                    self.assertEqual(staff["staff"]["shift"]["tr_code"], "TRA0002")
                    self.assertEqual(request("/api/pos/commands/test-submit-0001", 404, current)[0]["status"],
                                     "NOT_CONFIRMED")
                    _, cleared = request("/api/logout", 200, current, {}, csrf=staff["csrf"])
                    self.assertIn("bsv_pos_v4_session=", cleared)
                    self.assertNotIn("bsv_session=", cleared)
                    self.assertIn("bsv_identity_session=", cleared)
                    request("/api/state", 401, current)
                finally:
                    server.shutdown()
                    worker.join(6)
            with app.db_read() as db:
                self.assertEqual({(row["tr_code"],row["staff_id"]) for row in
                                  db.execute("SELECT * FROM bsv_pos_tr_projection")},
                                 {("TRA0001","TRA0001"),("TRA0002","TRA0002")})
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 28)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM order_lines").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM demo_checkouts").fetchone()[0], 0)
                details = json.loads(db.execute("SELECT detail_json FROM audit_events "
                                                "WHERE action='SUBMIT_ORDER_TEST'").fetchone()[0])
                self.assertEqual(details["order_id"], unpaid["order_id"])
                self.assertEqual(details["authority"], first_state["staff"]["shift"])
