import sys,tempfile,unittest,sqlite3,json,hashlib,datetime
from pathlib import Path
APP=Path(__file__).resolve().parents[2]/"services/api/bsv1"
sys.path.insert(0,str(APP))
import bsv_data_router as R

class DataRoutes(unittest.TestCase):
    def test_primary_is_only_writer(self):
        for operation in ['WRITE','CHECKOUT','PAYMENT','INVENTORY_CHANGE','STAFF_MUTATION','PUBLISH']:
            self.assertEqual(R.select_source(operation=operation,domain='published_catalog',primary_healthy=True).source,'DB_A')
            with self.assertRaises(R.Unavailable):R.select_source(operation=operation,domain='published_catalog',primary_healthy=False,snapshot_valid=True)
    def test_safe_stale_read_only(self):
        r=R.select_source(operation='READ_REFERENCE',domain='published_catalog',primary_healthy=False,snapshot_valid=True)
        self.assertEqual((r.source,r.read_only,r.stale),('DB_B',True,True))
        for domain in ('orders','inventory','employee','payments'):
            with self.assertRaises(R.Unavailable):R.select_source(operation='READ_REFERENCE',domain=domain,primary_healthy=False,snapshot_valid=True)
        with self.assertRaises(R.Unavailable):R.select_source(operation='READ_TRANSACTION',domain='published_catalog',primary_healthy=False,snapshot_valid=True)
        with self.assertRaises(R.Unavailable):R.select_source(operation='READ_REFERENCE',domain='published_catalog',primary_healthy=False,snapshot_valid=False)
    def test_snapshots_reject_sensitive_tables_and_bad_hash(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'snapshot.sqlite3';m=Path(td)/'snapshot.json'
            with sqlite3.connect(p) as db:db.execute('CREATE TABLE public_catalog(id TEXT PRIMARY KEY)')
            now=datetime.datetime.now(datetime.timezone.utc)
            meta={'snapshot_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'created_at_utc':now.isoformat(),'revision':'catalog-001','classification':'PUBLIC_REFERENCE_ONLY'}
            m.write_text(json.dumps(meta),'utf-8')
            self.assertTrue(R.verify_snapshot(p,m,now_utc=now)['ok'])
            with sqlite3.connect(p) as db:db.execute('CREATE TABLE orders(id TEXT PRIMARY KEY)')
            meta['snapshot_sha256']=hashlib.sha256(p.read_bytes()).hexdigest();m.write_text(json.dumps(meta),'utf-8')
            with self.assertRaises(R.Unavailable):R.verify_snapshot(p,m,now_utc=now)
            with self.assertRaises(NotImplementedError):R.publish_reference_snapshot(p,p,source_revision='bad')
if __name__=='__main__':unittest.main()
