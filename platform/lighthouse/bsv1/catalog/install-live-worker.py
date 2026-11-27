#!/usr/bin/python3
"""Install the one production publisher timer using real, operator-supplied paths."""
import argparse,json,os,re,subprocess
from pathlib import Path

def path(value,kind):
    p=Path(value).resolve(strict=True)
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+",str(p)):raise ValueError("unsafe systemd path")
    if kind=="file" and not p.is_file():raise ValueError("file missing")
    if kind=="dir" and not p.is_dir():raise ValueError("directory missing")
    return p

def private_file(value):
    p=path(value,"file")
    st=p.stat()
    if st.st_uid!=0 or st.st_mode&0o077:raise PermissionError("root private policy/environment required")
    return p

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("repo","python","env","policy"):p.add_argument("--"+key,required=True)
    p.add_argument("--enable",action="store_true")
    a=p.parse_args()
    if os.geteuid()!=0:raise PermissionError("root installation required")
    repo=path(a.repo,"dir");python=path(a.python,"file")
    env=private_file(a.env);policy=private_file(a.policy);data=json.loads(policy.read_text())
    if data.get("status")!="APPROVED_PRODUCTION_CATALOG":raise PermissionError("not approved production policy")
    head=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],text=True).strip()
    if head!=data.get("approved_git_sha"):raise ValueError("actual approved commit differs")
    source=path(repo/"services/api/bsv1/bsv_hq_release_worker.py","file")
    if repo.stat().st_uid!=0 or source.stat().st_uid!=0 or source.stat().st_mode&0o022:
        raise PermissionError("publisher source must be root controlled")
    writable=[path(data[k],"dir") for k in ("draft_root","approval_dir","catalog_dir")]
    writable += [path(data[k],"file").parent for k in ("pos_database","public_menu_json")]
    if any(repo==x or repo in x.parents or x in repo.parents for x in writable):
        raise ValueError("runtime data must be separate from code")
    service="""[Unit]
Description=BSV ALL production catalog publisher
After=network-online.target postgresql.service
[Service]
Type=oneshot
User=root
WorkingDirectory={repo}
EnvironmentFile={env}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart={python} {source} --policy {policy}
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={writable}
TimeoutStartSec=180
""".format(repo=repo,env=env,python=python,source=source,policy=policy,writable=" ".join(map(str,writable)))
    timer="""[Unit]
Description=BSV ALL catalog publication queue
[Timer]
OnBootSec=30s
OnUnitInactiveSec=60s
AccuracySec=5s
Unit=bsv-all-catalog-publisher.service
[Install]
WantedBy=timers.target
"""
    for name,content in (("bsv-all-catalog-publisher.service",service),("bsv-all-catalog-publisher.timer",timer)):
        target=Path("/etc/systemd/system")/name
        if target.is_symlink():raise ValueError("existing unit is symlink")
        if target.exists() and target.read_text()!=content:raise ValueError("existing unit differs; preserve and reconcile")
        if not target.exists():
            fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644)
            with os.fdopen(fd,"w") as f:f.write(content)
    subprocess.run(["systemctl","daemon-reload"],check=True)
    if a.enable:subprocess.run(["systemctl","enable","--now","bsv-all-catalog-publisher.timer"],check=True)
    print("INSTALLED_ENABLED" if a.enable else "INSTALLED_DISABLED")
if __name__=="__main__":main()
