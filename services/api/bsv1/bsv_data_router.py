"""BSV ALL logical read-route policy: fail CLOSED for writes, fail to verified local cache for reference reads.

This is an integration contract + reusable deterministic policy, NOT a PostgreSQL driver
or a transparent failover of operational SQLite. The existing BSV1 POS still uses its
own temporary staging SQLite until the central BSV ALL repository is implemented.
"""
from __future__ import annotations
import dataclasses, datetime, hashlib, json, os, sqlite3, tempfile
from pathlib import Path

SAFE_REFERENCE_DOMAINS=frozenset({'published_catalog','published_recipe','published_layout','store_directory','training_document'})
DANGEROUS_OPERATIONS=frozenset({'WRITE','CHECKOUT','PAYMENT','INVENTORY_CHANGE','STAFF_MUTATION','PUBLISH'})

class Unavailable(RuntimeError):pass
@dataclasses.dataclass(frozen=True)
class Route:
    source:str
    read_only:bool
    stale:bool
    reason:str


def select_source(*,operation:str,domain:str,primary_healthy:bool,snapshot_valid:bool=False):
    """Pure function, no IO, no database writes; higher-level adapters must implement probes."""
    if type(primary_healthy) is not bool or type(snapshot_valid) is not bool:
        raise ValueError('boolean health inputs required')
    if operation not in ('READ_REFERENCE', 'READ_TRANSACTION', *DANGEROUS_OPERATIONS):
        raise ValueError('unrecognized operation')
    if primary_healthy:
        return Route('DB_A',False,False,'PRIMARY_AVAILABLE')
    if operation=='READ_REFERENCE' and domain in SAFE_REFERENCE_DOMAINS and snapshot_valid:
        return Route('DB_B',True,True,'VERIFIED_STALE_REFERENCE')
    raise Unavailable('Primary unavailable; no approved writable or transactional failover')


def _sha256(path:Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def publish_reference_snapshot(source:Path,target:Path,*,source_revision:str,created_utc=None):
    """Single-file local reference cache export from a consistent SQLite snapshot.
    The caller must first filter strictly to PUBLISHED NON-SENSITIVE reference tables.
    DO NOT point this function at the full payroll/orders database as a user-facing cache.
    """
    raise NotImplementedError('Snapshot export requires domain-filtered projection; copying an entire operational DB is forbidden')


def verify_snapshot(snapshot:Path,meta:Path,*,max_age_seconds:int=86400,now_utc=None)->dict:
    """Verify immutable reference snapshot against trusted out-of-band manifest.
    If manifest verification or staleness fails, REFUSE fallback. This does not authenticate
    the manifest: the integrator must protect metadata origin and file permissions.
    """
    if max_age_seconds<=0:raise ValueError('max_age_seconds must be positive')
    snapshot=Path(snapshot);meta=Path(meta)
    if not snapshot.is_file() or not meta.is_file():raise Unavailable('snapshot or metadata missing')
    try:
        manifest=json.loads(meta.read_text('utf-8'))
        if set(manifest)!={'snapshot_sha256','created_at_utc','revision','classification'}:
            raise ValueError('metadata schema mismatch')
        if manifest['classification']!='PUBLIC_REFERENCE_ONLY':raise ValueError('invalid data classification')
        if not isinstance(manifest['revision'],str) or not manifest['revision']:
            raise ValueError('missing revision')
        dt=datetime.datetime.fromisoformat(manifest['created_at_utc'].replace('Z','+00:00'))
        if dt.tzinfo is None:raise ValueError('missing timezone')
        now=now_utc or datetime.datetime.now(datetime.timezone.utc)
        age=(now-dt).total_seconds()
        if age<0 or age>max_age_seconds:raise ValueError('snapshot stale or from future')
        if _sha256(snapshot)!=manifest['snapshot_sha256']:raise ValueError('sha256 mismatch')
        uri=snapshot.resolve().as_uri()+'?mode=ro'
        with sqlite3.connect(uri,uri=True,timeout=3) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('SQLite quick_check failed')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            forbidden={'orders','order_lines','staff','sessions','members','visits','payments','employee'}
            if tables & forbidden:raise ValueError('sensitive or transactional tables found')
        return {'ok':True,'revision':manifest['revision'],'age_seconds':age,'source':'DB_B','read_only':True}
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,json.JSONDecodeError) as ex:
        raise Unavailable(f'reference snapshot invalid: {ex}') from ex
