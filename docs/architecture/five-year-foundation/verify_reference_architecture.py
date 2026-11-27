#!/usr/bin/env python3
"""Read-only architecture audit, no runtime or database access.
Run from a clone containing the two pinned Git objects:
  python docs/architecture/five-year-foundation/verify_reference_architecture.py
  python .../verify_reference_architecture.py --governance-ref REF --implementation-ref REF
The default reproduces the frozen reference; overrides audit a new candidate,
not a deployment. No network, no checkout, no writes.
"""
import argparse
import json
import subprocess

GOV = "e2a0368bb89d30627c5eae9be062cae38f82760d"
IMPL = "2052ef51f011be3c5898d816932d8982f420b752"

def git(*args):
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8")

def load(ref, path):
    return json.loads(git("show", f"{ref}:{path}"))

def tree(ref):
    return set(git("ls-tree", "-r", "-t", "--name-only", ref).splitlines())

def audit(gov, impl):
    lock = load(gov, "config/architecture-lock.json")
    apps = load(gov, "config/app-registry.json")["apps"]
    domains = load(gov, "config/domain-registry.json")["domains"]
    owners = load(gov, "config/data-ownership.json")["key_owners"]
    routing = load(impl, "config/change-routing.json")
    gp, ip = tree(gov), tree(impl)
    expected = set(lock["frozen_top_level"])
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    for ref in (gov, impl):
        roots = set(git("ls-tree", "-d", "--name-only", ref).splitlines())
        check(roots == expected, f"{ref}: directory drift: {sorted(roots ^ expected)}")
    declared = {}
    for domain in domains:
        check(domain["root_path"] in gp, f"Missing domain path: {domain['id']}")
        for key in domain["entity_keys"]:
            check(key not in declared, f"Duplicate domain key: {key}")
            declared[key] = domain["id"]
    check(declared == owners, "Domain keys and owner registry disagree")
    for app in apps:
        check(app["path"] in gp and app["path"] in ip, f"Missing app: {app['id']}")
    seen = set()
    for module in routing["modules"]:
        mid = module["module_id"]
        check(mid not in seen, f"Duplicate module: {mid}")
        seen.add(mid)
        for path in module["code_paths"] + module["test_paths"]:
            check(path in ip, f"Missing path: {mid}: {path}")
        for source in module["data_sources"]:
            check(source in routing["data_source_namespaces"], f"Unknown source: {mid}: {source}")
    return {"governance_ref": git("rev-parse", gov).strip(),
            "implementation_ref": git("rev-parse", impl).strip(),
            "roots": len(expected), "apps": len(apps), "domains": len(domains),
            "owner_keys": len(owners), "routes": len(seen), "errors": errors,
            "scope": "STATIC_ONLY_NO_RUNTIME_CERTIFICATION"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--governance-ref", default=GOV)
    parser.add_argument("--implementation-ref", default=IMPL)
    args = parser.parse_args()
    try:
        report = audit(args.governance_ref, args.implementation_ref)
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["errors"] else 0)
