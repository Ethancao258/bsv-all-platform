"""Synthetic one-use POS proof: forged, stale, cross-store, and duplicate protection."""
from __future__ import annotations
import hashlib
import sqlite3
import time
from uuid import uuid4

import pytest

from services.api.bsv1 import bsv_growth_pos as p


KEY = "ISOLATED-GUEST-LINK-KEY-01234567890123456789"
CONTEXT = "ISOLATED-POS-CONTEXT-KEY-01234567890123456789"


def test_guest_proof_scope_signature_and_times():
    cid = str(uuid4())
    issued = p.make_guest_link(cid, "BSVT", KEY, current=1000)
    assert p.verify_guest_link(issued, "BSVT", KEY, current=1001)["customer_id"] == cid
    with pytest.raises(p.ProofError):
        p.verify_guest_link(issued, "BSVS", KEY, current=1001)
    with pytest.raises(p.ProofError):
        p.verify_guest_link(issued, "BSVT", KEY, current=1120)
    with pytest.raises(p.ProofError):
        p.verify_guest_link(issued[:-1] + ("f" if issued[-1] != "f" else "e"), "BSVT", KEY, current=1001)
    with pytest.raises(p.ProofError):
        p.verify_guest_link(issued, "BSVT", "OTHER-KEY-012345678901234567890000", current=1001)
    with pytest.raises(p.ProofError):
        p.make_guest_link("arbitrary-staff-member", "BSVT", KEY)
    with pytest.raises(p.ProofError):
        p.verify_guest_link("not-a-valid-proof", "BSVT", KEY)


def test_visit_context_and_distinct_keys():
    cid = str(uuid4())
    token = p.make_visit_context(cid, "BSVT", "BSVT-VISIT-001", CONTEXT, current=2000)
    packed, sig = token.split(".")
    assert len(sig) == 64
    import base64, json
    payload = json.loads(base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4)))
    assert payload == {"customer_id": cid, "store_id": "BSVT", "visit_id": "BSVT-VISIT-001",
                       "iat": 2000, "exp": 2090}
    with pytest.raises(p.ProofError):
        p.verify_guest_link(token, "BSVT", KEY, current=2001)


def test_pos_projection_is_additive_and_nonce_ledger_rejects_replay():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE stores(id TEXT PRIMARY KEY);
    CREATE TABLE visits(id TEXT PRIMARY KEY);
    CREATE TABLE visit_member_links(
      visit_id TEXT, person_slot INTEGER, member_reference TEXT,
      member_id TEXT, PRIMARY KEY(visit_id, person_slot));
    INSERT INTO stores(id) VALUES('BSVT');
    INSERT INTO visits(id) VALUES('VISIT1');
    """)
    p.install_pos_projection(db)
    p.install_pos_projection(db)
    assert "canonical_customer_id" in {x["name"] for x in db.execute("PRAGMA table_info(visit_member_links)")}
    nonce = p.nonce_digest("stage-pos-nonce-001-abcdefghijkl")
    assert len(nonce) == 64
    db.execute("""INSERT INTO bsv_growth_pos_consumed_nonces
                  (nonce_hash,visit_id,store_id,customer_id,created_at)
                  VALUES(?,?,?,?,?)""", (nonce, "VISIT1", "BSVT", str(uuid4()), "synthetic"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO bsv_growth_pos_consumed_nonces
                      (nonce_hash,visit_id,store_id,customer_id,created_at)
                      VALUES(?,?,?,?,?)""", (nonce, "VISIT1", "BSVT", str(uuid4()), "synthetic"))
