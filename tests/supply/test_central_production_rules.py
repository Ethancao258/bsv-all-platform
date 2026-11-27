from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from services.api.supply.central_production_rules import (
    ApprovedRule, PackageFact, expiry, quantity, validate_split, available,
    receipt_intent, expiry_rows, expiry_sheet, arrival_sheet, shift_due, cn_time,
)

T=datetime(2026,11,27,6,30,tzinfo=timezone.utc)
R=ApprovedRule("synthetic-rule-v1",True,86400,3600)
def pack(pid="synthetic-1",amount="450",state="IN_TRANSIT",store="SYNTH-STORE"):
    return PackageFact(pid,"synthetic-batch","synthetic-item","<物料>",store,
        Decimal(amount),Decimal(amount),"mL",T,expiry(R,T),R.version,
        "synthetic-maker","冷藏示例","示例用法",state)

@pytest.mark.parametrize("bad",["NaN","Infinity","-1","0","0.00001",True,0.1])
def test_reject_quantity(bad):
    with pytest.raises(ValueError): quantity(bad,"mL")

def test_expiry_rules():
    assert expiry(R,T)==T+timedelta(days=1)
    assert expiry(R,T,opened_at=T+timedelta(hours=2))==T+timedelta(hours=3)
    assert expiry(R,T,restriction_at=T+timedelta(minutes=5))==T+timedelta(minutes=5)
    with pytest.raises(ValueError): ApprovedRule("x",False,3600)
    with pytest.raises(ValueError): expiry(R,T.replace(tzinfo=None))
    with pytest.raises(ValueError): expiry(ApprovedRule("x",True,3600),T,opened_at=T)
    with pytest.raises(ValueError): expiry(R,T,opened_at=T-timedelta(seconds=1))

def test_split():
    assert validate_split("800","mL",[("a","450"),("b","350")],"0","0")==800
    with pytest.raises(ValueError): validate_split("800","mL",[("a","450"),("a","350")],"0","0")
    with pytest.raises(ValueError): validate_split("800","mL",[("a","450")],"0","0")
    with pytest.raises(ValueError): quantity("1.5","piece")

def test_partial_receipt_and_store():
    p,q=pack(),pack("synthetic-2","350")
    assert receipt_intent([p,q],[p.package_id],[],store_id=p.store_id,now=T)==((p.package_id,"ACCEPTED",Decimal("450"),"mL"),)
    with pytest.raises(ValueError): receipt_intent([p,q],[p.package_id],[p.package_id],store_id=p.store_id,now=T)
    with pytest.raises(ValueError): receipt_intent([p],[p.package_id],[],store_id="OTHER",now=T)
    with pytest.raises(ValueError): receipt_intent([replace(p,state="ACCEPTED")],[p.package_id],[],store_id=p.store_id,now=T)
    with pytest.raises(ValueError): receipt_intent([p],[p.package_id],[],store_id=p.store_id,now=p.expires_at)
    assert receipt_intent([p],[],[p.package_id],store_id=p.store_id,now=p.expires_at)[0][1]=="HOLD"

def test_expiry_and_shift():
    p=pack(state="ACCEPTED")
    old=replace(pack("old","350","ACCEPTED"),produced_at=T-timedelta(days=1),expires_at=T)
    assert available(p,T)
    assert not available(p,p.expires_at)
    assert expiry_rows([p,old],store_id=p.store_id,now=T)[0]==("已过期",old)
    assert shift_due([p,old],store_id=p.store_id,now=T)[0][1]=="old"
    assert cn_time(T)=="2026-11-27 周五 14:30:00"
    with pytest.raises(ValueError): expiry_rows([p],store_id="OTHER",now=T)

def test_printing():
    p=pack(state="ACCEPTED")
    old=replace(pack("old","350","ACCEPTED"),produced_at=T-timedelta(days=1),expires_at=T)
    html=expiry_sheet([p,old],store_id=p.store_id,as_of=T,revision="1")
    assert "old" in html and "已过期" in html and "演示" in html
    assert "&lt;物料&gt;" in html and "<物料>" not in html
    row=dict(package=p,accepted="450",held="0",committed=True,source_store_id="SYNTH-WH",
        sender_id="synthetic-sender",receiver_id="synthetic-receiver",sent_at=T,received_at=T)
    sheet=arrival_sheet([row],store_id=p.store_id,as_of=T,revision="1")
    assert "450 mL" in sheet and "synthetic-receiver" in sheet
    with pytest.raises(ValueError): arrival_sheet([{**row,"committed":False}],store_id=p.store_id,as_of=T,revision="1")
    with pytest.raises(ValueError): arrival_sheet([row,row],store_id=p.store_id,as_of=T,revision="1")
    with pytest.raises(ValueError): arrival_sheet([{**row,"accepted":"451"}],store_id=p.store_id,as_of=T,revision="1")

def test_label_and_reconciliation():
    from services.api.supply.central_production_rules import label_preview, shipment_reconciliation
    p=pack(state="READY"); q=pack("synthetic-2","350")
    label=label_preview(p,as_of=T)
    assert "50mm 40mm" in label and "死期" in label and "非正式标签" in label
    with pytest.raises(ValueError): label_preview(p,as_of=p.expires_at)
    with pytest.raises(ValueError): receipt_intent([q],[q.package_id],[],store_id=q.store_id,now=T-timedelta(seconds=1))
    row=dict(package=replace(p,state="ACCEPTED"),accepted="450",held="0",committed=True,
        source_store_id="SYNTH-WH",sender_id="synthetic-sender",receiver_id="synthetic-receiver",
        sent_at=T,received_at=T)
    result=shipment_reconciliation([p,q],[row],store_id=p.store_id,as_of=T,revision="1")
    assert "计划800 / 合格450 / 隔离0 / 未确认350" in result
    with pytest.raises(ValueError): shipment_reconciliation([q],[row],store_id=p.store_id,as_of=T,revision="1")
