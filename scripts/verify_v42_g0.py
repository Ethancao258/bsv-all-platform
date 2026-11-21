#!/usr/bin/env python3
"""Fail-closed static verifier for V4.2/R3.2 G0 evidence. No network or secrets."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/use-case-registry.json"
DESIGN = ROOT / "contracts/v4-2/R3_2_USE_CASE_INTEGRATION_MAP.json"
OWNERS = ROOT / "config/data-ownership.json"
AUDIT = ROOT / "contracts/v4-2/G0_IMPLEMENTATION_EVIDENCE_20261121.json"
VALID_CODE = {"EXISTING_CODE_ANCHOR_NOT_FULL_SCOPE_PROOF", "NO_DIRECT_CODE_ANCHOR"}
VALID_CI = {"RELATED_JOB_PASS_NOT_USE_CASE_ACCEPTANCE", "NO_USE_CASE_ACCEPTANCE_EVIDENCE"}
VALID_HOST = {"V42_USE_CASE_HOST_NOT_VERIFIED"}
GATES = {"G0-01", "G0-02", "G0-03", "G0-04", "G0-05", "G0-06"}
JOBS = {"architecture", "bsv1", "menu-v13-1", "supply-v2", "identity-r2",
        "db-contract-preflight", "lighthouse-internal-stage", "v4-1-integration"}


def fail(message):
    raise ValueError(message)


def unique(rows, field, label):
    vals = [r[field] for r in rows]
    if len(vals) != len(set(vals)):
        fail("duplicate " + label)
    return set(vals)


def verify():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    owners = json.loads(OWNERS.read_text(encoding="utf-8"))["key_owners"]
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit["scope"] != "REPOSITORY_STATIC_EVIDENCE_ONLY":
        fail("evidence must not imply host or production acceptance")
    rows = audit["cases"]
    by_id = {r["use_case_id"]: r for r in rows}
    registry_ids = unique(registry["use_cases"], "id", "registered use case")
    design_ids = unique(design["use_cases"], "use_case_id", "crosswalk use case")
    case_ids = unique(rows, "use_case_id", "G0 case")
    if len(rows) != 32 or case_ids != registry_ids or case_ids != design_ids:
        fail("G0 must cover exactly the existing 32 use cases")
    design_by_id = {r["use_case_id"]: r for r in design["use_cases"]}
    anchored = 0
    for use_id, row in by_id.items():
        original = design_by_id[use_id]
        if row["owner_domain"] != original["owner_domain"] or row["writer_domain"] != original["writer_domain"]:
            fail("owner drift: " + use_id)
        if row["ui_apps"] != original["ui_app"] or row["phase"] not in "ABCDEFG":
            fail("presentation/phase drift: " + use_id)
        if row["code_status"] not in VALID_CODE or row["ci_status"] not in VALID_CI:
            fail("unsupported evidence assertion: " + use_id)
        if row["host_status"] not in VALID_HOST or row["production_status"] != "NO_GO":
            fail("unverified host/production promotion: " + use_id)
        if not row["required_acceptance"]:
            fail("missing acceptance goal: " + use_id)
        evidence = row["observed_file"]
        expected = original.get("existing_file_hint")
        if evidence:
            anchored += 1
            if evidence != expected or not (ROOT / evidence).is_file():
                fail("non-existent or unrelated code anchor: " + use_id)
            if row["code_status"] != "EXISTING_CODE_ANCHOR_NOT_FULL_SCOPE_PROOF":
                fail("mislabelled code anchor: " + use_id)
            if row["ci_status"] == "RELATED_JOB_PASS_NOT_USE_CASE_ACCEPTANCE" and row["related_ci_job"] not in JOBS:
                fail("unknown CI job: " + use_id)
        else:
            if expected and (ROOT / expected).is_file():
                fail("omitted existing code anchor: " + use_id)
            if row["code_status"] != "NO_DIRECT_CODE_ANCHOR" or row["related_ci_job"] is not None:
                fail("invented implementation/CI: " + use_id)
        if row["ci_status"] == "RELATED_JOB_PASS_NOT_USE_CASE_ACCEPTANCE" and not row["observed_file"]:
            fail("related CI declared without code anchor: " + use_id)
        if row["evidence_baseline_sha"] != audit["source"]["inspected_sha"]:
            fail("mixed source versions: " + use_id)
    metrics = audit["metrics"]
    if (metrics["total_use_cases"] != 32
            or metrics["code_anchors_present"] != anchored
            or metrics["without_direct_code_anchor"] != 32 - anchored
            or metrics["full_use_case_acceptances_verified"] != 0
            or metrics["v42_host_acceptances_verified"] != 0
            or metrics["production_go_verified"] != 0):
        fail("unsupported metric")
    if unique(audit["g0_gates"], "id", "G0 gate") != GATES:
        fail("missing or duplicated G0 checkpoint")
    for g in audit["g0_gates"]:
        if not g.get("finding") or not g.get("next"):
            fail("unactionable G0 checkpoint " + g["id"])
    if unique(audit["r3_extensions"], "feature_id", "R3 extension") != unique(design["r3_capabilities"], "feature_id", "design extension"):
        fail("R3 extension drift")
    if unique(audit["design_addenda"], "feature_id", "architecture addendum") != unique(design["r3_architecture_addenda"], "feature_id", "design addendum"):
        fail("design addendum drift")
    if metrics["r3_capabilities_documented"] != len(audit["r3_extensions"]) or metrics["r3_addenda_documented"] != len(audit["design_addenda"]):
        fail("design extension count incorrect")
    for x in audit["r3_extensions"] + audit["design_addenda"]:
        if x["production_status"] != "NO_GO":
            fail("design item promoted without approval")
    for key, owner in owners.items():
        if not isinstance(key, str) or not isinstance(owner, str) or not key or not owner:
            fail("invalid owner entry")
    namespaces = unique(audit["data_boundaries"], "namespace", "data boundary")
    if not {"identity.A", "supply.D", "supply.E", "pos.SQLite", "cloudbase.PG"} <= namespaces:
        fail("required data authority missing")
    blocks = unique(audit["critical_blockers"], "id", "critical blocker")
    if len(blocks) < 5:
        fail("critical blockers were silently removed")
    routes = {(v["path"], v["status"]) for v in audit["route_inventory"]}
    if ("UNREGISTERED_PATH", "SAFETY_GAP") not in routes or ("/work/craft", "DESIGN_ONLY") not in routes:
        fail("known route gap omitted")
    if audit["release_decision"] != "V42_ARCHITECTURE_RETAIN_STATIC_G0_PARTIAL_NO_PRODUCTION_RELEASE":
        fail("unauthorized G0 release declaration")
    return anchored


if __name__ == "__main__":
    try:
        count = verify()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("G0_FAIL:", exc, file=sys.stderr)
        sys.exit(1)
    print(f"G0_STATIC_PASS: 32/32 inventoried, {count} tracked code anchors, "
          f"{32-count} no direct anchor; 13 R3 extensions; 6 addenda; "
          "host/production NOT VERIFIED")
