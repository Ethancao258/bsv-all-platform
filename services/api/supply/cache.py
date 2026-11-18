"""Local SQLite is ONLY a bounded cache and pending-command queue; never a production ledger."""
import json, sqlite3, threading, time
from pathlib import Path

class LocalCache:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.path = directory / "offline_cache.sqlite3"
        self.lock = threading.RLock()
        with self._conn() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS snapshots(key TEXT PRIMARY KEY,payload TEXT NOT NULL,saved_at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS pending(request_id TEXT PRIMARY KEY, source_key TEXT NOT NULL,path TEXT NOT NULL,
                  method TEXT NOT NULL, payload TEXT NOT NULL, actor_id TEXT NOT NULL, state TEXT NOT NULL,
                  response TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
            ''')
            if 'permission_scope' not in {row[1] for row in c.execute('PRAGMA table_info(pending)')}:
                c.execute("ALTER TABLE pending ADD COLUMN permission_scope TEXT")
        self.path.chmod(0o600)
    def _conn(self):
        c=sqlite3.connect(str(self.path),timeout=20,isolation_level=None)
        c.row_factory=sqlite3.Row
        return c
    def save(self,key:str,value):
        with self.lock,self._conn() as c:
            c.execute("REPLACE INTO snapshots VALUES (?,?,?)",(key,json.dumps(value,ensure_ascii=False),time.time()))
    def get(self,key:str,max_age_h:int):
        with self.lock,self._conn() as c:
            r=c.execute("SELECT payload,saved_at FROM snapshots WHERE key=?",(key,)).fetchone()
            if not r or time.time()-r["saved_at"]>max_age_h*3600:return None
            return {"payload":json.loads(r["payload"]),"saved_at":r["saved_at"]}
    def enqueue(self,request_id,source_key,path,method,payload,actor_id,permission_scope=None):
        with self.lock,self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                previous=c.execute("SELECT * FROM pending WHERE request_id=?",(request_id,)).fetchone()
                serialized = json.dumps(payload,sort_keys=True)
                if previous:
                    fields = ('source_key','method','path','payload','actor_id','permission_scope')
                    if tuple(previous[key] for key in fields) != (source_key,method,path,serialized,actor_id,permission_scope):
                        raise ValueError("request_id 已用于不同的操作")
                    result = dict(previous)
                else:
                    now=time.time()
                    c.execute("INSERT INTO pending VALUES (?,?,?,?,?,?,?,?,?,?,?)",(request_id,source_key,path,method,
                        serialized,actor_id,"QUEUED",None,now,now,permission_scope))
                    result = {"request_id":request_id,"state":"QUEUED"}
                c.execute("COMMIT")
                return result
            except Exception:
                c.execute("ROLLBACK")
                raise
    def pending_for(self,actor_id,permission_scope=None):
        with self.lock,self._conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM pending WHERE actor_id=? AND permission_scope IS ? ORDER BY created_at DESC LIMIT 100",(actor_id,permission_scope))]
    def queued(self,actor_id=None,permission_scope=None):
        with self.lock,self._conn() as c:
            return [dict(x) for x in c.execute("SELECT * FROM pending WHERE state='QUEUED' AND (? IS NULL OR actor_id=?) AND permission_scope IS ? ORDER BY created_at LIMIT 100",(actor_id,actor_id,permission_scope))]
    def finish(self,rid,state,response):
        with self.lock,self._conn() as c:
            c.execute("UPDATE pending SET state=?,response=?,updated_at=? WHERE request_id=? AND state='QUEUED'",
                (state,json.dumps(response,ensure_ascii=False),time.time(),rid))
