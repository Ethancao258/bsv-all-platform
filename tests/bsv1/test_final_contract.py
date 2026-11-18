import os,sys,json,re,unittest,tempfile,sqlite3
from pathlib import Path
APP=Path(__file__).resolve().parents[2]/"services/api/bsv1"
sys.path.insert(0,str(APP))
import bsv_layouts,bsv_one
class CanonicalV31(unittest.TestCase):
    def test_entire_file_registry_uses_single_ids(self):
        pattern=re.compile(r'^(BSV[A-Z0-9]+)-SEAT-[0-9]{4}$')
        seen=set()
        for store,cfg,sha,art in bsv_layouts.all_configs():
            if not cfg:continue
            for s in cfg['seats']:
                self.assertRegex(s['id'],pattern)
                self.assertTrue(s['id'].startswith(store['store_id']+'-'))
                self.assertNotIn(s['id'],seen)
                seen.add(s['id'])
                self.assertIn(s['id'],cfg['neighbors'])
            for g in cfg.get('groups',[]):
                self.assertRegex(g['id'],r'^BSV[A-Z0-9]+-GROUP-[0-9]{4}$')
            for b in cfg.get('bathrooms',[]):
                self.assertRegex(b['id'],r'^BSV[A-Z0-9]+-RESTROOM-[0-9]{4}$')
        self.assertEqual(len(seen),43)
    def test_reject_alternate_seat_ids_even_prefixed(self):
        cfg=bsv_layouts.load_layout('BSVM')[0]
        for invalid in ('T2','BSVM-T2','BSVM-S1','BSVM-SEAT-1','BSVS-SEAT-0001'):
            c=json.loads(json.dumps(cfg));c['seats'][0]['id']=invalid
            with self.assertRaises(bsv_one.ControlError,msg=invalid):bsv_one.clean_layout(None,'BSVM',c)
    def test_db_trigger_rejects_alias_and_immutable_key(self):
        import subprocess
        with tempfile.TemporaryDirectory(prefix='bsvid-') as td:
            env=dict(os.environ,BSV_MODE='staging',BSV_DB_PATH=str(Path(td)/'clean.sqlite3'),BSV_V9_XLSX=os.environ['BSV_V9_XLSX'])
            run=subprocess.run([sys.executable,'-c','import sys;sys.path.insert(0,sys.argv[1]);import app;app.init_db()',str(APP)],
                env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            with sqlite3.connect(Path(td)/'clean.sqlite3') as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("INSERT INTO seats(id,store_id,label,seat_type,x,y,display_order) VALUES('BSVM-T2','BSVM','测试','BAR',10,10,1000)")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE seats SET id='BSVM-SEAT-9999' WHERE id='BSVM-SEAT-0001'")
    def test_reject_group_name_alias(self):
        cfg=bsv_layouts.load_layout('BSVM')[0]
        cfg['groups'][0]['id']='BSVM-G-T1'
        with self.assertRaises(bsv_one.ControlError):bsv_one.clean_layout(None,'BSVM',cfg)
if __name__=='__main__':unittest.main()
