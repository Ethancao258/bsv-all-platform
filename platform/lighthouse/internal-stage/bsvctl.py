#!/usr/bin/env python3
"""Operate a reviewed, isolated Lighthouse release through fixed local commands."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import stage

REPO = Path(__file__).resolve().parents[3]
PROOF_ROOT = stage.ROOT / "control"
REPO_NAME = "Ethancao258/bsv-all-platform"
JOBS = {"architecture", "bsv1", "menu-v13-1", "supply-v2", "identity-r2",
        "db-contract-preflight", "lighthouse-internal-stage", "v4-1-integration",
        "customer-growth-v43"}
CI_FIELDS = ("url", "headSha", "event", "status", "conclusion", "workflowName", "jobs")
REMOTE = re.compile(r"^(?:https://github\.com/|git@github\.com:)Ethancao258/bsv-all-platform(?:\.git)?$")
SHA = re.compile("[a-f0-9]{40}")


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(*args):
    return stage.output(*stage.git(*args))


def release_state():
    return {"deployed_sha": stage.sha_at(stage.ROOT / "current"),
            "rollback_target_sha": stage.sha_at(stage.ROOT / "previous"),
            "pending_activation": (stage.ROOT / "activation.pending").exists()}


def validate_ci(proof, sha):
    if not isinstance(proof, dict):
        raise ValueError("CI evidence must be an object")
    url = proof.get("url", "")
    if (not isinstance(url, str) or not re.fullmatch(
            rf"https://github\.com/{REPO_NAME}/actions/runs/[1-9][0-9]*", url)
            or proof.get("headSha") != sha or proof.get("conclusion") != "success"
            or proof.get("status") != "completed" or proof.get("event") != "pull_request"
            or proof.get("workflowName") != "validate-architecture"):
        raise ValueError("Missing completed successful PR CI evidence for this repository and SHA")
    successful = set()
    jobs = proof.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("CI job evidence must be a list")
    for row in jobs:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or row.get("status") != "completed" or row.get("conclusion") != "success" or row.get("name") in successful:
            raise ValueError("CI contains a missing, failed or duplicated check")
        successful.add(row.get("name"))
    if not JOBS <= successful:
        raise ValueError("CI proof lacks required isolated release checks")
    return url


def export_ci(sha, run_id):
    """Read the evidence from GitHub using the operator's authenticated gh client."""
    if not SHA.fullmatch(sha) or not re.fullmatch("[1-9][0-9]*", run_id):
        raise ValueError("Specify the complete approved SHA and the GitHub Actions run ID")
    source = json.loads(stage.output("gh", "run", "view", run_id, "-R", REPO_NAME,
                                     "--json", ",".join(CI_FIELDS)))
    url = validate_ci(source, sha)
    if url.rsplit("/", 1)[-1] != run_id:
        raise ValueError("GitHub CLI returned an unexpected run")
    proof = {field: source[field] for field in CI_FIELDS if field != "jobs"}
    proof["jobs"] = [{field: row[field] for field in ("name", "status", "conclusion")}
                     for row in source["jobs"]]
    return proof


def persist(payload):
    stage.ROOT.mkdir(mode=0o755, exist_ok=True)
    PROOF_ROOT.mkdir(mode=0o700, exist_ok=True)
    st = PROOF_ROOT.stat()
    if PROOF_ROOT.is_symlink() or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        raise ValueError("Unsafe release evidence directory")
    name = f"{payload['proposed_release_sha']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    stage.write_secret(PROOF_ROOT / name, json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2))
    return name


def record_acceptance(report):
    sha = report["version"]
    manifests = sorted(PROOF_ROOT.glob(f"{sha}-*.json"), reverse=True)
    approved = None
    for path in manifests:
        if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
            raise ValueError("Unsafe release manifest")
        entry = json.loads(path.read_text())
        if (entry.get("approved_release_sha") == entry.get("deployed_sha") == sha
                and entry.get("ci_conclusion") == "success"
                and entry.get("state") == "HOST_VERIFIED"):
            approved = entry
            break
    if not approved:
        raise ValueError("Missing approved host release manifest")
    name = f"acceptance-{sha}-{report['run_id']}.json"
    stage.write_secret(PROOF_ROOT / name, json.dumps(report, ensure_ascii=False, indent=2))
    persist({**approved, "state": report["state"], "host_verification": report["state"],
             "acceptance_report_ref": name})
    return name


def checkpoints():
    return set((stage.DATA / "recovery").glob("*/receipt.json"))


def checkpoint_ref(previous):
    created = sorted(checkpoints() - previous)
    return "recovery/" + created[-1].parent.name + "/receipt.json" if created else None


def deploy(args):
    sha = args.sha
    if not SHA.fullmatch(sha) or git("rev-parse", "HEAD") != sha:
        raise ValueError("Checkout must equal the exact approved 40-character SHA")
    if not REMOTE.fullmatch(git("remote", "get-url", "origin")):
        raise ValueError("Origin must be the BSV ALL repository")
    if not args.approve_isolated or os.geteuid() != 0:
        raise ValueError("Run with sudo and explicit --approve-isolated")
    approve_three_stores = bool(getattr(args, "approve_synthetic_three_store", False))
    if approve_three_stores and not args.approve_isolated:
        raise ValueError("Synthetic three-store scope also requires --approve-isolated")
    if not re.fullmatch(r"(?:ISSUE-[1-9][0-9]*|BSV-CHG-[0-9]{8}-[a-zA-Z0-9-]{1,20})", args.request_id):
        raise ValueError("Specify a versioned request ID")
    if args.ci_proof == "-":
        proof = sys.stdin.buffer.read(65537)
    else:
        with Path(args.ci_proof).open("rb") as source:
            proof = source.read(65537)
    if len(proof) > 65536:
        raise ValueError("CI evidence is too large")
    url = validate_ci(json.loads(proof), sha)
    config = REPO / "config/change-routing.json"
    modules = args.module
    known = {m["module_id"] for m in json.loads(config.read_text())["modules"]}
    if set(modules) - known:
        raise ValueError("Unknown release module")
    before = release_state()
    manifest = {
        "schema_version": "1.0", "request_id": args.request_id, "module_ids": sorted(set(modules)),
        "approved_release_sha": sha, "proposed_release_sha": sha, "repo_head_sha": sha,
        "ci_run_url": url, "ci_conclusion": "success", "ci_evidence": "operator_supplied_github_export",
        "approval_actor": os.environ.get("SUDO_USER", "root"), "approval_timestamp": utc(),
        "migration_ids": stage.migration_revisions(REPO),
        "artifact_digest": "git-tree:" + git("rev-parse", "HEAD^{tree}"),
        "config_revision_hash": hashlib.sha256(config.read_bytes()).hexdigest(),
        "config_revision_scope": "tracked change-routing index; runtime credentials excluded",
        "resource_preflight": "PENDING", "expected_units": [stage.unit(x) for x in stage.START_ORDER],
        "rollout_environment": "isolated", "no_payment": True, "no_prod_db": True,
        "synthetic_store_scope": "BSVM,BSVS,BSVT" if approve_three_stores else "BSVT",
        "backup_snapshot_ref": None, "acceptance_report_ref": None,
        "host_verification": "HOST_NOT_RUN", "state": "RELEASE_APPROVED", **before,
    }
    with stage.locked():
        stage.preflight(sha)
        manifest["resource_preflight"] = "PASS"
        checkpoint_paths = checkpoints()
        manifest.update(release_state(), state="DEPLOYING")
        persist(manifest)
        try:
            stage.deploy(sha, approve_synthetic_three_store=approve_three_stores)
            manifest.update(release_state(), state="HOST_VERIFIED", host_verification="HEALTH_ONLY",
                            isolated_db_revision=stage.database_revision())
        except (RuntimeError, OSError, subprocess.SubprocessError, KeyboardInterrupt):
            manifest.update(release_state(), state="BLOCKED", host_verification="FAILED_OR_ROLLED_BACK")
            raise
        finally:
            manifest["backup_snapshot_ref"] = checkpoint_ref(checkpoint_paths)
            print("RELEASE_MANIFEST", persist(manifest))


def rollback():
    if os.geteuid() != 0:
        raise ValueError("Use sudo for rollback")
    with stage.locked():
        before = release_state()
        sha = before["deployed_sha"]
        if not sha and not before["pending_activation"]:
            raise ValueError("No active or interrupted isolated release")
        previous_checkpoints = checkpoints()
        stage.rollback()
        after = release_state()
        if after == before:
            raise ValueError("Rollback did not change the running release or clear the activation journal")
        if not sha:
            sha = git("rev-parse", "HEAD")
        evidence = {
            "schema_version": "1.0", "proposed_release_sha": sha,
            "rollout_environment": "isolated", "state": "ROLLED_BACK",
            "time": utc(), "before": before, "after": after,
            "backup_snapshot_ref": checkpoint_ref(previous_checkpoints),
            "isolated_db_revision_retained": stage.database_revision() if after["deployed_sha"] else None,
        }
        print("RELEASE_MANIFEST", persist(evidence))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="operation", required=True)
    modes.add_parser("status")
    proof = modes.add_parser("ci-evidence")
    proof.add_argument("--sha", required=True)
    proof.add_argument("--run", required=True)
    release = modes.add_parser("deploy")
    release.add_argument("--sha", required=True)
    release.add_argument("--approve-isolated", action="store_true")
    release.add_argument("--approve-synthetic-three-store", action="store_true",
                         help="explicitly allow only DEMO_LEGAL BSVM/BSVS/BSVT isolated test scope")
    release.add_argument("--ci-proof", required=True)
    release.add_argument("--request-id", required=True)
    release.add_argument("--module", required=True, action="append")
    modes.add_parser("verify")
    modes.add_parser("rollback")
    return parser


def main():
    args = build_parser().parse_args()
    if args.operation == "status":
        print(json.dumps(release_state(), sort_keys=True))
    elif args.operation == "ci-evidence":
        print(json.dumps(export_ci(args.sha, args.run), sort_keys=True))
    elif args.operation == "deploy":
        deploy(args)
    elif args.operation == "verify":
        stage.verify()
    else:
        rollback()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f"Private release blocked: {error}")
