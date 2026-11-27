# BSV brand portal V1 — server handoff
Status: SOURCE_BASELINE / LIVE_HOST_DEPLOYMENT_TRACKED_SEPARATELY (2026-11-27). This PR contains the standalone public static website source and deployment handoff; live-host state must be verified from the current server evidence. No business DB, new services, paid resources or M1 release changes. Design source: feature/v4-3-pos-growth-closeout, apps/guest-web/bsv1/site/cocktail/assets/style.css, index.html and original bsv-mark.webp (blob 24503b8958bf08375c8b66d5c82ea3ec4b0add5c). Inherits the original dark brown, warm gold, serif typography and brand slogan. No invented venue imagery, private data, remote fonts, JS or tracker. Store display names use existing public registry and owner-described brand; verify against actual public listings before release. This is a four-store display based on the available registry, not a complete verified company store count.

## 1. Retrieve the pinned portal source without touching business worktrees
From a new shell in the existing repository, fetch only this branch and verify the commit supplied by the owner. Do not checkout, reset, merge, or alter the current production or C worktree.
```bash
git fetch origin refs/heads/feature/brand-portal-v1-20261127
git rev-parse FETCH_HEAD
```
Use the exact approved SHA from the handoff; stop if FETCH_HEAD differs, or fetch the exact approved SHA. Extract only the directory:
```bash
SRC=$(mktemp -d)
git archive FETCH_HEAD apps/guest-web/brand-portal | tar -x -C "$SRC"
cd "$SRC/apps/guest-web/brand-portal"
python3 -m py_compile render.py
```
If fetch is unavailable use the existing authenticated git channel or public GitHub HTTPS fetch with finite retries. Never paste credentials or use an unrelated HEAD.

## 2. Confirm menu routing and certificate before activating portal
Owner reports menu DNS mapping done. Verify externally resolving menu.bsvm.cn, existing EdgeOne/custom domain and actual HTTPS /cocktail/ and /craft/ content (title, asset and JSON loading; not only status 200). Preserve a functioning old provider, existing path and query string. If menu now points to this Lighthouse instance:
- Add a separate HTTP virtual host for menu.bsvm.cn with ACME webroot /var/www/html and other requests redirecting to HTTPS only once cert/vhost ready. Do not duplicate server_name. Validate nginx -t and reload. Use existing certificate if it covers menu; otherwise issue separate Certbot webroot certificate for menu.bsvm.cn (certonly, reuse registered account). Never replace three-domain cert.
- Add separate menu HTTPS vhost, reuse the exact currently approved public cocktail static directory and behavior (including assets and data/menu-public.json); confirm directory and all resource files are public allowlist and data contains no cost, inventory, staff, credentials, or synthetic pricing presented as real. Do not proxy mixed port 8080 or any business API. Keep the same source of truth for bsvm.cn/cocktail/ and menu.bsvm.cn/cocktail/; preferably pin both aliases to the same independently approved release directory so a candidate deployment cannot change a public menu automatically. No duplicate maintained menu source.
- If craft exists, verify real beer content and its public resources, then serve /craft/ through the same method. If no actual craft site exists, preserve the path with an explicit 503 temporary-unavailable page, no fake prices or cocktail fallback. Do not enable craft CTA until real menu is verified. Preserve existing functional EdgeOne route if present.
- Canonical menu host root can 302 to /cocktail/ or to bsvm.cn/#menus; choose /cocktail/ for legacy scans of root. /cocktail and /craft without slash redirect to slash form preserving query string. Unknown paths return 404. No admin paths. Ensure separate cert renewal and deploy hook nginx -t && systemctl reload nginx.
- If menu verification fails, retain existing public bsvm.cn/cocktail/ as temporary homepage link (renderer flag below), keep legacy menu DNS untouched and report the one concrete failure. Do not break the existing working menu.

## 3. Render and publish homepage
Use the verified full website ICP number including site suffix from the real filing record, not an assumed suffix. The source intentionally contains a placeholder and must never be served unrendered. If the filing record is not accessible to the Agent, obtain it from the owner before switching the homepage; retain old menu meanwhile.
```bash
# Substitute actual verified values, not the placeholders below:
PORTAL_RELEASE=/srv/bsv/public/brand-portal/releases/<approved-short-sha>
sudo install -d -m 0755 "$PORTAL_RELEASE"
sudo python3 render.py --icp '<actual-full-site-ICP-number>' --output "$PORTAL_RELEASE"
# Only if real /craft/ confirmed: append --craft-live
# Only if canonical cocktail URL still fails: append --cocktail-url https://bsvm.cn/cocktail/
```
This uses Python stdlib only, creates one index.html, atomically replaces that file and prints SHA256 and link decisions. Run once for the selected release directory. Check readability as www-data. No npm or database required. Do not publish source Python, deployment docs or .git.
Back up the actual current Nginx site file (reported /etc/nginx/sites-available/bsv-public-https), inspect current config, and edit only bsvm.cn HTTPS server block. Replace the old exact root 302 location with:
```nginx
location = / {
    root /srv/bsv/public/brand-portal/releases/<approved-short-sha>;
    try_files /index.html =404;
    add_header Cache-Control "no-cache";
    add_header X-Content-Type-Options "nosniff";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
}
location = /stores/ { return 302 /#stores; }
location = /stores { return 302 /#stores; }
```
Keep existing working /cocktail/ alias and static resources intact; add /craft/ only if independently approved. Preserve all other deny rules, HTTP ACME routes, www redirect, admin host, SSL certificate and upstreams. Never replace whole nginx config blindly. Do not map general public / to port 8080 or 18782. No new public backend port.
Validate nginx -t with no conflicting names, then systemctl reload nginx. Roll back by restoring exact backed-up Nginx site(s), testing and reloading; do not remove working SSL or public menu in rollback.

## 4. Admin preview and future path contracts
V1.6 supersedes the earlier V1.5/Basic-Auth handoff: admin.bsvm.cn is the unified internal workbench and must proxy to 127.0.0.1:18760; identity service is 127.0.0.1:18761. Port 18782 is the legacy/independent POS service, not the unified admin entry. Do not restore /etc/nginx/.htpasswd-bsv-admin, do not re-enable Nginx Basic Auth, and do not proxy admin to 18782; doing so reintroduces the extra shared-password prompt and breaks the approved V1.6 identity flow. A 200 GET / is acceptable only when it is a login/application shell with no private business data; all protected API routes and authenticated operations must reject anonymous requests (401/403). Verify actual V1.6 route registration and test the real protected routes, not guessed paths. Verify the existing reviewer1 account can authenticate and has company-wide management scope as separately required; do not alter its role in this public-web closeout. If any sensitive route returns data anonymously, block only that route or hold admin unavailable pending an identity fix. Future employee login, HQ, POS, staff, academy, supply and finance are routes under admin, not additional public ports. No dead public customer buttons for member/events; reserve conceptual paths, publish only after modules independently authorized. No production M1 promotion here.

## 5. Minimum acceptance & stop
- HTTPS bsvm.cn displays independent responsive brand portal, not redirect to menu; www redirects. Both canonical menu QR paths preserved; record craft AVAILABLE or NOT_YET_PUBLISHED. Check mobile viewport at 320/390 px and desktop 1280 px, no horizontal overflow, links, emblem, legal footer visibility; test actual rendered page in browser if possible, otherwise say BROWSER_NOT_RUN and provide URL. Verify current menu fixed viewport unchanged.
- Public bsvm.cn/menu.bsvm.cn /hq, /staff, /api/state, /api/history, /member/ remain blocked (404/403 as appropriate). On admin.bsvm.cn, login/application shell may return 200; protected API endpoints must return 401/403 without a session, and reviewer1 must authenticate through V1.6 identity with company-wide scope. Keep 18760/18761/18782 loopback-only. Do not print sensitive data in evidence.
- Check certbot timer and nginx reload hook (certonly/webroot does not auto-reload nginx), simulate renew only if not already validated for those certs; verify normal curl TLS without -k. Record actual ICP and public site status, code SHA, rendered SHA256, backup and rollback. Add private runtime state record per repo rules; no sensitive data in public GitHub. If server is read-only deploy key, report private handoff path.
- No business refactor, package upgrade, database migration, new module, admin production release or other Agent changes. Stop after URL verification; if only craft is unavailable, complete all independent items and report it.
