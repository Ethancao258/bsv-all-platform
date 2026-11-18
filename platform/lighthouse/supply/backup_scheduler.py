"""Use cron/systemd outside the app. This script never backs up HR personal records by default."""
import argparse,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from services.api.supply.config import load_settings
from services.api.supply.cache import LocalCache
from services.api.supply.gateway import Gateway
from services.api.supply.backup import make_snapshot,verify_snapshot

def once():
    c=load_settings();cache=LocalCache(c.cache_dir);gateway=Gateway(c,cache)
    result=make_snapshot(c,gateway)
    status=verify_snapshot(Path(result['file']))
    print('ENCRYPTED API SNAPSHOT VERIFIED',result,status)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--loop-hours',type=float,default=0)
    a=p.parse_args()
    if a.loop_hours<0:raise ValueError('周期不可为负')
    while True:
        try:once()
        except Exception as exc:
            print('BACKUP FAILED:',type(exc).__name__,str(exc),file=sys.stderr)
            if not a.loop_hours:sys.exit(1)
        if not a.loop_hours:break
        time.sleep(max(a.loop_hours,0.1)*3600)
