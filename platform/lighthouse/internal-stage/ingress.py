"""Loopback-only HTTP ingress for the SSH-forwarded internal test edition."""
import os
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
PORTS = {"identity": 18761, "pos": 18762, "supply": 18763}
UPSTREAM = {key: f"http://127.0.0.1:{int(os.getenv('BSV_STAGE_'+key.upper()+'_PORT', port))}"
            for key, port in PORTS.items()}
INBOUND = {b"accept", b"content-type", b"cookie", b"origin", b"x-bsv-csrf", b"x-csrf-token"}
OUTBOUND = {b"content-type", b"cache-control", b"set-cookie", b"content-disposition",
            b"content-security-policy", b"x-content-type-options", b"x-frame-options", b"referrer-policy"}
LIMIT = 4 * 1024 * 1024


def upstream(path):
    if path.startswith("/supply-ui/"):
        return "supply", path.removeprefix("/supply-ui")
    if path in {"/identity", "/staff", "/hq", "/health/ready"} or path.startswith(
            ("/api/v1/", "/hq-assets/")) or path in {"/assets/common.js", "/assets/staff.js", "/assets/style.css"}:
        return "identity", "/" if path == "/identity" else path
    return "pos", "/" if path == "/pos" else path


async def proxy(request: Request):
    path = request.url.path
    if path in {"/api/v1/identity/authorize", "/api/v1/identity/pos-session", "/api/v1/auth/me"}:
        return Response(status_code=404)
    if path == "/":
        return HTMLResponse("""<!doctype html><meta charset=utf-8><title>BSV ALL 内部测试</title>
<h1>BSV ALL 内部测试</h1><p>隔离测试数据 · SSH 隧道入口</p>
<ul><li><a href="/staff">员工登录与个人中心</a><li><a href="/hq">总部身份管理</a>
<li><a href="/pos">门店 POS</a><li><a href="/supply-ui/hq/supply">供货与库存</a>
<li><a href="/supply-ui/inspector/supply">独立督查</a><li><a href="/cocktail/">电子菜单</a></ul>""")
    if path == "/craft" or path.startswith("/craft/"):
        return Response("Craft menu unavailable", status_code=404)
    # Reject paths that could normalize to a different upstream route.
    if any(part in {".", ".."} for part in path.split("/")) or any(c in path for c in ("%", "\\", "//")):
        return Response(status_code=400)
    key, target = upstream(path)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > LIMIT:
            return Response(status_code=413)
    headers = [(k, v) for k, v in request.headers.raw if k in INBOUND]
    headers.append((b"host", request.headers["host"].encode("ascii")))
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            url = httpx.URL(UPSTREAM[key]).copy_with(path=target, query=request.scope["query_string"])
            async with client.stream(request.method, url, headers=headers, content=bytes(body)) as result:
                data = bytearray()
                async for chunk in result.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > LIMIT:
                        return Response(status_code=502)
                response = Response(bytes(data), status_code=result.status_code)
                response.raw_headers.extend((k.lower(), v) for k, v in result.headers.raw if k.lower() in OUTBOUND)
                return response
    except (httpx.HTTPError, ValueError):
        return Response(status_code=503)


class LocalHost:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            hosts = [value for key, value in scope["headers"] if key == b"host"]
            if len(hosts) != 1 or hosts[0].split(b":", 1)[0] not in (b"127.0.0.1", b"localhost"):
                return await Response(status_code=400)(scope, receive, send)
        await self.app(scope, receive, send)


app = LocalHost(Starlette(routes=[
    Mount("/cocktail", StaticFiles(directory=ROOT / "apps/guest-web/bsv1/site/cocktail", html=True)),
    Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST"]),
]))
