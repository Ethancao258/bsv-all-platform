"""Bootstrap just one synthetic POS alias and the existing test workbook."""
import os
from pathlib import Path
import runpy
import secrets
import sys

ROOT = Path(__file__).resolve().parents[3]
data = Path(os.environ["BSV_DB_PATH"]).parent
if (os.environ.get("BSV_POS_INTERNAL_STAGE") != "1" or data.name != "pos"
        or not data.parent.name.startswith("bsv-all-internal-stage")):
    raise SystemExit("Synthetic bootstrap requires the internal stage's isolated POS directory")
workbook = Path(os.environ["BSV_V9_XLSX"])
if workbook != data / "synthetic-v9.xlsx":
    raise SystemExit("Unexpected synthetic workbook location")
if not workbook.exists():
    temp = workbook.with_suffix(".pending")
    runpy.run_path(str(ROOT / "tests/bsv1/make_fixture.py"))["write_fixture"](temp)
    temp.replace(workbook)
sys.path.insert(0, str(ROOT / "services/api/bsv1"))
import app as pos

pos.init_db()
with pos.tx() as db:
    staff = db.execute("SELECT * FROM staff WHERE staff_code='STAGEPOS01'").fetchone()
    if staff is None:
        salt = secrets.token_bytes(16)
        pin = os.environ["BSV_STAGE_POS_PIN"]
        db.execute("INSERT INTO staff(id,staff_code,pin_salt,pin_digest,role,enabled) VALUES (?,?,?,?,?,1)",
                   ("SYNTH-STAGE-POS-01", "STAGEPOS01", salt.hex(), pos.pin_hash(pin, salt), "MANAGER"))
        db.execute("INSERT INTO staff_store_access(staff_id,store_id) VALUES (?,?)", ("SYNTH-STAGE-POS-01", "BSVT"))
    elif staff["id"] != "SYNTH-STAGE-POS-01":
        raise SystemExit("Unexpected existing synthetic POS staff mapping")
    layout = pos.bsv_one.current(db, "BSVT")
    if not db.execute("SELECT layout_ready FROM stores WHERE id='BSVT'").fetchone()[0]:
        operator = dict(db.execute("SELECT * FROM staff WHERE staff_code='STAGEPOS01'").fetchone())
        db.execute("INSERT OR IGNORE INTO bsv_hq_roles(staff_id,role,granted_at) VALUES (?,'HQ_ADMIN',?)",
                   (operator["id"], pos.bsv_one.now()))
        draft = pos.bsv_one.draft(db, operator, "BSVT", layout["layout"], layout["version"])
        pos.bsv_one.publish(db, operator, "BSVT", draft["revision_id"])
        db.execute("DELETE FROM bsv_hq_roles WHERE staff_id=? AND role='HQ_ADMIN'", (operator["id"],))
