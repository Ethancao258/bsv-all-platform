"""Versioned HTTP acceptance of approved synthetic V4.1 stage releases."""
import argparse
import base64
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
import re
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from acceptance import ALIAS, API, AUTH, BASE, LEGAL, GateError, call, case, host_evidence, read_secret, require, stamp
import stage

ACADEMY = "/api/v1/academy"
TARGET = "TRA0001"
STORES = ("BSVT", "BSVS")


class Exercise:
    def __init__(self, base, results, run_id):
        self.base = base
        self.results = results
        self.tag = run_id.replace("-", "")[:16].upper()
        self.now = datetime.now(timezone.utc)
        self.cleanups = []

    def cleanup(self, account, path, body):
        self.cleanups.append((account, path, body))

    def post(self, account, path, body=None, expected=200):
        return call(account, "POST", path, expected, body if body is not None else {})

    def grant(self, requester, approver, owner, target, store, action, *, deny_self=False):
        data = {"tr_code": target, "legal_entity_id": LEGAL, "store_id": store, "role": "staff",
                "action": action, "valid_from": (self.now - timedelta(minutes=2)).isoformat(),
                "valid_to": (self.now + timedelta(minutes=20)).isoformat(), "reason": "V4.1 synthetic acceptance " + self.tag}
        grant = self.post(requester, API + "/grants", data, 201)["grant_id"]
        path = API + "/grants/" + grant
        decision = {"legal_entity_id": LEGAL, "reason": "Independent synthetic acceptance " + self.tag}
        if deny_self:
            self.post(requester, path + "/approve", decision, 403)
        self.cleanup(owner, path + "/revoke", decision)
        self.post(approver, path + "/approve", decision)

    def course(self, author, publisher, store, version=1):
        ident = f"SYNTH-{self.tag}-{store or 'GROUP'}"
        path = ACADEMY + "/courses/" + ident + "/" + str(version)
        self.post(author, ACADEMY + "/courses", {
            "course_id": ident, "version": version, "title": "隔离演练课程",
            "store_id": store, "role": "bartender", "passing_score": 80,
            "questions": [{"prompt": "测试题：哪项是本次演练数据？",
                           "options": ["合成记录", "真实资料"], "correct_index": 0}],
            "rights_ref": "SYNTHETIC-ACCEPTANCE", "practical_requirements": "按门店核对演练操作",
        }, 201)
        if version == 1:
            work = call(publisher, "GET", ACADEMY + "/work", 200)
            require(not any(row["course_id"] == ident for row in work["courses"]), "Draft is visible to learners")
            bad_file = base64.b64encode(b"<html><script>synthetic</script></html>").decode()
            self.post(author, path + "/media", {"filename": "synthetic.pdf", "mime": "application/pdf",
                       "content_base64": bad_file, "rights_ref": "SYNTHETIC-ACCEPTANCE"}, 422)
            if not work.get("media_ready"):
                sample = base64.b64encode(b"%PDF-1.4\n%%EOF").decode()
                self.post(author, path + "/media", {"filename": "synthetic.pdf", "mime": "application/pdf",
                           "content_base64": sample, "rights_ref": "SYNTHETIC-ACCEPTANCE"}, 503)
        self.post(author, path + "/publish", expected=403)
        self.post(publisher, path + "/publish")
        self.cleanup(publisher, path + "/retire", {})
        return path

    def theory(self, student, course):
        self.post(student, course + "/enroll")
        self.post(student, course + "/complete")
        failed = self.post(student, course + "/exam", {"answers": [1]})
        require(failed.get("passed") is False, "Incorrect answer cannot pass theory")
        exam = {"answers": [0], "request_id": str(uuid4())}
        passed = self.post(student, course + "/exam", exam)
        require(passed.get("passed") is True, "Correct answer did not pass theory")
        require(self.post(student, course + "/exam", exam) == passed, "Repeated exam counted again")
        self.post(student, course + "/exam", {**exam, "answers": [1]}, 409)

    def practical(self, student, reviewer, path, suffix="FIRST"):
        body = {"tr_code": TARGET, "decision": "verified", "evidence_ref": "SYNTHETIC-" + self.tag + "-" + suffix,
                "reason": "Independent synthetic practical review"}
        self.post(student, path + "/practical", body, 403)
        return self.post(reviewer, path + "/practical", body)

    def shift_body(self, store, *, start=None, end=None):
        return {"tr_code": TARGET, "store_id": store, "role": "bartender",
                "start": start or (self.now - timedelta(minutes=1)).isoformat(),
                "end": end or (self.now + timedelta(minutes=10)).isoformat(),
                "timezone": "Asia/Shanghai", "request_id": str(uuid4())}

    def device(self, registrar, store, suffix):
        ident = f"SYNTH-{self.tag}-{suffix}"
        result = self.post(registrar, ACADEMY + "/devices", {"device_id": ident, "store_id": store}, 201)
        self.cleanup(registrar, f"{ACADEMY}/devices/{ident}/revoke", {})
        return {"device_id": ident, "device_token": result["device_token"], "store_id": store, "confirmed_store_id": store}

    def close(self):
        for account, path, payload in reversed(self.cleanups):
            try:
                self.post(account, path, payload, (200, 409))
            except (GateError, httpx.HTTPError, ValueError):
                case(self.results, "SYNTHETIC_CLEANUP", {}, "BLOCKED", "See this run's synthetic audit trail")


def login(client, index, password):
    call(client, "POST", AUTH + "/isolated/login", 200, {"username": f"reviewer{index}", "password": password})
    sess = call(client, "GET", AUTH + "/session", 200)
    require(sess.get("app_env") == "isolated" and sess.get("linked"), "Unexpected non-isolated session")
    return sess["tr_code"]


def run_flow(base, passwords, results, run_id, browser_check=None):
    with ExitStack() as stack:
        clients = [stack.enter_context(httpx.Client(base_url=base, timeout=12, trust_env=False)) for _ in range(5)]
        employee, reviewer, approver, second, anonymous = clients
        people = [login(client, i, password) for i, (client, password) in enumerate(zip(clients, passwords), 1)]
        require(people[:2] == [TARGET, "TRA0002"] and len(set(people)) == 3, "Synthetic reviewer identities differ")
        require(login(second, 1, passwords[0]) == TARGET, "Second device did not identify the same TR")
        me = call(employee, "GET", API + "/me", 200)
        require(me["emp_code"] == "EMPA0001" and me["bm_code"] == "BMA0001", "Derived identity chain changed")
        call(employee, "GET", API + "/admin/people?legal_entity_id=DEMO_LEGAL&q=TRA0002", 200)
        call(anonymous, "GET", ACADEMY + "/work", 401)
        call(anonymous, "GET", ACADEMY + "/media/" + str(uuid4()), 401)
        call(anonymous, "POST", ACADEMY + "/pos-authorize", 404, {})
        case(results, "IDENTITY", {"same_tr_two_sessions": True, "hq_lookup": 200, "anonymous_denied": True})

        legacy = call(reviewer, "POST", API + "/legacy-import/dry-run", 200, {"legal_entity_id": LEGAL, "rows": [ALIAS]})
        require(legacy["write_count"] == 0 and legacy["records"][0]["issues"] == ["ALREADY_MAPPED"],
                "Existing approved V3 synthetic mapping is missing")
        case(results, "LEGACY_ALIAS", {"write_count": 0, "unchanged": True})
        flow = Exercise(base, results, run_id)
        try:
            business(flow, employee, reviewer, approver, second, people, browser_check)
        finally:
            flow.close()

        for path in ("/", "/staff", "/hq", "/cocktail/", "/supply-ui/inspector/supply"):
            call(anonymous, "GET", path, 200)
        call(anonymous, "GET", "/supply-ui/api/me", 401)
        call(anonymous, "GET", "/craft/", 404)
        case(results, "PRIVATE_UI", {"menu": 200, "craft": 404, "unauthenticated_supply": 401})
        case(results, "CENTRAL_D_E", {}, "BLOCKED", "No approved authoritative supply or inspection writer")


def business(flow, employee, reviewer, approver, second, people, browser_check):
    post = flow.post
    for store in STORES:
        # Two site schedulers distinct from the employee being scheduled.
        flow.grant(employee, approver, employee, people[1], store, "store.shift.write", deny_self=True)
        flow.grant(reviewer, employee, employee, people[2], store, "store.shift.write", deny_self=True)

    for store in STORES:
        flow.grant(reviewer, approver, reviewer, TARGET, store, "learning.course.read")
    general = flow.course(reviewer, employee, None)
    local = flow.course(reviewer, employee, "BSVT")
    alternate = flow.course(reviewer, employee, "BSVS")
    flow.theory(employee, general)
    flow.theory(employee, local)
    flow.theory(employee, alternate)
    post(reviewer, ACADEMY + "/shifts", flow.shift_body("BSVS"), 403)
    post(reviewer, ACADEMY + "/shifts", flow.shift_body("BSVF"), 403)
    flow.practical(employee, reviewer, local)
    post(reviewer, ACADEMY + "/shifts", flow.shift_body("BSVT"), 403)
    for action in ("pos.order.read", "pos.order.create"):
        flow.grant(reviewer, approver, reviewer, TARGET, "BSVT", action, deny_self=True)
    post(reviewer, ACADEMY + "/shifts", flow.shift_body("BSVS"), 403)
    case(flow.results, "TRAINING", {"general_and_store_theory": True, "wrong_answer_not_accepted": True,
                                    "theory_only_denied_at_other_store": True, "self_attestation_denied": True,
                                    "qualified_but_no_grant_denied": True})

    first_terminal = flow.device(reviewer, "BSVT", "01")
    second_terminal = flow.device(reviewer, "BSVT", "02")
    other_terminal = flow.device(reviewer, "BSVS", "03")
    login_path = "/api/pos/device-login"
    post(employee, login_path, first_terminal, 403)
    shift_data = flow.shift_body("BSVT")
    shift = post(reviewer, ACADEMY + "/shifts", shift_data, 201)["shift_id"]
    replay = post(reviewer, ACADEMY + "/shifts", shift_data, (200, 201))
    require(replay["shift_id"] == shift, "Duplicate shift request created a new shift")
    sh = ACADEMY + "/shifts/" + shift
    flow.cleanup(reviewer, sh + "/cancel", {})
    post(reviewer, sh + "/approve", expected=403)
    post(approver, sh + "/approve")
    post(employee, login_path, first_terminal, 403)
    post(employee, sh + "/confirm")
    post(employee, login_path, {**first_terminal, "device_token": "a" * 43}, 403)
    post(employee, login_path, other_terminal, 403)
    post(employee, login_path, first_terminal)
    post(second, login_path, second_terminal)
    for web in (employee, second):
        state = call(web, "GET", "/api/state", 200)
        require(state["store"]["id"] == "BSVT" and state["payments_enabled"] is False, "Wrong store or payment state")
    case(flow.results, "SHIFT", {"same_request_same_shift": True, "requester_approval_denied": True,
                                 "before_confirmation_denied": True})
    pos_order(employee, flow, first_terminal)
    pos_order(second, flow, second_terminal)
    growth_context = growth_pos_flow(employee, flow)
    if browser_check:
        browser = flow.device(reviewer, "BSVT", "WEB")
        browser_check(browser)
    post(reviewer, ACADEMY + f"/devices/{first_terminal['device_id']}/revoke")
    if growth_context:
        # A formerly authorized staff member must lose customer access immediately.
        call(employee, "GET", "/api/v1/growth/staff/guest-context?context=" + growth_context, 403)
    call(employee, "GET", "/api/state", (401, 403))
    call(second, "GET", "/api/state", 200)
    case(flow.results, "POS", {"authorized_terminals": 2, "unpaid_orders": 2, "one_device_revoked": True})

    credential = flow.practical(employee, reviewer, alternate)["credential_id"]
    for action in ("pos.order.read", "pos.order.create"):
        flow.grant(reviewer, approver, reviewer, TARGET, "BSVS", action)
    post(reviewer, ACADEMY + "/shifts", flow.shift_body("BSVS"), 409)
    post(reviewer, sh + "/cancel")
    call(second, "GET", "/api/state", (401, 403))
    other = post(reviewer, ACADEMY + "/shifts", flow.shift_body("BSVS"), 201)["shift_id"]
    target = ACADEMY + "/shifts/" + other
    flow.cleanup(reviewer, target + "/cancel", {})
    post(approver, target + "/approve")
    post(employee, target + "/confirm")
    post(employee, login_path, other_terminal)
    call(employee, "GET", "/api/state", 200)
    post(reviewer, f"{ACADEMY}/credentials/{credential}/revoke")
    call(employee, "GET", "/api/state", (401, 403))
    work = call(employee, "GET", ACADEMY + "/work", 200)
    require(any(row["shift_id"] == other and row["status"] == "NEEDS_REASSIGNMENT" for row in work["shifts"]),
            "Lost credential did not flag the confirmed shift for reassignment")
    flow.practical(employee, reviewer, alternate, "REVIEWED-AGAIN")
    post(employee, login_path, other_terminal)
    call(employee, "GET", "/api/state", 200)

    beijing = ZoneInfo("Asia/Shanghai")
    start = (flow.now.astimezone(beijing) + timedelta(days=1)).replace(hour=23, minute=30, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    overnight = post(reviewer, ACADEMY + "/shifts",
                     flow.shift_body("BSVS", start=start.isoformat(), end=end.isoformat()), 201)
    require(overnight["local_start"] == start.isoformat() and overnight["local_end"] == end.isoformat(),
            "Beijing overnight shift did not preserve both local dates")
    flow.cleanup(reviewer, ACADEMY + "/shifts/" + overnight["shift_id"] + "/cancel", {})
    post(reviewer, ACADEMY + "/shifts",
         flow.shift_body("BSVT", start=(start + timedelta(minutes=15)).astimezone(timezone.utc).isoformat(),
                         end=(end + timedelta(minutes=15)).astimezone(timezone.utc).isoformat()), 409)
    flow.course(reviewer, employee, "BSVS", version=2)
    call(employee, "GET", "/api/state", (401, 403))
    case(flow.results, "CROSS_STORE", {"other_store_theory_not_enough": True, "overlap_denied": True,
                                       "other_store_after_independent_practical_and_shift": True,
                                       "credential_revocation_and_retraining": True, "beijing_midnight": True})


def growth_pos_flow(employee, flow):
    """Real HTTP: customer consent -> live POS visit -> scoped taste -> revocation.

    Uses only private synthetic users/records and never calls a payment writer.
    """
    if not stage_growth_enabled(employee):
        case(flow.results, "GROWTH_POS", {}, "BLOCKED", "Isolated member service not active")
        return None
    scope=call(employee,"GET","/api/v1/growth/staff/me?store_id=BSVT",200)
    require(scope["actor_tr"]==TARGET and scope["can_marketing"] is False,
            "POS staff received an unauthorized marketing or claim role")
    call(employee,"GET","/api/v1/growth/staff/queue?store_id=BSVT",403)
    with httpx.Client(base_url=flow.base, timeout=12, trust_env=False) as customer:
        cid_source = "stage-" + flow.tag.lower()
        call(customer, "POST", "/api/v1/growth/dev/guest-login", 200,
             {"subject":cid_source,"store_id":"BSVT"})
        hdr={"X-Growth-CSRF": customer.cookies["bsv_growth_csrf"]}
        reg=call(customer, "POST", "/api/v1/growth/public/register", 200,
                 {"privacy_accepted":True, "display_name":"合成会员"}, hdr)
        cid=reg["customer_id"]
        reg2=call(customer, "POST", "/api/v1/growth/public/register", 200,
                  {"privacy_accepted":True, "display_name":"重复虚构会员"}, hdr)
        require(reg2["customer_id"]==cid and reg2["already_registered"],"Duplicate customer ID")
        call(customer, "POST", "/api/v1/growth/public/taste", 200,
             {"tags":["果香酸爽"],"share_for_service":True}, hdr)
        configured=call(customer,"GET","/api/v1/growth/public/config",200)["stores"]
        valid=call(customer, "POST", "/api/v1/growth/public/pos-link", 200, {"store_id":"BSVT"}, hdr)
        if "BSVS" in configured:
            wrong=call(customer, "POST", "/api/v1/growth/public/pos-link", 200, {"store_id":"BSVS"}, hdr)
            wrong_token=wrong["token"]
        else:
            # The real Lighthouse isolated baseline authorizes only BSVT.
            # A tampered but otherwise valid token must still fail closed.
            wrong_token=valid["token"][:-1]+("f" if valid["token"][-1]!="f" else "e")
        state=call(employee, "GET", "/api/state", 200)
        headers={"X-BSV-CSRF":state["csrf"]}
        seat=next((x["id"] for x in state["seats"] if x["enabled"] and x["id"]
                   not in {v["seat_id"] for v in state["visits"]}
                   and x.get("cleaning_state")!="DIRTY"), None)
        require(seat is not None,"No available POS seat for member integration")
        run=str(uuid4())
        payload={"seat_id":seat,"acceptance_run":run,"_action_id":str(uuid4())}
        opened=call(employee,"POST","/api/seats/open",200,payload,headers)
        visit=opened["visit_id"]
        context=None
        try:
            call(employee,"GET","/api/visits/customer-context?visit_id="+visit,404)
            call(employee,"POST","/api/visits/customer-link",403,
                 {"visit_id":visit,"proof":wrong_token},headers)
            action_id=str(uuid4())
            link_request={"visit_id":visit,"proof":valid["token"],"_action_id":action_id}
            first=call(employee,"POST","/api/visits/customer-link",200,link_request,headers)
            require(first["linked"] is True,"Customer proof was not bound to this visit")
            retry=call(employee,"POST","/api/visits/customer-link",200,link_request,headers)
            require(retry.get("duplicate") is True,"Lost response retry was not idempotent")
            call(employee,"POST","/api/visits/customer-link",409,
                 {**link_request,"_action_id":str(uuid4())},headers)
            linked=call(employee,"GET","/api/state",200)
            visit_row=next(v for v in linked["visits"] if v["id"]==visit)
            require(visit_row["canonical_customer_linked"] is True and visit_row["member"] is None,
                    "Linked customer incorrectly became a SILVER member or discount")
            result=call(employee,"GET","/api/visits/customer-context?visit_id="+visit,200)
            context=result["context"]
            from urllib.parse import quote
            url="/api/v1/growth/staff/guest-context?context="+quote(context,safe="")
            tags=call(employee,"GET",url,200)
            require(tags["tags"]==["果香酸爽"] and tags["share_for_service"] is True,
                    "POS visit consent was not validated through identity/shift")
            with httpx.Client(base_url=flow.base,timeout=12,trust_env=False) as anonymous:
                call(anonymous,"GET",url,401)
            call(customer,"POST","/api/v1/growth/public/taste",200,
                 {"tags":["果香酸爽"],"share_for_service":False},hdr)
            require(call(employee,"GET",url,200)["tags"]==[],
                    "Revoked sharing persisted in POS customer view")
            case(flow.results,"GROWTH_POS",{
                "stable_customer_id":True,"one_use_proof":True,"scope_denials":True,
                "live_pos_authorization":True,"guest_revocation_immediate":True,
                "payments_enabled":False})
        finally:
            call(employee,"POST","/api/visits/cancel",200,
                 {"visit_id":visit,"acceptance_run":run,"_action_id":str(uuid4())},headers)
        if context:
            call(employee,"GET","/api/v1/growth/staff/guest-context?context="+context,403)
        return context


def stage_growth_enabled(employee):
    response=employee.get("/growth/health")
    return response.status_code==200 and response.json().get("mode")=="isolated"


def pos_order(client, flow, terminal):
    state = call(client, "GET", "/api/state", 200)
    headers = {"X-BSV-CSRF": state["csrf"]}
    occupied = {x["seat_id"] for x in state["visits"]}
    seat = next((x["id"] for x in state["seats"] if x["enabled"] and x["id"] not in occupied
                 and x.get("cleaning_state") != "DIRTY"), None)
    require(seat is not None, "No available synthetic seat")
    run = str(uuid4())
    opened = call(client, "POST", "/api/seats/open", 200,
                  {"seat_id": seat, "acceptance_run": run, "_action_id": str(uuid4())}, headers)
    visit = {"visit_id": opened["visit_id"], "acceptance_run": run}
    try:
        call(client, "POST", "/api/drafts/add", 200,
             {**visit, "product_id": "C000001", "_action_id": str(uuid4())}, headers)
        call(client, "POST", "/api/orders/submit", 403, {**visit, "pay_now": True, "_action_id": str(uuid4())}, headers)
        unpaid = {**visit, "pay_now": False, "_action_id": str(uuid4())}
        order = call(client, "POST", "/api/orders/submit", 200, unpaid, headers)
        require(call(client, "POST", "/api/orders/submit", 200, unpaid, headers) == order,
                "Exact repeat returned a different order receipt")
        require(order["checkout_id"] is None and order["payment_verified"] is False, "Order unexpectedly collected payment")
        saved = call(client, "GET", "/api/receipt?visit_id=" + opened["visit_id"], 200)["visit"]
        require(not saved["checkouts"] and len(saved["lines"]) == 1, "Unpaid order contents differ")
        state = call(client, "GET", "/api/state", 200)
        evidence = [row["detail"]["authority"] for row in state.get("audit", [])
                    if row.get("action") == "SUBMIT_ORDER_TEST" and row.get("target_id") == opened["visit_id"]
                    and "authority" in row.get("detail", {})]
        require(len(evidence) == 1 and evidence[0]["device_id"] == terminal["device_id"]
                and evidence[0]["tr_code"] == TARGET and evidence[0]["store_id"] == "BSVT"
                and evidence[0]["role"] == "bartender" and evidence[0]["shift_id"],
                "Order audit must identify one authorized worker, shift and terminal")
    finally:
        call(client, "POST", "/api/visits/cancel", 200, {**visit, "_action_id": str(uuid4())}, headers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--execute-isolated", action="store_true", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        parser.error("Run with sudo and the full approved SHA")
    rows = []
    report = {"schema_version": "4.1", "version": args.expected_sha, "time": stamp(),
              "mode": "isolated-host", "run_id": str(uuid4()), "tests": rows}
    try:
        with stage.locked():
            host_evidence(rows, args.expected_sha)
            require(stage.database_revision() == stage.ACADEMY_REVISION, "The isolated Academy migration is unavailable")
            run_flow(BASE, [read_secret(f"reviewer{i}") for i in (1, 2, 3)], rows, report["run_id"])
    except GateError as error:
        case(rows, "V4_GATE", {}, "BLOCKED", str(error))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, httpx.HTTPError, stage.subprocess.SubprocessError) as error:
        case(rows, "V4_GATE", {}, "BLOCKED", f"Acceptance stopped: {type(error).__name__}")
    case(rows, "REAL_IMPORT", {}, "NOT_RUN", "No approved real data")
    case(rows, "HOST_RECOVERY", {}, "NOT_RUN", "Recovery is a separate operator-authorized test")
    accepted = all(item["status"] != "BLOCKED" or item["test_id"] == "CENTRAL_D_E" for item in rows)
    report["state"] = "V4_STAGING_ACCEPTED" if accepted else "V4_STAGING_BLOCKED"
    for item in rows:
        item.update(version=report["version"], time=report["time"], mode=report["mode"])
    if any(item["test_id"] == "HOST" and item["status"] == "PASS" for item in rows):
        try:
            from bsvctl import record_acceptance
            with stage.locked():
                require(stage.sha_at(stage.ROOT / "current") == args.expected_sha, "Version changed during acceptance")
                report["report_ref"] = record_acceptance(report)
        except (OSError, ValueError, KeyError, GateError):
            case(rows, "REPORT_PERSISTENCE", {}, "BLOCKED", "Cannot associate this run with approved host release")
            rows[-1].update(version=report["version"], time=report["time"], mode=report["mode"])
            accepted = False
            report["state"] = "V4_STAGING_BLOCKED"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(report["state"])
    return 0 if accepted else 2


if __name__ == "__main__":
    sys.exit(main())
