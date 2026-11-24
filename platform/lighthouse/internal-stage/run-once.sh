#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

readonly SHA="${2:-}"
readonly REPO='https://github.com/Ethancao258/bsv-all-platform.git'
readonly ROOT='/opt/bsv-all-internal-stage'
readonly DATA='/var/lib/bsv-all-internal-stage'
readonly PACKAGE_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
readonly DATA_FILE="$PACKAGE_DIR/workbuddy-v22.zip"
[[ -f "$DATA_FILE" && ! -L "$DATA_FILE" ]] || { echo 'BLOCKED: WorkBuddy archive is missing or symlinked' >&2; exit 1; }
readonly IMPORT_DIR="$DATA/catalog/imports"
readonly DATA_SHA="$(sha256sum "$DATA_FILE" | awk '{print $1}')"
readonly APPROVER="$(python3 - <<'PYACTOR'
import os, pwd, sys
if os.geteuid() != 0:
    raise SystemExit('must run as root')
sudo_uid = os.environ.get('SUDO_UID')
sudo_user = os.environ.get('SUDO_USER')
if sudo_uid is None:
    if sudo_user is not None:
        raise SystemExit('SUDO_USER without sudo-authenticated SUDO_UID is not trusted')
    print(pwd.getpwuid(os.geteuid()).pw_name)
else:
    if not sudo_uid.isdecimal():
        raise SystemExit('invalid SUDO_UID')
    account = pwd.getpwuid(int(sudo_uid)).pw_name
    if sudo_user != account:
        raise SystemExit('SUDO_USER does not match SUDO_UID account')
    print(account)
PYACTOR
)"
WORK=''
DEPLOYMENT_ATTEMPTED=0

rollback_after_failure() {
  rc="${1:-$?}"
  trap - ERR HUP INT TERM
  if (( DEPLOYMENT_ATTEMPTED == 1 )) && [[ -n "$WORK" && -d "$WORK/repo" ]]; then
    status=$(python3 "$WORK/repo/platform/lighthouse/internal-stage/bsvctl.py" status 2>/dev/null || true)
    should_rollback=$(python3 - "$status" "$SHA" <<'PY'
import json,sys
try:
    state=json.loads(sys.argv[1])
except (ValueError,TypeError):
    print('unknown');raise SystemExit(0)
print('yes' if state.get('pending_activation') is True or state.get('deployed_sha') == sys.argv[2] else 'no')
PY
)
    if [[ "$should_rollback" == yes ]]; then
      echo 'Post-deploy failure/interruption: invoking controlled software rollback. PostgreSQL/catalog content, backups, and source records are preserved.' >&2
      python3 "$WORK/repo/platform/lighthouse/internal-stage/bsvctl.py" rollback || \
        echo 'ROLLBACK_FAILED: preserve all files and inspect the activation journal and service logs; do not retry.' >&2
    elif [[ "$should_rollback" == unknown ]]; then
      echo 'ROLLBACK_NOT_ATTEMPTED: release state is unreadable; preserve all files and inspect before any retry.' >&2
    fi
  fi
  exit "$rc"
}
trap 'rollback_after_failure $?' ERR
trap 'rollback_after_failure 129' HUP
trap 'rollback_after_failure 130' INT
trap 'rollback_after_failure 143' TERM
block() { echo "BLOCKED: $*" >&2; return 1; }

[[ "$SHA" =~ ^[a-f0-9]{40}$ && ${1:-} == '--approve-isolated' ]] || block 'usage: run-once.sh --approve-isolated <exact 40-character SHA>'
[[ $(id -u) == 0 ]] || block 'run the TAT command as root'
exec 9>/run/lock/bsv-pr40-run-once.lock
flock -n 9 || block 'another PR #40 deployment attempt is active; no files were changed'
[[ -d "$PACKAGE_DIR" && ! -L "$PACKAGE_DIR" ]] || block 'private delivery directory missing or symlinked'
cd "$PACKAGE_DIR"
sha256sum --check --strict SHA256SUMS

python3 - "$PACKAGE_DIR" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1])
expected={'repo.bundle','ci-proof.json','workbuddy-v22.zip','SHA256SUMS','run-once.sh','ACCEPTANCE_TEMPLATE.md','TRANSFER_AND_EXECUTION.md','DEPLOYMENT_REHEARSAL_REPORT.md'}
items=list(p.iterdir())
if {x.name for x in items}!=expected or any(x.is_symlink() or not x.is_file() for x in items):
    raise SystemExit('BLOCKED: unexpected or unsafe delivery package contents')
PY

# Fresh private checkout per attempt. A previous work tree is never deleted or rewritten.
WORK=$(mktemp -d "/root/bsv-pr40-${SHA}.XXXXXX")
chmod 0700 "$WORK"
git clone --no-checkout "$PACKAGE_DIR/repo.bundle" "$WORK/repo" >/dev/null
git -C "$WORK/repo" checkout --detach "$SHA" >/dev/null
git -C "$WORK/repo" remote set-url origin "$REPO"
[[ $(git -C "$WORK/repo" rev-parse HEAD) == "$SHA" ]] || block 'Git bundle commit mismatch'
[[ -z $(git -C "$WORK/repo" status --porcelain) ]] || block 'target source tree is not clean'

# Stage preflight checks real units, PostgreSQL 17, HBA drift, listeners, paths and legacy 8765/8767.
free_bytes=$(df -PB1 "$DATA" | awk 'NR==2 {print $4}')
mem_kib=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
[[ "$free_bytes" =~ ^[0-9]+$ && "$free_bytes" -ge 8589934592 ]] || block 'less than 8 GiB free on the isolated data filesystem'
[[ "$mem_kib" =~ ^[0-9]+$ && "$mem_kib" -ge 1048576 ]] || block 'less than 1 GiB available memory'
[[ $(nproc) -ge 2 ]] || block 'fewer than two CPUs available'
python3 "$WORK/repo/platform/lighthouse/internal-stage/stage.py" --preflight --sha "$SHA"
status=$(python3 "$WORK/repo/platform/lighthouse/internal-stage/bsvctl.py" status)
python3 - "$status" <<'PY'
import json,sys
x=json.loads(sys.argv[1])
if x.get('pending_activation') is not False or not x.get('deployed_sha'):
    raise SystemExit('BLOCKED: no stable managed release or an activation is pending')
PY

# Verify WorkBuddy before any release change. Package rows and originals are source data, not executable code.
python3 - "$WORK/repo" "$PACKAGE_DIR/workbuddy-v22.zip" <<'PY'
import hashlib,sys,tempfile,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'services/api/bsv1'))
from bsv_catalog_import import _verified_package
archive=Path(sys.argv[2])
if hashlib.sha256(archive.read_bytes()).hexdigest()!='3f98fbe12eacdca481d1e7b3350a59410da7f1116c74a75a1c7b93fe63a0e5a1':
    raise SystemExit('BLOCKED: WorkBuddy V2.2 archive SHA mismatch')
with tempfile.TemporaryDirectory(prefix='bsv-v22-preflight-') as temp:
    root=Path(temp).resolve()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            path=(root/name).resolve()
            if name.startswith('/') or not path.is_relative_to(root):
                raise SystemExit('BLOCKED: unsafe data archive path')
        z.extractall(root)
    manifest,_,rows=_verified_package(root,archive)
    main=sum(len(rows[k]) for k in ('catalog.product','catalog.semifinished','catalog.material','catalog.bundle','catalog.recipe_step','catalog.price_quote','core.store'))
    if main!=589: raise SystemExit(f'BLOCKED: expected 589 source records, got {main}')
    print('SOURCE_PACKAGE_VALID',manifest['source_sha256'],'main_records=589')
PY

# bsvctl performs the managed-config comparison and checkpoint before service switching. Do not remove prior backups/releases.
DEPLOYMENT_ATTEMPTED=1
SUDO_USER="$APPROVER" python3 "$WORK/repo/platform/lighthouse/internal-stage/bsvctl.py" deploy \
  --sha "$SHA" --approve-isolated --ci-proof "$PACKAGE_DIR/ci-proof.json" \
  --request-id ISSUE-40 --module identity-api --module store-pos \
  --module customer-growth --module vincent-academy --module store-shifts \
  --module deployment-config
python3 "$WORK/repo/platform/lighthouse/internal-stage/bsvctl.py" verify

# Reuse an identical prior archive/private extraction; create the imports child only if absent.
if [[ -e "$IMPORT_DIR" || -L "$IMPORT_DIR" ]]; then
  [[ -d "$IMPORT_DIR" && ! -L "$IMPORT_DIR" ]] || block 'managed catalog imports directory is unsafe'
  [[ $(stat -c '%U:%G:%a' "$IMPORT_DIR") == 'bsvint-identity:bsvint-identity:700' ]] || block 'imports directory owner/mode drift'
else
  install -d -o bsvint-identity -g bsvint-identity -m 0700 "$IMPORT_DIR"
fi
archive="$IMPORT_DIR/workbuddy-$DATA_SHA.zip"
if [[ -e "$archive" || -L "$archive" ]]; then
  [[ -f "$archive" && ! -L "$archive" && $(stat -c '%U:%G:%a' "$archive") == 'bsvint-identity:bsvint-identity:600' ]] || block 'existing source archive has unexpected owner/mode'
  echo "$DATA_SHA  $archive" | sha256sum --check --status || block 'existing source archive differs; preserved for manual investigation'
else
  install -o bsvint-identity -g bsvint-identity -m 0600 "$PACKAGE_DIR/workbuddy-v22.zip" "$archive"
fi
pkgdir="$IMPORT_DIR/package-$DATA_SHA"
if [[ -e "$pkgdir" || -L "$pkgdir" ]]; then
  [[ -d "$pkgdir" && ! -L "$pkgdir" && $(stat -c '%U:%G:%a' "$pkgdir") == 'bsvint-identity:bsvint-identity:700' ]] || block 'existing package extraction has unexpected owner/mode; left untouched'
else
  install -d -o bsvint-identity -g bsvint-identity -m 0700 "$pkgdir"
  python3 - "$archive" "$pkgdir" <<'PY'
import pathlib,sys,zipfile
archive=pathlib.Path(sys.argv[1]);root=pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(archive) as z:
  for name in z.namelist():
    path=pathlib.PurePosixPath(name)
    target=(root.joinpath(*path.parts)).resolve()
    if path.is_absolute() or '..' in path.parts or not target.is_relative_to(root):
      raise SystemExit('BLOCKED: unsafe WorkBuddy path')
  z.extractall(root)
PY
  chown -R bsvint-identity:bsvint-identity "$pkgdir"
  chmod -R go-rwx "$pkgdir"
fi

python="$ROOT/current/identity/bin/python"
importer="$ROOT/current/src/services/api/bsv1/bsv_catalog_import.py"
manifest="$pkgdir/manifest.json"
"$python" - "$WORK/repo" "$pkgdir" "$archive" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'services/api/bsv1'))
from bsv_catalog_import import _verified_package
m,_,rows=_verified_package(Path(sys.argv[2]),Path(sys.argv[3]))
assert sum(len(rows[k]) for k in ('catalog.product','catalog.semifinished','catalog.material','catalog.bundle','catalog.recipe_step','catalog.price_quote','core.store'))==589
print('PERSISTED_PACKAGE_VALID',m['source_sha256'])
PY

set -a
. "$ROOT/config/catalog-import.env"
set +a
[[ ${BSV_APP_ENV:-} == isolated && ${BSV_ALLOW_ISOLATED_CATALOG_IMPORT:-} == 1 ]] || block 'catalog importer is not isolated-only'
[[ ${BSV_CATALOG_ADMIN_DB_URL:-} == postgresql+psycopg://bsv_catalog_importer:*@127.0.0.1:18764/bsv_all_prod ]] || block 'catalog DSN is not the registered loopback bsv_all_prod target'
stamp=$(date -u +%Y%m%dT%H%M%SZ)
approval="$IMPORT_DIR/approval-$stamp-$$.json"
result="$WORK/import-result.json"
state=$("$python" "$importer" --package-dir "$pkgdir" --archive "$archive" \
  --audit-existing --approvals-dir "$IMPORT_DIR")
state_kind=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["status"])' "$state")
if [[ "$state_kind" == FRESH ]]; then
  [[ ! -e "$approval" && ! -L "$approval" ]] || block 'approval path collision; preserved'
  "$python" "$importer" --package-dir "$pkgdir" --archive "$archive" --issue-approval \
    --approver "$APPROVER" --change-id BSV-CHG-20261124-PR40-V22 --approval-output "$approval" >/dev/null
  "$python" "$importer" --package-dir "$pkgdir" --archive "$archive" --approval "$approval" > "$result"
elif [[ "$state_kind" == SAFE_RESUME_IDEMPOTENT_NOOP ]]; then
  # The database already contains the exact committed raw revision. Do not
  # re-import it or roll back durable catalog facts when only app rollout failed.
  python3 - "$state" > "$result" <<'PY'
import json,sys
x=json.loads(sys.argv[1])
print(json.dumps({"status":"IDEMPOTENT_NOOP","source_sha256":x["source_sha256"],
                  "batch_id":x["batch_id"],"counts":x["counts"]},sort_keys=True))
PY
else
  block 'catalog state is neither fresh nor an exact audited prior import; preserved and stopped'
fi
chmod 0600 "$result"
"$python" - "$WORK/repo" "$manifest" "$result" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'services/api/bsv1'))
from bsv_catalog_import import expected_sql_counts
m=json.load(open(sys.argv[2]));result=json.load(open(sys.argv[3]));expected=expected_sql_counts(m);actual=result.get('counts',{})
if result.get('status') not in ('COMMITTED_RAW','IDEMPOTENT_NOOP') or actual!=expected:
  raise SystemExit('BLOCKED: committed status or actual PG17 table counts differ from package manifest')
main=sum(actual[x] for x in ('catalog.product','catalog.semifinished','catalog.material','catalog.bundle','catalog.recipe_step','catalog.price_quote','core.store'))
if main!=589: raise SystemExit(f'BLOCKED: actual main record count is {main}, expected 589')
print('PG17_IMPORT_COUNT_VERIFIED',json.dumps(actual,sort_keys=True))
PY

# Run once more under a fresh approval bound to the now-active source; this must be a no-op.
source_sha=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["source_sha256"])' "$manifest")
noop_approval="$IMPORT_DIR/approval-replay-$stamp-$$.json"
[[ ! -e "$noop_approval" && ! -L "$noop_approval" ]] || block 'replay approval path collision; preserved'
"$python" "$importer" --package-dir "$pkgdir" --archive "$archive" --issue-approval \
  --approver "$APPROVER" --change-id BSV-CHG-20261124-PR40-V22 --expected-active-source-sha "$source_sha" \
  --approval-output "$noop_approval" >/dev/null
noop=$("$python" "$importer" --package-dir "$pkgdir" --archive "$archive" --approval "$noop_approval")
python3 - "$noop" <<'PY'
import json,sys
x=json.loads(sys.argv[1])
if x.get('status')!='IDEMPOTENT_NOOP': raise SystemExit('BLOCKED: replay was not idempotent')
print('IMPORT_REPLAY',x['status'])
PY

BSV_REQUIRE_PG_CATALOG=1 "$ROOT/current/identity/bin/python" "$ROOT/current/src/platform/lighthouse/internal-stage/acceptance_v41.py" --expected-sha "$SHA" --execute-isolated > "$WORK/acceptance-v41.json"
grep -q 'V4_STAGING_ACCEPTED' "$WORK/acceptance-v41.json" || block 'synthetic isolated HTTP acceptance failed'
python3 - "$WORK/acceptance-v41.json" <<'PY'
import json,sys
s=open(sys.argv[1],encoding='utf-8').read();end=s.rfind('\nV4_STAGING_')
if end<0: raise SystemExit('BLOCKED: acceptance state marker missing')
x=json.loads(s[:end]);rows={r['test_id']:r for r in x.get('tests',[])}
if rows.get('PG_CATALOG_READ',{}).get('status')!='PASS':
  raise SystemExit('BLOCKED: authenticated employee PostgreSQL catalog API acceptance did not pass')
print('EMPLOYEE_PG_CATALOG_HTTP=PASS')
PY
python3 "$ROOT/current/src/platform/lighthouse/internal-stage/bsvctl.py" verify
backup_report="$WORK/postimport-checkpoint.json"
python3 "$WORK/repo/platform/lighthouse/internal-stage/stage.py" --backup > "$backup_report"
receipt=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["checkpoint"])' "$backup_report")
recovery=$(python3 "$WORK/repo/platform/lighthouse/internal-stage/stage.py" --recovery-check "$receipt")
python3 - "$recovery" <<'PY'
import json,sys
x=json.loads(sys.argv[1])
if x.get('postgres')!='AES_GCM_VERIFIED' or x.get('catalog_postgres')!='AES_GCM_VERIFIED' or x.get('pos_sqlite')!='QUICK_CHECK_OK':
  raise SystemExit('BLOCKED: post-import backup integrity check failed')
print('POSTIMPORT_BACKUP_INTEGRITY=PASS')
PY
catalog_archive=$(python3 - "$receipt" <<'PY'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
catalog=x.get('postgres',{}).get('catalog',{})
if catalog.get('source')!='catalog' or catalog.get('database')!='bsv_all_prod' or catalog.get('integrity')!='AES_GCM_VERIFIED':
  raise SystemExit('BLOCKED: catalog restore source evidence is incomplete')
print(catalog['archive'])
PY
)
restore_db=$(python3 - "$WORK/repo" "$SHA" <<'PY'
import subprocess, sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'platform/lighthouse/internal-stage'))
import stage
source_sha=sys.argv[2]
common=['-XAt','-h',stage.DATA/'postgres','-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d','postgres','-v','ON_ERROR_STOP=1']
limit_result=stage.as_user('postgres',stage.PG/'psql',*common,'-c','SHOW max_identifier_length',
    env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE)
limit=int(limit_result.stdout.strip())
name=stage.catalog_restore_database_name(source_sha,limit)
exists=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres','-p',str(stage.PORTS['postgres']),
                    '-U',stage.user('postgres'),'-d','postgres','-v','ON_ERROR_STOP=1',
                    '-c',f"SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='{name}')",
                    env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE).stdout.strip()
if exists!='f': raise SystemExit('BLOCKED: isolated restore target name already exists; preserved')
stage.as_user('postgres',stage.PG/'createdb','-T','template0','-O',stage.CATALOG_IMPORT_USER,
              '-h',stage.DATA/'postgres','-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),name)
print(name)
PY
)
restore_url="postgresql+psycopg://bsvint-postgres@127.0.0.1:18764/$restore_db"
BSV_APP_ENV=isolated BSV_DB_A_URL="$BSV_CATALOG_ADMIN_DB_URL" BSV_DB_SSLMODE=disable \
BSV_LOCAL_ARCHIVE_DIR="$DATA/catalog/archives" BSV_BACKUP_KEY_FILE="$DATA/catalog/backup.key" \
BSV_BACKUP_SOURCE_LABEL=catalog "$ROOT/current/identity/bin/python" -m services.api.identity.backup restore \
  --archive "$catalog_archive" --target "$restore_url" --apply-isolated --managed-peer-restore
"$ROOT/current/identity/bin/python" - "$WORK/repo" "$restore_db" "$result" "$manifest" <<'PY'
import json,re,sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'platform/lighthouse/internal-stage'))
import stage
name=sys.argv[2];counts=json.load(open(sys.argv[3],encoding='utf-8'))['counts']
source_sha=json.load(open(sys.argv[4],encoding='utf-8'))['source_sha256']
prefix='bsvr_'
legacy_prefix='bsv_identity_isolated_catalog_restore_'
if not re.fullmatch(r'bsvr_[a-f0-9]{8}_[0-9]{14}_[a-f0-9]{16}',name):
  raise SystemExit('BLOCKED: restore query is outside a unique isolated database')
limit_output=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
    '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d','postgres',
    '-v','ON_ERROR_STOP=1','-c','SHOW max_identifier_length',
    env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE).stdout.strip()
identifier_limit=int(limit_output)
found=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
    '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d','postgres',
    '-v','ON_ERROR_STOP=1','-c',"SELECT datname FROM pg_database WHERE left(datname,"+str(len(prefix))+ ")='"+prefix+"' OR left(datname,"+str(len(legacy_prefix))+ ")='"+legacy_prefix+"' ORDER BY datname",
    env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE).stdout.splitlines()
names=[item.strip() for item in found if item.strip()]
if name not in names: raise SystemExit('BLOCKED: current restore database is not in the managed temporary namespace')
if any(not (re.fullmatch(r'bsvr_[a-f0-9]{8}_[0-9]{14}_[a-f0-9]{16}',item)
            or re.fullmatch(r'bsv_identity_isolated_catalog_restore_[a-f0-9]{8}_[0-9]{8}T[0-9]{6}_[0-9]+',item))
       for item in names):
  raise SystemExit('BLOCKED: unexpected temporary restore database name; preserve all')
if any(len(item.encode('utf-8'))>identifier_limit for item in names):
  raise SystemExit('BLOCKED: retained restore database name exceeds server max_identifier_length; preserve all')
verified=[]
for candidate in names:
  owner=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
      '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d','postgres',
      '-v','ON_ERROR_STOP=1','-c',"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='"+candidate+"'",
      env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE).stdout.strip()
  if owner!='bsv_catalog_importer': raise SystemExit('BLOCKED: temporary restore database owner differs; preserve all')
  active=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
      '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d',candidate,
      '-v','ON_ERROR_STOP=1','-c',"SELECT trim(source_sha256)||':'||activation_status FROM catalog.active_content WHERE singleton_id=1",
      env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE).stdout.strip()
  if active!=source_sha+':IMPORTED_RAW': raise SystemExit('BLOCKED: leftover restore database has a different or incomplete content version; preserve all')
  actual={}
  for key,expected in counts.items():
    m=re.fullmatch(r'([a-z_]+)\.([a-z_]+)',key)
    if not m: raise SystemExit('BLOCKED: unexpected SQL count identifier')
    sql=f'SELECT count(*) FROM "{m.group(1)}"."{m.group(2)}"'
    result=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
        '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d',candidate,
        '-v','ON_ERROR_STOP=1','-c',sql,env={'PATH':str(stage.PG)+':/usr/bin:/bin'},
        stdout=subprocess.PIPE)
    value=int(result.stdout.strip());actual[key]=value
    if value!=expected: raise SystemExit(f'BLOCKED: restored table count mismatch in {candidate}: {key}')
  product=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
      '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d',candidate,
      '-v','ON_ERROR_STOP=1','-c',"SELECT count(*) FROM catalog.product WHERE product_id='C000001' AND ingest_status='IMPORTED_RAW'",
      env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE)
  if product.stdout.strip()!='1': raise SystemExit('BLOCKED: restored C000001 is missing or not raw/unapproved')
  hba=stage.as_user('postgres',stage.PG/'psql','-XAt','-h',stage.DATA/'postgres',
      '-p',str(stage.PORTS['postgres']),'-U',stage.user('postgres'),'-d','postgres',
      '-v','ON_ERROR_STOP=1','-c',f"SELECT count(*) FROM pg_hba_file_rules WHERE type='host' AND array_to_string(database,',') LIKE '%{candidate}%'",
      env={'PATH':str(stage.PG)+':/usr/bin:/bin'},stdout=subprocess.PIPE)
  if hba.stdout.strip()!='0': raise SystemExit('BLOCKED: temporary restore database has a TCP HBA exception')
  main=sum(actual[x] for x in ('catalog.product','catalog.semifinished','catalog.material','catalog.bundle','catalog.recipe_step','catalog.price_quote','core.store'))
  if main!=589: raise SystemExit(f'BLOCKED: restored main row count is {main}, expected 589')
  verified.append(candidate)
# All retained temporary restores are source-, owner-, count-, and HBA-verified
# before any cleanup. Unknown prior state is left untouched and blocks release.
for candidate in verified:
  stage.as_user('postgres',stage.PG/'dropdb','-h',stage.DATA/'postgres','-p',str(stage.PORTS['postgres']),
                '-U',stage.user('postgres'),'-w',candidate)
print('LIVE_PG17_ISOLATED_RESTORE=PASS main_records=589 count_sets='+str(len(counts))+' local_peer=PASS tcp_hba_exception=NONE')
print('TEMP_RESTORE_DATABASES_CLEANED='+str(len(verified)))
PY
echo "TARGET_SHA=$SHA"
echo "WORKBUDDY_SOURCE_SHA=$DATA_SHA"
echo 'DATABASE_IMPORT=COMMITTED_RAW_OR_AUDITED_IDEMPOTENT_NOOP'
echo 'SALES_APPROVAL=UNCHANGED_NOT_GRANTED'
echo 'OLD_8765_8767=PROTECTED_BY_RELEASE_PREFLIGHT'
echo 'CATALOG_BACKUP=AUTHENTICATED_AES_GCM_PASS'
echo 'CATALOG_RESTORE=LIVE_ISOLATED_PG17_PASS'
echo 'EMPLOYEE_BROWSER=HOST_NOT_RUN (authenticated HTTP catalog read verified in CI; host browser acceptance is still required)'
echo 'CATALOG_CONTENT_ROLLBACK=NOT_PERFORMED (raw imported facts are preserved; retry requires identical content and audit evidence)'
echo 'TEMP_RESTORE_DATABASES=REMOVED_AFTER_VERIFIED_SUCCESS'
[[ "$WORK" == "/root/bsv-pr40-${SHA}."* && -d "$WORK/repo/.git" && ! -L "$WORK" ]] || block 'refusing to clean an unexpected work path'
trap - ERR HUP INT TERM
rm -rf -- "$WORK"
WORK=''
echo 'SUCCESS_WORKTREE=CLEANED_AFTER_ALL_ACCEPTANCE_GATES'
