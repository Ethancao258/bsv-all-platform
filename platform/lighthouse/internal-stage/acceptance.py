#!/usr/bin/env python3
"""Batch HTTP acceptance for the existing isolated Lighthouse services."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from uuid import uuid4

import httpx

import stage

BASE = "http://127.0.0.1:18760"
API = "/api/v1/identity"
AUTH = "/api/v1/auth"
LEGAL = "DEMO_LEGAL"
ALIAS = {"source_system": "bsv1_pos", "legacy_value": "SYNTH-STAGE-POS-01", "tr_code": "TRA0001"}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GateError(RuntimeError):
    pass


def require(accepted, context):
    if not accepted:
        raise GateError(context)


def call(client, method, path, expected, payload=None, headers=None):
    fields = {"Origin": str(client.base_url).rstrip("/")}
    csrf = client.cookies.get("bsv_csrf")
    if csrf:
        fields["X-CSRF-Token"] = csrf
    fields.update(headers or {})
    response = client.request(method, path, json=payload, headers=fields)
    statuses = (expected,) if isinstance(expected, int) else expected
    # Never include bodies, request headers, or exception messages from a service in reports.
    require(response.status_code in statuses, f"{method} {path.split('?')[0]}: HTTP {response.status_code}, expected {statuses}")
    return response.json() if "application/json" in response.headers.get("content-type", "") else response.text


def case(results, test, evidence, status="PASS", reason=""):
    results.append({"test_id": test, "status": status, "evidence": evidence, "reason": reason})


def read_secret(name):
    path = stage.ROOT / "config" / name
    require(not path.is_symlink(), f"Unsafe isolated credential file: {name}")
    st = path.stat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o077,
            f"Unsafe isolated credential permissions: {name}")
    value = path.read_text().strip()
    require(bool(value), f"Missing isolated credential: {name}")
    return value


def qualification(operator, target, code, run_id, start, end):
    call(operator, "POST", API + "/qualifications", 201,
         {"tr_code": target, "legal_entity_id": LEGAL, "qualification_code": code,
          "learning_credential_id": f"SYNTH-V3-{code}-{run_id}", "source_evidence_ref": "SYNTHETIC-STAGE-ACCEPTANCE",
          "effective_from": start, "effective_to": end})


def exercise(base, passwords, pin, results, write, run_id):
    with ExitStack() as stack:
        clients = [stack.enter_context(httpx.Client(base_url=base, timeout=10, trust_env=False)) for _ in range(4)]
        one, two, three, anon = clients
        ready = call(anon, "GET", "/health/ready", 200)
        require(all(ready.get(key) == value for key, value in
                    {"status": "ready", "database": "A", "mode": "isolated"}.items()), "Not the isolated identity gateway")
        case(results, "RELEASE_HEALTH", {"health": "ready", "mode": "isolated"})
        call(anon, "GET", API + "/me", 401)
        call(anon, "GET", "/api/state", 401)
        call(anon, "GET", "/supply-ui/api/me", 401)
        call(anon, "GET", "/internal-unknown-control-route", 404)
        call(anon, "POST", API + "/pos-session", 404, {})
        call(anon, "POST", AUTH + "/isolated/login", 403, {"username": "reviewer1", "password": "INVALID-SYNTHETIC"},
             {"Origin": "https://not-authorized.invalid"})
        case(results, "ANONYMOUS_SECURITY", {"identity": 401, "pos": 401, "supply": 401, "unknown": 404, "cross_origin": 403})

        for i, browser in enumerate(clients[:3] if write else clients[:2], start=1):
            call(browser, "POST", AUTH + "/isolated/login", 200,
                 {"username": f"reviewer{i}", "password": passwords[i - 1]})
            session = call(browser, "GET", AUTH + "/session", 200)
            expected = f"TRA000{i}" if i < 3 else session.get("tr_code")
            require(bool(re.fullmatch(r"TR[A-Z][0-9]{4}", expected or "")) and
                    session.get("tr_code") == expected and session.get("app_env") == "isolated",
                    "Unexpected synthetic administrator identity or environment")
            if i == 3:
                require(expected not in {"TRA0001", "TRA0002"}, "Third approver must be distinct")
        case(results, "LOGIN", {"admins_logged_in": 3 if write else 2, "cross_site_login_rejected": True})
        subject = call(one, "GET", API + "/me", 200)
        require((subject.get("tr_code"), subject.get("emp_code"), subject.get("bm_code")) ==
                ("TRA0001", "EMPA0001", "BMA0001") and LEGAL in subject.get("active_legal_entities", []),
                "Synthetic identity code chain or legal membership differs")
        case(results, "IDENTITY", {"same_suffix": True, "new_person_created_by_acceptance": False})
        staff = call(one, "GET", API + "/admin/people?legal_entity_id=DEMO_LEGAL&q=TRA0002", 200)
        require([person.get("tr_code") for person in staff["people"]] == ["TRA0002"], "HQ synthetic lookup failed")
        call(one, "GET", API + "/admin/people?legal_entity_id=OUTSIDE_ACCEPTANCE&q=TRA0002", 403)
        case(results, "HQ", {"synthetic_lookup": 200, "cross_entity": 403})

        mapping = {"legal_entity_id": LEGAL, "rows": [ALIAS]}
        known = call(one, "POST", API + "/legacy-import/dry-run", 200, mapping)
        records = known["records"]
        require(known["write_count"] == 0 and len(records) == 1 and records[0]["tr_code"] == "TRA0001"
                and records[0]["issues"] == ["ALREADY_MAPPED"], "Existing synthetic POS mapping not verified")
        if write:
            body = {**mapping, "evidence_ref": "SYNTH-V3-EXISTING-ALIAS", "reason": f"Acceptance {run_id}"}
            repeat = call(two, "POST", API + "/legacy-import/commit", 200, body)
            require(repeat["write_count"] == 0 and repeat["created_alias_ids"] == [], "Idempotent alias wrote a new row")
            changed = {**body, "rows": [{**ALIAS, "tr_code": "TRA0002"}]}
            call(two, "POST", API + "/legacy-import/commit", 409, changed)
        case(results, "LEGACY_ALIAS", {"existing_mapping": True, "write_count": 0, "conflict_checked": write})
        for path in ("/", "/staff", "/hq", "/pos", "/supply-ui/hq/supply", "/supply-ui/inspector/supply", "/cocktail/"):
            call(anon, "GET", path, 200)
        call(anon, "GET", "/craft/", 404)
        case(results, "MENU_AND_ROUTES", {"cocktail": 200, "craft": 404, "work_routes": 6})
        if not write:
            case(results, "POS", {}, "NOT_RUN", "Use --execute-isolated after operator approval")
            return
        exercise_writes(one, two, three, subject, pin, results, run_id)


def exercise_writes(one, two, three, subject, pin, results, run_id):
    clock = datetime.now(timezone.utc)
    start, end = (clock - timedelta(minutes=1)).isoformat(), (clock + timedelta(minutes=12)).isoformat()
    operations = {"pos.order.read": "POS_SERVICE", "pos.order.create": "POS_SERVICE",
                  "supply.receive": "SUPPLY_SAFETY", "quality.independent.submit": "QUALITY_INSPECTOR"}
    grants = []
    cleanup = {"legal_entity_id": LEGAL, "reason": f"Acceptance finalization {run_id}"}
    existing = {item["action"] for item in subject["grants"]
                if item["legal_entity_id"] == LEGAL and item["store_id"] in (None, "BSVT")}
    require(not (existing & operations.keys()),
            "Existing business grants present. Preserve them and wait for any previous acceptance grants to expire")
    have = {item["code"] for item in subject["qualifications"]}
    visit = None
    pos_headers = {}
    try:
        for code in sorted(set(operations.values()) - have):
            qualification(two, "TRA0001", code, run_id, start, end)
        for action in operations:
            request = {"tr_code": "TRA0001", "legal_entity_id": LEGAL, "store_id": "BSVT", "role": "staff",
                       "action": action, "valid_from": start, "valid_to": end, "reason": f"Acceptance temporary grant {run_id}"}
            gid = call(two, "POST", API + "/grants", 201, request)["grant_id"]
            call(two, "POST", API + f"/grants/{gid}/approve", 403, cleanup)
            call(one, "POST", API + f"/grants/{gid}/approve", 403, cleanup)
            grants.append(gid)
            call(three, "POST", API + f"/grants/{gid}/approve", 200, cleanup)
        case(results, "TWO_PERSON", {"scoped_grants": len(grants), "requester_and_beneficiary_denied": True,
                                     "distinct_approver": True, "ttl_minutes": 12})

        credentials = {"store_id": "BSVT", "confirmed_store_id": "BSVT", "staff_code": "STAGEPOS01", "pin": pin}
        wrong_store = {**credentials, "store_id": "BSVS", "confirmed_store_id": "BSVS"}
        call(one, "POST", "/api/login", (401, 403), wrong_store)
        call(one, "POST", "/api/login", 200, credentials)
        state = call(one, "GET", "/api/state", 200)
        require(state.get("payments_enabled") is False and state.get("mode") == "staging", "POS is not isolated")
        require(any(item["id"] == "C000001" for item in state["products"]), "Expected synthetic test product unavailable")
        pos_headers = {"X-BSV-CSRF": state["csrf"]}
        occupied = {row["seat_id"] for row in state["visits"] if row["status"] == "OPEN"}
        seats = [row["id"] for row in state["seats"] if row["id"].startswith("BSVT-SEAT-")
                 and row["id"] not in occupied and row.get("enabled") and row.get("cleaning_state") != "DIRTY"]
        require(bool(seats), "No available isolated BSVT seat")
        open_args = {"seat_id": seats[0], "acceptance_run": run_id}
        try:
            opened = call(one, "POST", "/api/seats/open", 200, open_args, pos_headers)
            require(opened["new"] is True, "Seat was already in use. Existing visits are untouched")
        except httpx.RequestError:
            # The server deduplicates this exact synthetic run and seat.
            opened = call(one, "POST", "/api/seats/open", 200, open_args, pos_headers)
        visit = opened["visit_id"]
        own_visit = {"visit_id": visit, "acceptance_run": run_id}
        call(one, "POST", "/api/drafts/add", 200, {**own_visit, "product_id": "C000001"}, pos_headers)
        call(one, "POST", "/api/orders/submit", 403, {**own_visit, "pay_now": True}, pos_headers)
        unpaid = call(one, "POST", "/api/orders/submit", 200, {**own_visit, "pay_now": False}, pos_headers)
        require(unpaid.get("pay_now") is False and unpaid.get("payment_verified") is False
                and unpaid.get("checkout_id") is None, "Test order must remain unpaid")
        check_order = call(one, "GET", "/api/receipt?visit_id=" + visit, 200)["visit"]
        require(check_order["checkouts"] == [] and len(check_order["lines"]) == 1
                and check_order["lines"][0]["product_id"] == "C000001",
                "Stored order must have one synthetic item and no checkout")
        archived = call(one, "POST", "/api/visits/cancel", 200, own_visit, pos_headers)
        require(archived.get("archived") is True, "Synthetic POS test visit archival not confirmed")
        case(results, "POS", {"unpaid_order_recorded": True, "archived_test_visit": visit,
                              "cross_store_denied": True, "payment_denied": True})
        visit = None

        me = call(one, "GET", "/supply-ui/api/me", 200)
        require(me.get("employee_id") == "EMPA0001" and me["role_stores"].get("receive") == ["BSVT"]
                and me["role_stores"].get("inspect_independent") == ["BSVT"], "Shared supply and QA authorization mismatch")
        receipt = {"request_id": str(uuid4()), "scanned_codes": ["SYNTHETIC"], "expected_version": 1}
        call(one, "POST", "/supply-ui/api/shipments/SYNTH-V3/receive", 503, receipt)
        check = {"request_id": str(uuid4()), "store_id": "BSVT", "kind": "independent", "results": {}}
        call(one, "POST", "/supply-ui/api/inspections", 403, {**check, "store_id": "BSVS"})
        call(one, "POST", "/supply-ui/api/inspections", 503, check)
        case(results, "SUPPLY_AND_QA", {"authorized_read": 200, "unapproved_store": 403, "central_write": 503})
        case(results, "CENTRAL_D_E", {}, "BLOCKED", "Central ledger and independent review write APIs not connected")
    finally:
        if visit:
            try:
                call(one, "POST", "/api/visits/cancel", 200, {"visit_id": visit, "acceptance_run": run_id}, pos_headers)
            except (GateError, httpx.HTTPError, ValueError):
                case(results, "POS_CLEANUP", {"visit_id": visit}, "BLOCKED", "Test visit outcome requires local audit")
        for grant in reversed(grants):
            try:
                call(two, "POST", API + f"/grants/{grant}/revoke", 200, cleanup)
            except (GateError, httpx.HTTPError, ValueError):
                case(results, "GRANT_CLEANUP", {"grant_id": grant}, "BLOCKED", "Temporary grant expires automatically")
    call(one, "GET", "/api/state", 401)
    call(one, "GET", "/supply-ui/api/me", 403)
    call(one, "POST", AUTH + "/logout", 200, {})
    call(one, "GET", AUTH + "/session", 401)
    case(results, "REVOCATION", {"pos": 401, "supply": 403, "session": 401})


def host_evidence(results, sha):
    observed = stage.host_evidence(require_all=True)
    require(observed["deployed_sha"] == sha, "Host does not run the expected SHA")
    pg = stage.as_user("postgres", stage.PG / "psql", "-XAt", "-h", stage.DATA / "postgres", "-p", "18764",
                       "-d", "postgres", "-U", stage.user("postgres"), "-v", "ON_ERROR_STOP=1", "-c", "SHOW server_version_num",
                       stdout=subprocess.PIPE)
    require(pg.stdout.strip().isdigit() and int(pg.stdout.strip()) // 10_000 == 17, "Isolation database is not PG17")
    memory = Path("/proc/meminfo").read_text()
    free = shutil.disk_usage(stage.ROOT).free
    available = re.search(r"^MemAvailable:\s+(\d+)", memory, re.M)
    case(results, "HOST", {**observed, "cpu_count": os.cpu_count(),
                           "pg_major": 17, "disk_free_bytes": free,
                           "memory_available_kib": int(available.group(1)) if available else None})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--execute-isolated", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[a-f0-9]{40}", args.expected_sha):
        parser.error("Use sudo with the approved complete --expected-sha")
    results = []
    run_id = str(uuid4())
    report = {"schema_version": "1.0", "version": args.expected_sha, "time": stamp(),
              "mode": "isolated-host", "run_id": run_id, "tests": results}
    try:
        with stage.locked():
            host_evidence(results, args.expected_sha)
            passwords = [read_secret("reviewer1"), read_secret("reviewer2")]
            if args.execute_isolated:
                passwords.append(read_secret("reviewer3"))
            exercise(BASE, passwords, read_secret("pos-pin") if args.execute_isolated else "",
                     results, args.execute_isolated, run_id)
    except GateError as error:
        case(results, "ACCEPTANCE_GATE", {}, "BLOCKED", str(error))
    except (OSError, RuntimeError, ValueError, KeyError, httpx.HTTPError, subprocess.SubprocessError) as error:
        case(results, "ACCEPTANCE_GATE", {}, "BLOCKED", f"Local acceptance stopped: {type(error).__name__}")
    case(results, "HOST_ROLLBACK", {}, "NOT_RUN", "Recovery is a separate explicit host action")
    accepted = args.execute_isolated and all(x["status"] != "BLOCKED" or x["test_id"] == "CENTRAL_D_E" for x in results)
    report["state"] = "STAGING_ACCEPTED" if accepted else "STAGING_BLOCKED"
    report["scope"] = "approved isolated identity/POS and read-only supply/QA; no production approval"
    for result in results:
        result.update(version=report["version"], time=report["time"], mode=report["mode"])
    if any(r["test_id"] == "HOST" and r["status"] == "PASS" for r in results):
        try:
            from bsvctl import record_acceptance
            with stage.locked():
                require(stage.sha_at(stage.ROOT / "current") == args.expected_sha, "Version changed during acceptance")
                report["report_ref"] = record_acceptance(report)
        except (ValueError, OSError, KeyError, GateError):
            case(results, "REPORT_PERSISTENCE", {}, "BLOCKED", "Cannot store approved host evidence")
            results[-1].update(version=report["version"], time=report["time"], mode=report["mode"])
            accepted = False
            report["state"] = "STAGING_BLOCKED"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(report["state"])
    return 0 if accepted else 2


if __name__ == "__main__":
    sys.exit(main())
