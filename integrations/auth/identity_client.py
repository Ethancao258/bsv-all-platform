"""POS client for authoritative A-backed identity; never caches a decision."""
import json
import os
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def authorize_pos(session, staff_id, store_id, action):
    origin = os.environ.get("BSV_POS_IDENTITY_URL", "")
    target = urlsplit(origin)
    loopback = target.scheme == "http" and target.hostname in ("127.0.0.1", "::1", "localhost")
    service_token = os.environ.get("BSV_POS_IDENTITY_TOKEN", "")
    try:
        legal = json.loads(os.environ.get("BSV_POS_STORE_LEGAL_JSON", "{}")).get(store_id)
    except (ValueError, AttributeError):
        return False
    if (not session or not legal or not service_token or not target.hostname
            or (target.scheme != "https" and not loopback) or target.username or target.password
            or target.query or target.fragment or target.path not in ("", "/")):
        return False
    data = {"legacy_staff_id":staff_id, "legal_entity_id":legal, "store_id":store_id, "action":action}
    request = Request(origin.rstrip("/") + "/api/v1/identity/pos-session",
                      data=json.dumps(data).encode(), headers={"Content-Type":"application/json",
                      "X-BSV-Service-Token":service_token, "Authorization":"Bearer "+session})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=3) as response:
            decision = json.load(response)
        return decision.get("allowed") is True and decision.get("decision_source") == "A"
    except (URLError, TimeoutError, ValueError, AttributeError, OSError):
        return False
