#!/usr/bin/python3
"""Root-installed, unprivileged LibreOffice adapter. Fail closed if sandbox unavailable."""
import argparse,os,shutil,subprocess,tempfile
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    if os.geteuid()==0:raise PermissionError("never run office as root")
    for tool in ("/usr/bin/bwrap","/usr/bin/libreoffice"):
        if not Path(tool).is_file():raise RuntimeError("bubblewrap and LibreOffice required")
    with tempfile.TemporaryDirectory(prefix="bsv-office-") as tmp:
        root=Path(tmp);(root/"in").mkdir();(root/"out").mkdir();(root/"home").mkdir()
        shutil.copyfile(args.input,root/"in/source.xlsx")
        cmd=["/usr/bin/bwrap","--unshare-all","--die-with-parent","--new-session",
             "--ro-bind","/usr","/usr","--symlink","usr/lib","/lib","--symlink","usr/lib64","/lib64",
             "--symlink","usr/bin","/bin","--proc","/proc","--dev","/dev","--tmpfs","/tmp","--dir","/etc",
             "--bind",str(root),"/work","--chdir","/work","--clearenv","--setenv","HOME","/work/home",
             "--setenv","PATH","/usr/bin:/bin","--setenv","LANG","C.UTF-8"]
        for path in ("/etc/fonts","/etc/ld.so.cache","/etc/localtime"):
            if Path(path).exists():cmd+=["--ro-bind",path,path]
        cmd+=["/usr/bin/libreoffice","-env:UserInstallation=file:///work/home/profile","--headless","--nologo",
              "--nodefault","--norestore","--convert-to","xlsx","--outdir","/work/out","/work/in/source.xlsx"]
        subprocess.run(cmd,check=True,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        result=root/"out/source.xlsx"
        if not result.is_file():raise RuntimeError("no recalculated workbook")
        with result.open("rb") as src,args.output.open("xb") as dst:shutil.copyfileobj(src,dst)
if __name__=="__main__":main()
