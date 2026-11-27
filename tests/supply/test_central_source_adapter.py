from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import pytest
from services.api.supply.central_source_adapter import CatalogPolicyAdapter, organization_from_env

def write_pinned(path,value):
    raw=json.dumps(value).encode();path.write_bytes(raw)
    return sha256(raw).hexdigest()

def test_approved_catalog_projection_uses_real_ids_and_revision(tmp_path):
    revision="a"*64
    class Repo:
        sha=revision
        def get_product(self,item):
            return dict(product_id=item,name="Synthetic",source_sha256=self.sha,production_standard_approved=True)
    repo=Repo()
    item=dict(item_id="P000001",approved=True,approval_reference="synthetic-policy-ref",duration_basis="PRODUCED_AT",
              rule_version="E1",elapsed_seconds=3600,opened_seconds=600,unit="mL",yield_amount="800",standard_amount="450",
              recipe_version="R1",sop_version="S1",storage="synthetic",usage="synthetic",
              recipe_inputs=[dict(material_id="M000001",unit="mL",amount="800")])
    path=tmp_path/"policy.json"
    digest=write_pinned(path,dict(schema_version=1,catalog_source_sha256=revision,approval_reference="fixture",policies=[item]))
    adapter=CatalogPolicyAdapter(repo,path,digest)
    assert adapter.production_policy("P000001","R1")["recipe_inputs"][0]["amount"]=="800"
    assert adapter.items()[0]["item_id"]=="P000001"
    repo.sha="b"*64
    with pytest.raises(ValueError,match="stale"):adapter.production_policy("P000001")
    assert adapter.items()==[]
    path.write_text("{}")
    with pytest.raises(ValueError,match="digest"):adapter.items()

def test_org_projection_rejects_fixture_and_expired_scope(tmp_path,monkeypatch):
    now=datetime(2026,11,27,12,tzinfo=timezone.utc)
    path=tmp_path/"org.json"
    value=dict(schema_version=1,approval_reference="fixture-for-test-only",as_of=now.isoformat(),
               valid_until=(now+timedelta(hours=24)).isoformat(),legal_entity_id="EXAMPLE-LEGAL",
               stores=[dict(store_id="WH01",name_zh="Example",kind="warehouse",approved=True,legal_entity_id="EXAMPLE-LEGAL")],
               department_by_tr={"TRA0001":"DEPT01"})
    monkeypatch.setenv("BSV_SUP59_ORG_PROJECTION_FILE",str(path))
    monkeypatch.setenv("BSV_SUP59_ORG_PROJECTION_SHA256",write_pinned(path,value))
    assert organization_from_env(now=now)["stores"][0]["store_id"]=="WH01"
    with pytest.raises(ValueError,match="stale"):organization_from_env(now=now+timedelta(hours=25))
    value["legal_entity_id"]="DEMO_LEGAL"
    monkeypatch.setenv("BSV_SUP59_ORG_PROJECTION_SHA256",write_pinned(path,value))
    with pytest.raises(ValueError,match="fixture"):organization_from_env(now=now)
