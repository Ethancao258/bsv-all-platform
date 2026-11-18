"""One isolated clean-install backup and recovery check; cannot attest cloud backups."""
import os,subprocess,sys,sqlite3,tempfile,unittest
from pathlib import Path
APP=Path(__file__).resolve().parents[2]/"services/api/bsv1"
class BackupRecovery(unittest.TestCase):
    def test_sqlite_online_consistent_restore(self):
        with tempfile.TemporaryDirectory(prefix='bsv-backup-') as td:
            db=Path(td)/'operational.sqlite3'
            out=Path(td)/'backups'
            env=dict(os.environ,BSV_MODE='staging',BSV_DB_PATH=str(db),BSV_V9_XLSX=os.environ['BSV_V9_XLSX'],BSV_BACKUP_DIR=str(out))
            exe=[sys.executable,'-c',"import sys;sys.path.insert(0,sys.argv[1]);import app;app.init_db()",str(APP)]
            installed=subprocess.run(exe,env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(installed.returncode,0,installed.stderr)
            run=subprocess.run([sys.executable,str(APP/'backup_db.py')],env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            files=list(out.glob('operational_backup_*.sqlite3'))
            self.assertEqual(len(files),1)
            with sqlite3.connect(files[0]) as restored:
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(restored.execute('SELECT count(*) FROM seats').fetchone()[0],43)
                self.assertEqual(restored.execute('SELECT count(*) FROM stores').fetchone()[0],4)
if __name__=='__main__':unittest.main()
