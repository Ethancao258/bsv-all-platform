"""Canonical identity contract and clean-install gates."""
import os,sys,tempfile,unittest,sqlite3,copy,json
from pathlib import Path
APP=Path(__file__).resolve().parents[2]/"services/api/bsv1"
sys.path.insert(0,str(APP))
import bsv_layouts,bsv_one

class CanonicalIds(unittest.TestCase):
    def test_01_all_bundled_store_ids_are_unique_and_prefixed(self):
        all_ids=set()
        for st,cfg,_,_ in bsv_layouts.all_configs():
            if cfg is None:continue
            for seat in cfg['seats']:
                sid=seat['id'];self.assertTrue(sid.startswith(st['store_id']+'-'))
                self.assertNotIn(sid,all_ids);all_ids.add(sid)
            for g in cfg.get('groups',[]):
                self.assertTrue(g['id'].startswith(st['store_id']+'-GROUP-'))
                self.assertNotIn(g['id'],all_ids);all_ids.add(g['id'])
    def test_02_unprefixed_legacy_id_is_rejected_even_if_db_contains_it(self):
        cfg=bsv_layouts.load_layout('BSVM')[0]
        s=cfg['seats'][0]['id'];cfg['seats'][0]['id']='T2'
        with self.assertRaises(bsv_one.ControlError):bsv_one.clean_layout(None,'BSVM',cfg)
        cfg['seats'][0]['id']=s
        cfg['groups'][0]['id']='G-T1'
        with self.assertRaises(bsv_one.ControlError):bsv_one.clean_layout(None,'BSVM',cfg)
    def test_03_bad_source_id_is_rejected_before_DB(self):
        cfg=bsv_layouts.load_layout('BSVM')[0]
        import unittest.mock as mock
        with mock.patch.object(bsv_layouts,'_read_json',side_effect=lambda p:dict(cfg,seats=[dict(cfg['seats'][0],id='BAR1')])):
            with self.assertRaises(bsv_layouts.LayoutError):bsv_layouts.load_layout('BSVM')

class FreshDatabaseBoundary(unittest.TestCase):
    def test_legacy_sqlite_refused_without_mutation(self):
        import subprocess,sys,os,sqlite3,tempfile
        with tempfile.TemporaryDirectory() as td:
            dbfile=Path(td)/'legacy.sqlite3'
            with sqlite3.connect(dbfile) as conn:
                conn.execute('CREATE TABLE stores(id TEXT PRIMARY KEY)')
                conn.execute("INSERT INTO stores VALUES('BSVM')")
                conn.execute('PRAGMA user_version=28')
            env=dict(os.environ,BSV_MODE='staging',BSV_DB_PATH=str(dbfile),BSV_V9_XLSX=os.environ['BSV_V9_XLSX'])
            run=subprocess.run([sys.executable,'-c','import sys;sys.path.insert(0,sys.argv[1]);import app;app.init_db()',str(APP)],
                               env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(run.returncode,0)
            self.assertIn('禁止将V2.x测试数据库原地升级',run.stderr)
            with sqlite3.connect(dbfile) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM stores').fetchone()[0],1)
                self.assertFalse(conn.execute("SELECT name FROM sqlite_master WHERE name='bsv_platform_identity'").fetchone())
