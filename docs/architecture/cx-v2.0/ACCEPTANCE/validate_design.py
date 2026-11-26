"""Design-only; requires jsonschema[format]. No runtime access."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator, FormatChecker
R=Path(__file__).resolve().parents[1]
def load(p): return json.loads((R/p).read_text(encoding="utf-8"))
s=load("CONTRACTS/PAYLOAD-SCHEMAS.json")
Draft202012Validator.check_schema(s)
defs=s["$defs"]
def val(name,data):
    return Draft202012Validator({"$schema":s["$schema"],"$defs":defs,"$ref":"#/$defs/"+name},format_checker=FormatChecker()).is_valid(data)
def sample(n):
    if "$ref" in n: return sample(defs[n["$ref"].split("/")[-1]])
    if "enum" in n: return n["enum"][0]
    if "const" in n: return n["const"]
    t=n.get("type")
    if t=="object": return {k:sample(n["properties"][k]) for k in n.get("required",[])}
    if t=="array": return [sample(n["items"]) for _ in range(n.get("minItems",0))]
    if t=="integer": return n.get("minimum",0)
    if t=="boolean": return False
    if t=="string":
        if n.get("format")=="date-time": return "2026-01-01T00:00:00Z"
        if n.get("format")=="date": return "2026-01-01"
        if n.get("pattern")=="^[A-Z]{3}$": return "CNY"
        if "64}" in n.get("pattern",""): return "a"*64
        return "SYN"
    raise ValueError(n)
ops=load("CONTRACTS/OPERATIONS.json")["operations"]
ids={x["id"] for x in ops}; assert len(ids)==len(ops)
count=0
for x in ops:
    for side,ref in x["schema_refs"].items():
        name=ref.split("/")[-1]; data=sample(defs[name])
        if name=="cx_auth_login_v1_response": data.update(session_ref="SYN-SESSION",customer_id="SYN-C1")
        assert val(name,data),(name,data)
        if isinstance(data,dict): assert not val(name,{**data,"unexpected_field":True}),name
        count+=1
assert not val("cx_order_submit_v1_request",{"visit_id":"SYN","items":[{"product_id":"SYN","quantity":1}],"quote_version":"SYN"})
assert not val("cx_auth_login_v1_response",{"status":"REGISTRATION_REQUIRED"})
q=sample(defs["Quote"]); assert val("Quote",q); q["expires_at"]="2026-02-30T00:00:00Z"; assert not val("Quote",q)
f=load("CONTRACTS/FEATURE-TRACE.json")["items"]; assert len(f)==len({x["feature_id"] for x in f})==192
assert all(x["related_operation"] in ids and x["status"]=="NOT_RUN" for x in f)
p=load("CONFIG/PROVIDER-TEMPLATE.json")["bindings"]; assert all(not x["enabled"] and x["actual_binding"] is None and all(v is None for v in x["required_fields"].values()) for x in p)
print("DESIGN_SCHEMA_VALIDATION_PASS",count,"payload samples; runtime NOT_RUN")
