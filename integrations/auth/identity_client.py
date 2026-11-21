"""POS client for authoritative A-backed identity; never caches a decision."""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_identity(path, data, headers):
    origin = os.environ.get("BSV_POS_IDENTITY_URL", "")
    try:
        target = urlsplit(origin)
        loopback = target.scheme == "http" and target.hostname in ("127.0.0.1", "::1", "localhost")
        if (not target.hostname or (target.scheme != "https" and not loopback)
                or target.username or target.password or target.query or target.fragment
                or target.path not in ("", "/")):
            return None
        request = Request(origin.rstrip("/") + path, data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json", **headers})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=3) as response:
            result = json.loads(response.read(8193))
            return result if isinstance(result, dict) else None
    except HTTPError as error:
        return {"http_status": error.code}
    except (URLError, TimeoutError, ValueError, OSError):
        return None


def authorize_pos(session, staff_id, store_id, action):
    service_token = os.environ.get("BSV_POS_IDENTITY_TOKEN", "")
    try:
        legal = json.loads(os.environ.get("BSV_POS_STORE_LEGAL_JSON", "{}")).get(store_id)
    except (ValueError, AttributeError):
        return False
    if not session or not legal or not service_token:
        return False
    data = {"legacy_staff_id": staff_id, "legal_entity_id": legal, "store_id": store_id, "action": action}
    decision = request_identity("/api/v1/identity/pos-session", data, {
        "X-BSV-Service-Token": service_token, "Authorization": "Bearer " + session,
    }) or {}
    return decision.get("allowed") is True and decision.get("decision_source") == "A"


def authorize_device(session, store_id, device_id, device_token, action):
    service_token = os.environ.get("BSV_POS_IDENTITY_TOKEN", "")
    if not session:
        return {"reason": "AUTH_REQUIRED"}
    if not service_token:
        return {"reason": "IDENTITY_UNAVAILABLE"}
    data = {"store_id": store_id, "device_id": device_id, "device_token": device_token, "action": action}
    decision = request_identity("/api/v1/academy/pos-authorize", data, {
        "X-BSV-Service-Token": service_token, "Authorization": "Bearer " + session,
    }) or {}
    if decision.get("http_status") == 401:
        return {"reason": "AUTH_REQUIRED"}
    if decision.get("decision_source") != "A":
        return {"reason": "IDENTITY_UNAVAILABLE"}
    if decision.get("allowed") is not True:
        return {"reason": decision.get("reason")}
    if (decision.get("store_id") != store_id or decision.get("device_id") != device_id
            or not isinstance(decision.get("tr_code"), str)
            or not re.fullmatch(r"TR[A-Z][0-9]{4}", decision["tr_code"])
            or not isinstance(decision.get("shift_id"), str) or not decision["shift_id"]
            or not isinstance(decision.get("role"), str) or not decision["role"]):
        return {"reason": "IDENTITY_UNAVAILABLE"}
    return decision


def authorize_hq_layout(session, store_id, action, legal_entity_id):
    """Ask identity.A for one uncached HQ map read decision. Never infer scope locally."""
    service_token = os.environ.get("BSV_POS_LAYOUT_SERVICE_TOKEN", "")
    if not session or not service_token:
        return {"reason": "IDENTITY_UNAVAILABLE"}
    if action != "hq.layout.read" or not legal_entity_id:
        return {"reason": "STORE_UNAUTHORIZED"}
    decision = request_identity("/api/v1/identity/hq-layout-session", {
        "action": action, "legal_entity_id": legal_entity_id, "store_id": store_id,
    }, {"X-BSV-Service-Token": service_token, "Authorization": "Bearer " + session}) or {}
    if decision.get("http_status") == 401:
        return {"reason": "AUTH_REQUIRED"}
    if decision.get("decision_source") != "A" or decision.get("cache_ttl_seconds") != 0:
        return {"reason": "IDENTITY_UNAVAILABLE"}
    if decision.get("allowed") is not True:
        return {"reason": "HQ_LAYOUT_FORBIDDEN"}
    if (decision.get("action") != action or decision.get("store_id") != store_id
            or decision.get("legal_entity_id") != legal_entity_id
            or not isinstance(decision.get("actor_tr_code"), str)
            or not re.fullmatch(r"TR[ABCDEFGHJKLMNPQRSTUVWXYZ][0-9]{4}", decision["actor_tr_code"])):
        return {"reason": "IDENTITY_UNAVAILABLE"}
    return decision


def revoke_browser_session(session, csrf):
    if not (session and csrf and re.fullmatch(r"[A-Za-z0-9_-]{1,150}", session)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,150}", csrf)):
        return False
    data = request_identity("/api/v1/auth/logout", {}, {
        "Cookie": f"bsv_identity_session={session}; bsv_csrf={csrf}", "X-CSRF-Token": csrf,
    }) or {}
    return data.get("signed_out") is True
