#!/usr/bin/env python3
"""Public web closeout: read-only HTTPS regression; optional renewal-hook installation.
No credentials, business endpoints with auth, DNS modifications or certificate reissue."""
import argparse
import json
import os
from pathlib import Path
import ssl
import socket
import subprocess
import tempfile
import datetime
import urllib.request
import urllib.error
import urllib.parse

BASE="https://bsvm.cn"
MENU="https://menu.bsvm.cn"
ADMIN="https://admin.bsvm.cn"
HOSTS=("bsvm.cn","www.bsvm.cn","menu.bsvm.cn","admin.bsvm.cn")
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def audit():
    ctx=ssl.create_default_context()
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ctx))
    failures=0
    def row(name, ok, detail):
        nonlocal failures
        failures+=not ok
        print(json.dumps({"check":name,"ok":bool(ok),"detail":detail},ensure_ascii=False),flush=True)
    def get(url, status, contains=None, mime=None, target=None, parse_json=False):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"BSV-Public-Web-Health/1.0","Accept-Encoding":"identity"})
            try:
                res=opener.open(req,timeout=10)
            except urllib.error.HTTPError as e:
                res=e
            with res:
                code=res.code
                loc=res.headers.get("Location","")
                typ=res.headers.get_content_type()
                data=res.read(2_000_001)
            ok=code in status and len(data)<=2_000_000
            if contains: ok=ok and all(x.encode("utf-8") in data for x in contains)
            if mime: ok=ok and typ in mime
            if target: ok=ok and urllib.parse.urljoin(url,loc)==target
            if parse_json:
                j=json.loads(data)
                ok=ok and isinstance(j,dict) and isinstance(j.get("items"),list) and bool(j["items"])
            row(url,ok,{"status":code,"mime":typ,"redirect":loc,"bytes":len(data)})
        except Exception as e:
            row(url,False, type(e).__name__+": "+str(e)[:220])
    for host in HOSTS:
        try:
            with socket.create_connection((host,443),timeout=8) as raw:
                with ctx.wrap_socket(raw,server_hostname=host) as s:
                    cert=s.getpeercert()
            days=int((ssl.cert_time_to_seconds(cert["notAfter"])-datetime.datetime.now(datetime.timezone.utc).timestamp())/86400)
            row("TLS "+host,days>=14,{"days_remaining":days,"subjectAltName":cert.get("subjectAltName")})
        except Exception as e: row("TLS "+host,False,str(e)[:220])
    get(BASE+"/",{200},["BAR ST. VINCENT","https://menu.bsvm.cn/cocktail/","beian.miit.gov.cn"],["text/html"])
    get("https://www.bsvm.cn/",{301,308},target=BASE+"/")
    get(MENU+"/",{301,302,307,308},target=MENU+"/cocktail/")
    for origin in (BASE,MENU):
        get(origin+"/cocktail/",{200},["BAR ST. VINCENT"],["text/html"])
        get(origin+"/cocktail?from=qr&x=1",{301,308},target=origin+"/cocktail/?from=qr&x=1")
        for f,m in [("style.css",["text/css"]),("app.js",["application/javascript","text/javascript"]),("menu-config.js",["application/javascript","text/javascript"]),("menu-copy.js",["application/javascript","text/javascript"]),("bsv-mark.webp",["image/webp"])]:
            get(origin+"/cocktail/assets/"+f,{200},mime=m)
        get(origin+"/cocktail/data/menu-public.json",{200},mime=["application/json"],parse_json=True)
        for p in ("/hq","/staff","/api/state","/api/history","/member/"):
            get(origin+p,{403,404})
    # V1.6 unified identity serves a public login shell; authorization is enforced by protected APIs.
    get(ADMIN+"/",{200},mime=["text/html"])
    get(ADMIN+"/api/state",{401,403})
    for origin in (BASE,MENU):
        get(origin.replace("https:","http:")+"/cocktail/?from=qr",{301,308},target=origin+"/cocktail/?from=qr")
    print("TECHNICAL_FAILURES="+str(failures))
    print("WECHAT_SCAN=DEVICE_REQUIRED; ICP_SERVICE_NUMBER=OWNER_RECORD_REQUIRED; CRAFT=SEPARATE_CONTENT_RELEASE")
    return failures

HOOK=Path("/etc/letsencrypt/renewal-hooks/deploy/90-bsv-nginx-reload.sh")
HOOK_BYTES=b'#!/bin/sh\nset -eu\n/usr/sbin/nginx -t\n/usr/bin/systemctl reload nginx\n'

def renew():
    if os.geteuid()!=0: raise SystemExit("Use sudo for --apply-renewal")
    subprocess.run(["/usr/sbin/nginx","-t"],check=True)
    HOOK.parent.mkdir(parents=True,exist_ok=True)
    if HOOK.is_symlink(): raise SystemExit("Unexpected hook symlink: inspect before change")
    if HOOK.exists() and HOOK.read_bytes()!=HOOK_BYTES:
        raise SystemExit("Existing different BSV hook: inspect before change")
    other=[p.name for p in HOOK.parent.iterdir() if p!=HOOK and p.is_file() and b"nginx" in p.read_bytes() and b"reload" in p.read_bytes() and os.access(p,os.X_OK)]
    if other and not HOOK.exists():
        print("EXISTING_EXECUTABLE_NGINX_HOOKS="+",".join(other))
        raise SystemExit("Review and reuse a valid existing hook; do not install duplicate")
    if not HOOK.exists():
        with tempfile.NamedTemporaryFile(dir=HOOK.parent,prefix=".bsv-",delete=False) as f:
            f.write(HOOK_BYTES)
            temp=Path(f.name)
        try:
            temp.chmod(0o755)
            os.replace(temp,HOOK)
        finally: temp.unlink(missing_ok=True)
    HOOK.chmod(0o755)
    subprocess.run(["/bin/sh","-n",str(HOOK)],check=True)
    subprocess.run(["systemctl","is-enabled","certbot.timer"],check=True)
    subprocess.run(["systemctl","is-active","certbot.timer"],check=True)
    # Test actual hook separately: dry-run does not normally execute deploy hooks.
    subprocess.run([str(HOOK)],check=True)
    # Staging only; do not use --force-renewal or delete live certificates.
    for name in ("bsvm.cn","menu.bsvm.cn"):
        subprocess.run(["certbot","renew","--cert-name",name,"--dry-run","--non-interactive"],check=True,timeout=180)
    print("RENEWAL_AND_HOOK_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply-renewal",action="store_true")
    a=p.parse_args()
    if a.apply_renewal: renew()
    return int(bool(audit()))
if __name__=="__main__":
    raise SystemExit(main())
