"""Package only the reviewed public V13.1 site for an isolated EdgeOne preview."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

SITE = Path(__file__).resolve().parents[3] / "apps/guest-web/bsv1/site"
PUBLIC = (
    "index.html", "entry-redirect.js", "edgeone.json", "cocktail/index.html",
    "cocktail/assets/app.js", "cocktail/assets/style.css", "cocktail/assets/bsv-mark.webp",
    "cocktail/assets/menu-copy.js", "cocktail/assets/menu-config.js", "cocktail/data/menu-public.json",
)


def build(output):
    actual = {p.relative_to(SITE).as_posix() for p in SITE.rglob("*") if p.is_file()}
    if actual != set(PUBLIC) or any(p.is_symlink() for p in SITE.rglob("*")):
        raise ValueError("Unexpected public files or symbolic links")
    output = output.resolve()
    if output.is_relative_to(SITE):
        raise ValueError("Build output must be outside the public source")
    with ZipFile(output, "x") as archive:
        for name in PUBLIC:
            archive.writestr(ZipInfo(name), (SITE / name).read_bytes(), compress_type=ZIP_DEFLATED)
    return hashlib.sha256(output.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print("SHA-256:", build(parser.parse_args().output))
