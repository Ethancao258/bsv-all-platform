#!/usr/bin/env python3
"""Validate scoped import proposals and rehearse their audit lifecycle locally."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone

MAX_METADATA = 4 * 1024 * 1024
MAX_ROWS = 10_000
STAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
CODE = r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}"
REF = r"[A-Za-z][A-Za-z0-9_.:-]{5,99}"
TR = r"TR[A-Z][0-9]{4}"
STORE = r"BSV[A-Z0-9]{1,12}"
CANONICAL_ID = r"(?:[A-Za-z][A-Za-z0-9_-]{2,63}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
SHA = r"[0-9a-f]{64}"
VERSION = r"[1-9][0-9]{0,8}"
POS = ("bsv1_pos",)
ROLES = ("bartender",)
APPLICATION_ID = 0x42535641
CONFIRM = "ISOLATED_SYNTHETIC_ONLY"
DB_NAME = "v41-import-ledger.sqlite3"
HERE = Path(__file__).resolve().parent

BATCH_HEADER = {
    "schema_version": ("1.0",),
    "batch_id": r"BSV-IMP-[A-Z0-9-]{3,48}",
    "mode": ("synthetic", "review_only"),
    "source_ref": REF,
    "source_sha256": SHA,
    "authority_snapshot_sha256": SHA,
    "legal_entity_id": CODE,
    "approved_by_ref": REF,
    "authorization_ref": REF,
    "captured_at": STAMP,
    "review_expires_at": STAMP,
}
AUTHORITY_HEADER = {
    "schema_version": ("1.0",),
    "mode": ("synthetic", "review_only"),
    "legal_entity_id": CODE,
    "authorization_ref": REF,
    "approved_by_ref": REF,
    "valid_until": STAMP,
}
# Required metadata only. Canonical organization and workforce identifiers
# must occur in the supplied authorized snapshot. No source here can issue TR.
TABLES = {
    "companies": (("legal_entity_id",), {
        "legal_entity_id": CODE, "authority_ref": REF,
    }),
    "stores": (("store_id",), {
        "store_id": STORE, "legal_entity_id": CODE, "kind": ("direct", "partner"),
        "authority_ref": REF,
    }),
    "people": (("tr_code",), {
        "tr_code": TR, "legal_entity_id": CODE, "auth_subject_id": REF, "verification_ref": REF,
    }),
    "pos_aliases": (("legal_entity_id", "source_system", "legacy_code"), {
        "legal_entity_id": CODE, "source_system": POS, "legacy_code": CODE, "tr_code": TR,
        "verification_ref": REF,
    }),
    "engagements": (("employment_id",), {
        "employment_id": CANONICAL_ID, "legal_entity_id": CODE, "tr_code": TR,
        "kind": ("employee", "part_time", "contractor", "partner"),
        "starts_at": STAMP, "ends_at": STAMP, "approval_ref": REF,
    }),
    "courses": (("course_id", "version"), {
        "course_id": CODE, "version": VERSION, "legal_entity_id": CODE, "store_id": rf"(?:{STORE})?",
        "role": ROLES, "source_ref": REF,
    }),
    "media_assets": (("asset_ref",), {
        "asset_ref": REF, "course_id": CODE, "course_version": VERSION,
        "legal_entity_id": CODE, "sha256": SHA, "size_bytes": r"[1-9][0-9]{0,11}",
        "mime_type": ("video/mp4", "video/webm", "application/pdf", "image/png", "image/jpeg"),
        "rights_ref": REF, "scan_evidence_ref": REF, "rights_expires_at": STAMP,
    }),
    "qualifications": (("credential_id",), {
        "credential_id": CANONICAL_ID, "legal_entity_id": CODE, "tr_code": TR, "store_id": STORE,
        "role": ROLES, "course_id": CODE, "course_version": VERSION,
        "verified_by_tr": TR, "theory_evidence_ref": REF, "practical_evidence_ref": REF,
        "issued_at": STAMP, "expires_at": STAMP,
    }),
    "shifts": (("shift_id",), {
        "shift_id": CANONICAL_ID, "legal_entity_id": CODE, "store_id": STORE, "tr_code": TR,
        "role": ROLES, "starts_at": STAMP, "ends_at": STAMP, "timezone": ("Asia/Shanghai",),
        "approval_ref": REF,
    }),
}
BASE_AUTHORITY = frozenset(("companies", "stores", "people"))
SYNTH_STORES = {"BSVM", "BSVS", "BSVT"}
SYNTH_OPAQUE = re.compile(r"(?:SYNTH[-_]|DEMO[-_])[A-Za-z0-9_:/.-]+")


class InputError(ValueError):
    """The message is a predefined code, without input values."""


def reject(code):
    raise InputError(code)


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            reject("DUPLICATE_JSON_FIELD")
        result[name] = value
    return result


def read_json(path, *, with_hash=False):
    if not path.is_file() or path.stat().st_size > MAX_METADATA:
        reject("METADATA_FILE_MISSING_OR_TOO_LARGE")
    with path.open("rb") as file:
        data = file.read(MAX_METADATA + 1)
    if len(data) > MAX_METADATA:
        reject("METADATA_FILE_MISSING_OR_TOO_LARGE")
    decoded = json.loads(data, object_pairs_hook=unique_object)
    return (decoded, hashlib.sha256(data).hexdigest()) if with_hash else decoded


def date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def source_digest(path):
    if not path.is_file():
        reject("SOURCE_MUST_BE_A_LOCAL_FILE")
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def field_issues(record, fields):
    if not isinstance(record, dict):
        return ["INVALID_RECORD"]
    issues = []
    if set(record) - fields.keys():
        issues.append("FIELD_OUTSIDE_PRIVACY_ALLOWLIST")
    if fields.keys() - record.keys():
        issues.append("MISSING_REQUIRED_FIELDS")
    for name, rule in fields.items():
        if name not in record:
            continue
        value = record[name]
        if not isinstance(value, str) or (
            value not in rule if isinstance(rule, tuple) else not re.fullmatch(rule, value)
        ):
            issues.append(f"INVALID_{name.upper()}")
        elif rule == STAMP:
            try:
                date(value)
            except ValueError:
                issues.append(f"INVALID_{name.upper()}")
    return issues


def record_key(table, record):
    return tuple(record[name] for name in TABLES[table][0])


def row_error(issues, table, row, code):
    issues.append({"table": table, "row": row, "code": code})


def index_records(document, field, issues):
    report = document.get(field)
    if not isinstance(report, dict) or report.keys() != TABLES.keys():
        row_error(issues, field, 0, "RECORD_SECTIONS_MISSING_OR_UNEXPECTED")
        return {}, 0
    if any(not isinstance(rows, list) for rows in report.values()):
        row_error(issues, field, 0, "RECORD_SECTION_MUST_BE_ARRAY")
        return {}, 0
    total = sum(len(rows) for rows in report.values())
    if total > MAX_ROWS:
        row_error(issues, field, 0, "METADATA_ROW_LIMIT")
        return {}, total
    indexed = {}
    for table, rows in report.items():
        entries = indexed[table] = {}
        for i, row in enumerate(rows, 1):
            invalid = field_issues(row, TABLES[table][1])
            for code in invalid:
                row_error(issues, table, i, code)
            if invalid:
                continue
            key = record_key(table, row)
            if key in entries:
                row_error(issues, table, i, "DUPLICATE_CANONICAL_OR_LEGACY_KEY")
            else:
                entries[key] = i, row
    return indexed, total


def synthetic_row(row):
    opaque = {name: value for name, value in row.items() if name.endswith("_ref")}
    for name in ("legal_entity_id", "legacy_code", "course_id"):
        if name in row:
            opaque[name] = row[name]
    return all(SYNTH_OPAQUE.fullmatch(value) for value in opaque.values())


def foreign_key_checks(proposed, authority, issues, current, entity, synthetic):
    combined = {table: {**authority[table], **proposed[table]} for table in TABLES}
    authoritative_shifts = [row for _, row in authority["shifts"].values()]
    role_evidence = [row for _, row in combined["qualifications"].values()]
    active_relations = [row for _, row in combined["engagements"].values()]
    subjects = {}
    for i, row in combined["people"].values():
        previous = subjects.setdefault(row["auth_subject_id"], row["tr_code"])
        if previous != row["tr_code"]:
            row_error(issues, "people", i, "SUBJECT_BINDS_MULTIPLE_TR")
    candidates, unchanged, proposed_shifts = [], 0, []
    for table, entries in proposed.items():
        for key, (i, row) in entries.items():
            def issue(code):
                row_error(issues, table, i, code)

            if row["legal_entity_id"] != entity:
                issue("CROSS_LEGAL_ENTITY")
            if synthetic and (not synthetic_row(row) or (
                    "store_id" in row and row["store_id"] not in SYNTH_STORES)):
                issue("NON_SYNTHETIC_SCOPE_OR_REFERENCE")
            stored = authority[table].get(key)
            same_alias = stored and table == "pos_aliases" and row["tr_code"] == stored[1]["tr_code"]
            if stored and row != stored[1] and not same_alias:
                issue("CANONICAL_KEY_CONFLICT")
            if table in BASE_AUTHORITY and not stored:
                issue("CANONICAL_BASE_ID_NOT_AUTHORIZED")
            if (entity,) not in authority["companies"]:
                issue("LEGAL_ENTITY_NOT_AUTHORIZED")
            if table != "stores" and row.get("store_id"):
                store = authority["stores"].get((row["store_id"],))
                if not store or store[1]["legal_entity_id"] != entity:
                    issue("STORE_UNKNOWN_OR_CROSS_LEGAL")
                elif store[1]["kind"] != "direct":
                    issue("PARTNER_STORE_NEEDS_SEPARATE_APPROVAL")
            if "tr_code" in row:
                person = authority["people"].get((row["tr_code"],))
                if not person or person[1]["legal_entity_id"] != entity:
                    issue("PERSON_UNKNOWN_OR_CROSS_LEGAL")
            if table in {"media_assets", "qualifications"}:
                course = combined["courses"].get((row["course_id"], row["course_version"]))
                if not course or course[1]["legal_entity_id"] != entity:
                    issue("COURSE_VERSION_UNKNOWN_OR_CROSS_LEGAL")
                elif table == "qualifications" and any(row[key] != course[1][key] for key in ("store_id", "role")):
                    issue("QUALIFICATION_COURSE_SCOPE_MISMATCH")
            if table == "media_assets" and date(row["rights_expires_at"]) <= current:
                issue("MEDIA_RIGHTS_EXPIRED")
            if table == "qualifications":
                reviewer = authority["people"].get((row["verified_by_tr"],))
                if not reviewer or row["verified_by_tr"] == row["tr_code"] or reviewer[1]["legal_entity_id"] != entity:
                    issue("PRACTICAL_REVIEWER_NOT_INDEPENDENT_OR_OUT_OF_SCOPE")
                if not date(row["issued_at"]) <= current < date(row["expires_at"]):
                    issue("QUALIFICATION_EXPIRED_OR_NOT_YET_EFFECTIVE")
            if table in {"engagements", "shifts"} and not date(row["starts_at"]) < date(row["ends_at"]):
                issue("INVALID_TIME_WINDOW")
            if table == "shifts" and not stored:
                proposed_shifts.append((i, row))
                start, end = date(row["starts_at"]), date(row["ends_at"])
                matches = lambda item, fields: all(item.get(k) == row[k] for k in fields)
                if not any(matches(item, ("tr_code", "legal_entity_id")) and
                           date(item["starts_at"]) <= start < end <= date(item["ends_at"]) for item in active_relations):
                    issue("SHIFT_WITHOUT_ENGAGEMENT_EVIDENCE")
                if not any(matches(item, ("tr_code", "legal_entity_id", "store_id", "role")) and
                           date(item["issued_at"]) <= start < end <= date(item["expires_at"]) for item in role_evidence):
                    issue("SHIFT_WITHOUT_STORE_ROLE_QUALIFICATION_EVIDENCE")
            if stored and (row == stored[1] or same_alias):
                unchanged += 1
            elif not stored:
                candidates.append((table, digest(key), digest(row)))
    shifts_by_person = {}
    for row in authoritative_shifts:
        shifts_by_person.setdefault(row["tr_code"], []).append((date(row["starts_at"]), date(row["ends_at"])))
    for i, row in sorted(proposed_shifts, key=lambda item: date(item[1]["starts_at"])):
        window = date(row["starts_at"]), date(row["ends_at"])
        prior = shifts_by_person.setdefault(row["tr_code"], [])
        if any(window[0] < end and start < window[1] for start, end in prior):
            row_error(issues, "shifts", i, "OVERLAPPING_SHIFT_FOR_PERSON")
        prior.append(window)
    return candidates, unchanged


def preview(batch, snapshot, source_sha, snapshot_sha, current):
    issues = []
    if not isinstance(batch, dict) or not isinstance(snapshot, dict):
        reject("DOCUMENT_MUST_BE_OBJECT")
    for document, contract, label in ((batch, BATCH_HEADER, "batch"), (snapshot, AUTHORITY_HEADER, "authority")):
        header = {name: value for name, value in document.items() if name != "records"}
        for code in field_issues(header, contract):
            row_error(issues, label, 0, code)
    proposed, count = index_records(batch, "records", issues)
    authority, _ = index_records(snapshot, "records", issues)
    if issues:
        return {"status": "BLOCKED", "input_count": count, "would_stage": 0,
                "unchanged_count": 0, "write_count": 0, "authority_write_count": 0, "issues": issues}, []
    for field in ("mode", "legal_entity_id", "authorization_ref"):
        if batch[field] != snapshot[field]:
            row_error(issues, "authority", 0, "AUTHORIZED_SCOPE_MISMATCH")
    if batch["source_sha256"] != source_sha or batch["authority_snapshot_sha256"] != snapshot_sha:
        row_error(issues, "batch", 0, "SOURCE_OR_AUTHORITY_HASH_MISMATCH")
    if (date(batch["captured_at"]) > current or date(batch["review_expires_at"]) <= current
            or date(snapshot["valid_until"]) <= current):
        row_error(issues, "batch", 0, "SOURCE_REVIEW_OR_SNAPSHOT_EXPIRED")
    if batch["mode"] == "synthetic" and not synthetic_row(batch):
        row_error(issues, "batch", 0, "NON_SYNTHETIC_SCOPE_OR_REFERENCE")
    candidates, unchanged = foreign_key_checks(proposed, authority, issues, current, batch["legal_entity_id"],
                                               batch["mode"] == "synthetic")
    status = "BLOCKED" if issues else "IMPORT_NOT_RUN" if not count else "PREVIEW_ONLY"
    return {"status": status, "input_count": count, "would_stage": 0 if issues else len(candidates),
            "unchanged_count": unchanged, "write_count": 0, "authority_write_count": 0, "issues": issues}, candidates


@contextmanager
def ledger(directory, *, create=True):
    original = directory.absolute()
    if original.is_symlink() or original.resolve() != original:
        reject("LEDGER_PATH_MUST_BE_CANONICAL")
    try:
        original.relative_to(Path("/tmp").resolve())
    except ValueError:
        reject("LEDGER_ONLY_IN_LOCAL_TEMP_ISOLATION")
    if not re.fullmatch(r"bsv-v41-isolated-[a-zA-Z0-9_-]+", original.name):
        reject("LEDGER_DIRECTORY_NAME_REQUIRES_ISOLATION_PREFIX")
    info = original.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        reject("LEDGER_DIRECTORY_MUST_BE_PRIVATE")
    path = original / DB_NAME
    if not create and not path.exists():
        reject("NO_EXISTING_ISOLATED_LEDGER")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        state = path.lstat()
        if (not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid() or
                state.st_mode & 0o077 or state.st_nlink != 1):
            reject("LEDGER_FILE_MUST_BE_PRIVATE")
    else:
        os.close(fd)
    with closing(sqlite3.connect(path, timeout=10)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        current_id = db.execute("PRAGMA application_id").fetchone()[0]
        if create and not current_id and not db.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone():
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("""CREATE TABLE batches(
                batch_id TEXT PRIMARY KEY, source_sha TEXT NOT NULL UNIQUE, proposal_sha TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('STAGED','ROLLED_BACK')), staged_count INTEGER NOT NULL,
                created_at TEXT NOT NULL, rolled_back_at TEXT)""")
            db.execute("""CREATE TABLE claims(
                kind TEXT NOT NULL, key_hash TEXT NOT NULL, row_hash TEXT NOT NULL,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id), PRIMARY KEY(kind,key_hash))""")
        elif current_id != APPLICATION_ID:
            reject("TARGET_IS_NOT_AN_IMPORT_LEDGER")
        with db:
            yield db


def commit(directory, batch, candidates, current):
    if batch["mode"] != "synthetic":
        reject("PRODUCTION_AND_REAL_DATA_COMMIT_BLOCKED")
    proposal_sha = digest(batch)
    with ledger(directory) as db:
        repeated = db.execute("SELECT batch_id,source_sha,proposal_sha,state FROM batches WHERE batch_id=? OR source_sha=?",
                              (batch["batch_id"], batch["source_sha256"])).fetchall()
        if repeated:
            if len(repeated) != 1 or repeated[0][:3] != (batch["batch_id"], batch["source_sha256"], proposal_sha):
                reject("BATCH_OR_SOURCE_ALREADY_STAGED_WITH_DIFFERENT_MAPPING")
            return {"status": "ALREADY_STAGED" if repeated[0][3] == "STAGED" else "ALREADY_ROLLED_BACK",
                    "write_count": 0, "authority_write_count": 0}
        rows, unchanged = [], 0
        for kind, key_hash, row_hash in candidates:
            existing = db.execute("SELECT row_hash FROM claims WHERE kind=? AND key_hash=?", (kind, key_hash)).fetchone()
            if existing and existing[0] != row_hash:
                reject("CONFLICT_WITH_ACTIVE_ISOLATED_PROPOSAL")
            if existing:
                unchanged += 1
            else:
                rows.append((kind, key_hash, row_hash, batch["batch_id"]))
        db.execute("INSERT INTO batches VALUES (?,?,?,'STAGED',?,?,NULL)",
                   (batch["batch_id"], batch["source_sha256"], proposal_sha, len(rows), current.isoformat()))
        db.executemany("INSERT INTO claims VALUES (?,?,?,?)", rows)
    return {"status": "STAGED_SYNTHETIC_PROPOSAL", "write_count": len(rows),
            "duplicate_proposal_count": unchanged, "receipt_write_count": 1, "authority_write_count": 0}


def rollback(directory, batch_id, current):
    with ledger(directory, create=False) as db:
        state = db.execute("SELECT state FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if not state:
            reject("BATCH_NOT_IN_ISOLATED_LEDGER")
        if state[0] == "ROLLED_BACK":
            return {"status": "ALREADY_ROLLED_BACK", "write_count": 0, "authority_write_count": 0}
        count = db.execute("DELETE FROM claims WHERE batch_id=?", (batch_id,)).rowcount
        db.execute("UPDATE batches SET state='ROLLED_BACK', rolled_back_at=? WHERE batch_id=?",
                   (current.isoformat(), batch_id))
    return {"status": "ROLLED_BACK", "write_count": count, "receipt_write_count": 1, "authority_write_count": 0}


def restore_check(directory):
    # Open a read snapshot after the write-capable ledger guard has closed.
    with ledger(directory, create=False):
        pass
    directory = directory.absolute()
    path = directory / DB_NAME
    with tempfile.TemporaryDirectory(dir=directory) as work:
        target = Path(work) / "restore.sqlite3"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as live, closing(sqlite3.connect(target)) as clone:
            live.backup(clone)
            if clone.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                reject("ISOLATED_RESTORE_INTEGRITY_FAILED")
            if clone.execute("PRAGMA foreign_key_check").fetchall():
                reject("ISOLATED_RESTORE_FOREIGN_KEY_FAILED")
            counts = {table: clone.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("batches", "claims")}
    return {"status": "ISOLATED_RESTORE_CHECKED", "copied_counts": counts, "write_count": 0,
            "authority_write_count": 0}


def assemble(header, directory, output):
    if not isinstance(header, dict) or field_issues(header, BATCH_HEADER):
        reject("INVALID_BATCH_HEADER")
    rows = {}
    for table, (_, fields) in TABLES.items():
        path = directory / (table + ".csv")
        if not path.is_file() or path.stat().st_size > MAX_METADATA:
            reject("CSV_MISSING_OR_TOO_LARGE")
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            if reader.fieldnames != list(fields):
                reject("CSV_HEADER_OUTSIDE_PRIVACY_ALLOWLIST_OR_SCHEMA")
            records = rows[table] = []
            for record in reader:
                invalid = field_issues(record, fields)
                if invalid:
                    reject(invalid[0])
                if header["mode"] == "synthetic" and not synthetic_row(record):
                    reject("NON_SYNTHETIC_SCOPE_OR_REFERENCE")
                records.append(record)
                if len(records) > MAX_ROWS:
                    reject("METADATA_ROW_LIMIT")
    if sum(map(len, rows.values())) > MAX_ROWS:
        reject("METADATA_ROW_LIMIT")
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as stream:
        json.dump({**header, "records": rows}, stream, ensure_ascii=False, indent=2)
    return {"status": "PROPOSAL_ASSEMBLED", "input_count": sum(map(len, rows.values())),
            "write_count": 0, "authority_write_count": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="operation", required=True)
    for name in ("dry-run", "commit"):
        command = modes.add_parser(name)
        for option in ("batch", "snapshot", "source"):
            command.add_argument("--" + option, required=True, type=Path)
    for name in ("commit", "rollback", "restore-check"):
        command = modes.choices.get(name) or modes.add_parser(name)
        command.add_argument("--ledger", required=True, type=Path)
        command.add_argument("--confirm-isolated", choices=(CONFIRM,), required=True)
    modes.choices["rollback"].add_argument("--batch-id", required=True)
    command = modes.add_parser("assemble")
    for option in ("header", "csv-dir", "output"):
        command.add_argument("--" + option, required=True, type=Path)
    args = parser.parse_args()
    current = datetime.now(timezone.utc)
    try:
        if args.operation == "assemble":
            result = assemble(read_json(args.header), args.csv_dir, args.output)
        elif args.operation == "rollback":
            if not re.fullmatch(BATCH_HEADER["batch_id"], args.batch_id):
                reject("INVALID_BATCH_ID")
            result = rollback(args.ledger, args.batch_id, current)
        elif args.operation == "restore-check":
            result = restore_check(args.ledger)
        else:
            batch = read_json(args.batch)
            snapshot, snapshot_sha = read_json(args.snapshot, with_hash=True)
            result, candidates = preview(batch, snapshot, source_digest(args.source), snapshot_sha, current)
            if args.operation == "commit" and result["status"] == "PREVIEW_ONLY":
                result.update(commit(args.ledger, batch, candidates, current))
    except (InputError, OSError, sqlite3.Error, ValueError, TypeError, csv.Error, RecursionError) as error:
        code = str(error) if isinstance(error, InputError) else type(error).__name__
        result = {"status": "BLOCKED", "write_count": 0, "authority_write_count": 0,
                  "issues": [{"table": "batch", "row": 0, "code": code}]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
