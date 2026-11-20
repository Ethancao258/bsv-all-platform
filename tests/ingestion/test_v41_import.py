from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "ingestion/v4-1"
SPEC = importlib.util.spec_from_file_location("v41_import", DIRECTORY / "import_batch.py")
imp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(imp)
NOW = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
SOURCE_SHA = "a" * 64
AUTH_SHA = "b" * 64
TIME_START = "2026-11-20T23:45:00+08:00"
TIME_END = "2026-11-21T00:30:00+08:00"
EVIDENCE_START = "2026-11-20T08:00:00Z"
EVIDENCE_END = "2026-12-30T00:00:00Z"


def make_records():
    return {key: [] for key in imp.TABLES}


def packet():
    auth = {"schema_version": "1.0", "mode": "synthetic", "legal_entity_id": "DEMO_LEGAL",
            "approved_by_ref": "SYNTH-REVIEWER", "authorization_ref": "SYNTH-APPROVED",
            "valid_until": EVIDENCE_END, "records": make_records()}
    auth["records"]["companies"] = [{"legal_entity_id": "DEMO_LEGAL", "authority_ref": "SYNTH-ORG"}]
    auth["records"]["stores"] = [{"legal_entity_id": "DEMO_LEGAL", "store_id": s, "kind": "direct",
                                   "authority_ref": "SYNTH-ORG"} for s in ("BSVT", "BSVS")]
    auth["records"]["people"] = [{"legal_entity_id": "DEMO_LEGAL", "tr_code": f"TRA000{i}",
                                 "auth_subject_id": f"subject-synthetic-{i}",
                                 "verification_ref": "SYNTH-VERIFICATION"} for i in (1, 2)]
    auth["records"]["pos_aliases"] = [{"legal_entity_id": "DEMO_LEGAL", "source_system": "bsv1_pos",
                                      "legacy_code": "SYNTH-STAGE-POS-01", "tr_code": "TRA0001",
                                      "verification_ref": "SYNTH-LINK"}]
    batch = {"schema_version": "1.0", "batch_id": "BSV-IMP-SYNTH-TEST", "mode": "synthetic",
             "source_ref": "SYNTH-FIXTURE", "source_sha256": SOURCE_SHA, "authority_snapshot_sha256": AUTH_SHA,
             "legal_entity_id": "DEMO_LEGAL", "approved_by_ref": "SYNTH-REVIEWER", "authorization_ref": "SYNTH-APPROVED",
             "captured_at": EVIDENCE_START, "review_expires_at": EVIDENCE_END, "records": deepcopy(auth["records"])}
    scope = {"legal_entity_id": "DEMO_LEGAL", "store_id": "BSVT", "role": "bartender"}
    batch["records"]["courses"] = [{**scope, "course_id": "SYNTH-COURSE", "version": "1", "source_ref": "SYNTH-SOP"}]
    batch["records"]["media_assets"] = [{
        "legal_entity_id": "DEMO_LEGAL", "asset_ref": "SYNTH-VIDEO", "course_id": "SYNTH-COURSE",
        "course_version": "1", "sha256": "c" * 64, "size_bytes": "105", "mime_type": "video/mp4",
        "rights_ref": "SYNTH-RIGHTS", "scan_evidence_ref": "SYNTH-SCAN-RECEIPT", "rights_expires_at": EVIDENCE_END,
    }]
    batch["records"]["engagements"] = [{
        "legal_entity_id": "DEMO_LEGAL", "tr_code": "TRA0001", "employment_id": "SYNTH-ENGAGEMENT",
        "kind": "part_time", "starts_at": EVIDENCE_START, "ends_at": EVIDENCE_END, "approval_ref": "SYNTH-APPROVAL",
    }]
    batch["records"]["qualifications"] = [{
        **scope, "credential_id": "SYNTH-CREDENTIAL", "tr_code": "TRA0001", "course_id": "SYNTH-COURSE",
        "course_version": "1", "verified_by_tr": "TRA0002", "theory_evidence_ref": "SYNTH-EXAM",
        "practical_evidence_ref": "SYNTH-PRACTICAL", "issued_at": EVIDENCE_START, "expires_at": EVIDENCE_END,
    }]
    batch["records"]["shifts"] = [{
        **scope, "shift_id": "SYNTH-SHIFT-01", "tr_code": "TRA0001", "starts_at": TIME_START, "ends_at": TIME_END,
        "timezone": "Asia/Shanghai", "approval_ref": "SYNTH-SHIFT-APPROVAL",
    }]
    return batch, auth


class ImportTest(unittest.TestCase):
    def test_templates_match_runtime_privacy_contract(self):
        for name, (keys, fields) in imp.TABLES.items():
            with (DIRECTORY / "csv" / f"{name}.csv").open() as source:
                self.assertEqual(list(csv.reader(source)), [list(fields)])
            for file in ("batch.schema.json", "authority-snapshot.schema.json"):
                schema = json.loads((DIRECTORY / "schemas" / file).read_text())
                row = schema["properties"]["records"]["properties"][name]["items"]
                self.assertEqual(row["required"], list(fields))
                self.assertFalse(row["additionalProperties"])
                for field, rule in fields.items():
                    expected = {"enum": list(rule)} if isinstance(rule, tuple) else {"pattern": f"^{rule}$"}
                    self.assertEqual(row["properties"][field], {"type": "string", **expected})
                self.assertTrue(set(keys) <= set(fields))

    def test_complete_preview_and_replay_rollback_restore(self):
        batch, authority = packet()
        report, candidates = imp.preview(batch, authority, SOURCE_SHA, AUTH_SHA, NOW)
        self.assertEqual(report["status"], "PREVIEW_ONLY", report)
        self.assertEqual(report["would_stage"], 5)
        self.assertEqual(report["unchanged_count"], 6)
        self.assertEqual(report["write_count"], 0)
        with tempfile.TemporaryDirectory(prefix="bsv-v41-isolated-import-", dir="/tmp") as tmp:
            directory = Path(tmp)
            with ThreadPoolExecutor(max_workers=2) as workers:
                repeat = [workers.submit(imp.commit, directory, batch, candidates, NOW) for _ in range(2)]
            self.assertEqual(sorted(f.result()["write_count"] for f in repeat), [0, 5])
            self.assertEqual(imp.restore_check(directory)["copied_counts"], {"batches": 1, "claims": 5})
            with sqlite3.connect(directory / imp.DB_NAME) as db:
                raw_log = repr(list(db.iterdump()))
                for secret in ("TRA0001", "SYNTH-STAGE-POS-01", "subject-synthetic-1"):
                    self.assertNotIn(secret, raw_log)
            conflict = deepcopy(batch)
            conflict.update(batch_id="BSV-IMP-CONFLICT", source_sha256="d" * 64)
            conflict["records"]["shifts"][0]["ends_at"] = "2026-11-21T00:35:00+08:00"
            _, conflicting_rows = imp.preview(conflict, authority, "d" * 64, AUTH_SHA, NOW)
            with self.assertRaisesRegex(imp.InputError, "CONFLICT_WITH_ACTIVE_ISOLATED_PROPOSAL"):
                imp.commit(directory, conflict, conflicting_rows, NOW)
            self.assertEqual(imp.rollback(directory, batch["batch_id"], NOW)["write_count"], 5)
            self.assertEqual(imp.commit(directory, batch, candidates, NOW)["status"], "ALREADY_ROLLED_BACK")
            self.assertEqual(imp.restore_check(directory)["copied_counts"], {"batches": 1, "claims": 0})

    def test_privacy_conflict_scope_and_expiry_negatives(self):
        def duplicate(table):
            return lambda batch, auth: batch["records"][table].append(deepcopy(batch["records"][table][0]))

        cases = (
            ("DUPLICATE_CANONICAL_OR_LEGACY_KEY", duplicate("people")),
            ("DUPLICATE_CANONICAL_OR_LEGACY_KEY", duplicate("pos_aliases")),
            ("CANONICAL_KEY_CONFLICT", lambda b, a: b["records"]["pos_aliases"][0].update(tr_code="TRA0002")),
            ("FIELD_OUTSIDE_PRIVACY_ALLOWLIST", lambda b, a: b["records"]["people"][0].update(phone="SENSITIVE-VALUE")),
            ("CROSS_LEGAL_ENTITY", lambda b, a: b["records"]["shifts"][0].update(legal_entity_id="DEMO_OTHER")),
            ("MISSING_REQUIRED_FIELDS", lambda b, a: b["records"]["courses"][0].pop("course_id")),
            ("SOURCE_REVIEW_OR_SNAPSHOT_EXPIRED", lambda b, a: b.update(review_expires_at=EVIDENCE_START)),
            ("MEDIA_RIGHTS_EXPIRED", lambda b, a: b["records"]["media_assets"][0].update(rights_expires_at=EVIDENCE_START)),
            ("PRACTICAL_REVIEWER_NOT_INDEPENDENT_OR_OUT_OF_SCOPE",
             lambda b, a: b["records"]["qualifications"][0].update(verified_by_tr="TRA0001")),
            ("SHIFT_WITHOUT_STORE_ROLE_QUALIFICATION_EVIDENCE", lambda b, a: b["records"]["shifts"][0].update(store_id="BSVS")),
            ("SOURCE_OR_AUTHORITY_HASH_MISMATCH", lambda b, a: b.update(authority_snapshot_sha256="d" * 64)),
            ("PARTNER_STORE_NEEDS_SEPARATE_APPROVAL", lambda b, a: a["records"]["stores"][0].update(kind="partner")),
        )
        for code, mutate in cases:
            with self.subTest(code=code):
                batch, authority = packet()
                mutate(batch, authority)
                report, _ = imp.preview(batch, authority, SOURCE_SHA, AUTH_SHA, NOW)
                self.assertEqual(report["status"], "BLOCKED")
                self.assertIn(code, [row["code"] for row in report["issues"]])
                self.assertEqual(report["authority_write_count"], 0)
                self.assertNotIn("SENSITIVE-VALUE", json.dumps(report))

    def test_alias_with_new_evidence_does_not_bind_twice(self):
        batch, authority = packet()
        batch["records"]["pos_aliases"][0]["verification_ref"] = "SYNTH-LINK-ADDITIONAL-EVIDENCE"
        report, candidates = imp.preview(batch, authority, SOURCE_SHA, AUTH_SHA, NOW)
        self.assertEqual(report["status"], "PREVIEW_ONLY")
        self.assertEqual(report["unchanged_count"], 6)
        self.assertNotIn("pos_aliases", {kind for kind, *_ in candidates})

    def test_csv_assemble_validates_before_creating_output(self):
        batch, _ = packet()
        header = {key: value for key, value in batch.items() if key != "records"}
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            folder = Path(tmp)
            result = folder / "assembled.json"
            for table, (_, fields) in imp.TABLES.items():
                with (folder / f"{table}.csv").open("w", newline="") as output:
                    writer = csv.DictWriter(output, list(fields))
                    writer.writeheader()
                    writer.writerows(batch["records"][table])
            self.assertEqual(imp.assemble(header, folder, result)["input_count"], 11)
            self.assertEqual(imp.read_json(result), batch)
            invalid = folder / "people.csv"
            with invalid.open("w") as output:
                output.write("tr_code,email\nTRA0001,PRIVATE-SENTINEL\n")
            blocked = folder / "blocked.json"
            with self.assertRaisesRegex(imp.InputError, "CSV_HEADER_OUTSIDE_PRIVACY_ALLOWLIST_OR_SCHEMA"):
                imp.assemble(header, folder, blocked)
            self.assertFalse(blocked.exists())

    def test_cross_store_overlap_uses_utc_offset(self):
        batch, authority = packet()
        row = {**batch["records"]["shifts"][0], "shift_id": "SYNTH-OTHER-SHIFT", "store_id": "BSVS",
               "starts_at": "2026-11-20T16:00:00Z", "ends_at": "2026-11-20T16:45:00Z"}
        authority["records"]["shifts"].append(row)
        report, _ = imp.preview(batch, authority, SOURCE_SHA, AUTH_SHA, NOW)
        self.assertIn("OVERLAPPING_SHIFT_FOR_PERSON", [row["code"] for row in report["issues"]])

    def test_cli_review_only_cannot_commit_or_print_payload(self):
        batch, authority = packet()
        with tempfile.TemporaryDirectory(prefix="bsv-v41-isolated-import-", dir="/tmp") as tmp:
            directory = Path(tmp)
            source, snapshot, proposal = [directory / s for s in ("source", "snapshot.json", "batch.json")]
            source.write_bytes(b"PRIVATE-DOCUMENT-SENTINEL")
            authority.update(mode="review_only")
            snapshot.write_text(json.dumps(authority))
            batch.update(mode="review_only", source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                         authority_snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                         captured_at="2020-01-01T00:00:00Z", review_expires_at="2090-01-01T00:00:00Z")
            authority["valid_until"] = "2090-01-01T00:00:00Z"
            snapshot.write_text(json.dumps(authority))
            batch["authority_snapshot_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            batch["records"]["media_assets"][0]["rights_expires_at"] = "2090-01-01T00:00:00Z"
            batch["records"]["qualifications"][0]["expires_at"] = "2090-01-01T00:00:00Z"
            proposal.write_text(json.dumps(batch))
            base = [sys.executable, str(DIRECTORY / "import_batch.py")]
            inputs = ["--source", str(source), "--batch", str(proposal), "--snapshot", str(snapshot)]
            preview = subprocess.run([*base, "dry-run", *inputs], text=True, capture_output=True)
            self.assertEqual(preview.returncode, 0, preview.stdout)
            run = subprocess.run([*base, "commit", *inputs, "--ledger", tmp,
                                  "--confirm-isolated", imp.CONFIRM], text=True, capture_output=True)
            self.assertEqual(run.returncode, 2, run.stdout)
            self.assertIn("PRODUCTION_AND_REAL_DATA_COMMIT_BLOCKED", run.stdout)
            self.assertNotIn("PRIVATE-DOCUMENT-SENTINEL", run.stdout)
            self.assertFalse((directory / imp.DB_NAME).exists())


if __name__ == "__main__":
    unittest.main()
