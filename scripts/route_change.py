#!/usr/bin/env python3
"""Resolve change requests against the existing BSV ALL routing index."""
import argparse
from datetime import datetime, timezone
import json
import re
import sys
from uuid import uuid4

from verify_change_routing import REGISTRY, validate

SCOPES = {"UI_COPY", "UI_FLOW", "API_LOGIC", "SECURITY_GRANT", "SOURCE_ENDPOINT",
          "SCHEMA_MIGRATION", "OPERATIONS", "HARDWARE"}


def route(index, intent, requested, scope, environment):
    available = {row["module_id"]: row for row in index["modules"]}
    aliases = index["data_source_namespaces"]
    if set(requested) - available.keys():
        raise ValueError("未知模块")
    exact_sources = [name for name in aliases if re.search(
        r"(?<![a-z0-9_.])" + re.escape(name) + r"(?![a-z0-9_.])", intent, re.I)]
    inferred = []
    for module in available.values():
        words = module["examples"]
        matched = any((re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", intent, re.I)
                       if word.isascii() else word in intent) for word in words)
        if matched or set(exact_sources) & set(module["data_sources"]):
            inferred.append(module["module_id"])
    ids = list(dict.fromkeys(requested or inferred))
    modules = [available[name] for name in ids]
    relevant = list(dict.fromkeys(source for module in modules for source in module["data_sources"]))
    reasons = []
    if not ids:
        reasons.append("未匹配到模块，需明确所属模块")
    if not requested and len(ids) > 1:
        reasons.append("有多个可能的模块，需确认 --module")
    if scope == "SOURCE_ENDPOINT" and len(exact_sources) != 1:
        reasons.append("数据源切换必须明确一个带命名空间的别名")
    if set(exact_sources) - set(relevant):
        reasons.append("数据源不属于确认的模块")
    if environment == "production" or scope in {"SCHEMA_MIGRATION", "SOURCE_ENDPOINT", "SECURITY_GRANT"}:
        reasons.append("需要独立审批和回退证明")
    return {
        "schema_version": "1.0", "state": "REVIEW" if reasons else "ROUTED",
        "scope": scope, "target_environment": environment, "module_ids": ids, "review_reasons": reasons,
        "modules": modules, "data_sources": {name: aliases[name] for name in relevant},
        "candidate_modules": inferred,
        "next_step": "人工确认，随后在同一仓库发起 Codex 任务",
        "connections": {"codex_start": "NOT_CONNECTED", "host_trigger": "NOT_CONNECTED",
                        "cloudbase_migration": "NOT_CONNECTED"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", help="自然语言描述，勿输入凭据或真实个人资料")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--scope", choices=sorted(SCOPES), required=True)
    parser.add_argument("--env", choices=("isolated", "staging", "production"), default="isolated")
    args = parser.parse_args()
    index = json.loads(REGISTRY.read_text(encoding="utf-8"))
    errors = validate(index)
    if errors:
        parser.error("；".join(errors))
    try:
        result = route(index, args.intent, args.module, args.scope, args.env)
    except ValueError as error:
        parser.error(str(error))
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    result["request_id"] = f"BSV-CHG-{date}-{uuid4().hex[:8]}"
    result["user_intent"] = args.intent
    result["approval"] = "PENDING"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "ROUTED" else 2


if __name__ == "__main__":
    sys.exit(main())
