"""Security and ingest: field encryption, MFA, DLP, ledger ingest (bank formats + Pub/Sub), evidence strength scores."""
import base64
import io
import json
import os
import time
from contextlib import asynccontextmanager

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import crypto
from app import models as m
from app.config import get_settings
from app.services import dlp, mfa
from app.services.evidence_scoring import score
from app.services.ledger_sources import FormatError, camt053_records

PW = "Investigate@2026"


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(scope="module")
def client(seeded):
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as c:
        yield c


def _session():
    from app.db import session_factory

    return session_factory()()


def _make_user(username: str, role: str) -> int:
    from app.security import hash_password

    with _session() as s:
        u = s.scalar(select(m.User).where(m.User.username == username))
        if u is None:
            u = m.User(username=username, full_name=username, role=role, password_hash=hash_password(PW))
            s.add(u)
        mfa.reset(u)
        s.commit()
        return u.id


def login(c, user):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------- field-level encryption

def test_sensitive_columns_are_encrypted_at_rest_and_transparent_in_code(db):
    raw = db.execute(text("SELECT allegation FROM dispute_cases LIMIT 1")).scalar()
    assert raw.startswith("enc:v1:")
    case = db.scalars(select(m.DisputeCase)).first()
    assert not case.allegation.startswith("enc:") and len(case.allegation) > 10
    for table, col in (("customers", "display_name"), ("accounts", "holder_label")):
        assert db.execute(text(f"SELECT {col} FROM {table} LIMIT 1")).scalar().startswith("enc:v1:")
    fields = crypto.status()["fields"]
    assert {"dispute_cases.allegation", "case_notes.body", "users.mfa_secret", "evidence_items.extracted"} <= set(fields)


def test_ciphertext_is_bound_to_its_column():
    c = crypto.encrypt("Rahul K", "customers.display_name")
    assert crypto.decrypt(c, "customers.display_name") == "Rahul K"
    with pytest.raises(InvalidTag):
        crypto.decrypt(c, "accounts.holder_label")  # copied into another column: does not decrypt


def test_legacy_plaintext_is_readable_and_backfilled(db):
    case = db.scalars(select(m.DisputeCase)).first()
    note = m.CaseNote(case_id=case.id, author_id=1, body="placeholder")
    db.add(note)
    db.flush()
    db.execute(text("UPDATE case_notes SET body = 'written before encryption' WHERE id = :i"), {"i": note.id})
    db.expire_all()
    assert db.get(m.CaseNote, note.id).body == "written before encryption"
    assert crypto.backfill(db) >= 1
    assert db.execute(text("SELECT body FROM case_notes WHERE id = :i"), {"i": note.id}).scalar().startswith("enc:v1:")
    db.expire_all()
    assert db.get(m.CaseNote, note.id).body == "written before encryption"
    db.rollback()


@pytest.fixture()
def restore_keyring():
    yield
    crypto.reset_keyring()


def test_key_rotation_and_cloud_requirement(monkeypatch, restore_keyring):
    s = get_settings()
    k1, k2 = base64.b64encode(os.urandom(32)).decode(), base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(s, "field_encryption_keys", f"k1:{k1}")
    crypto.reset_keyring()
    old = crypto.encrypt("secret", "t.c")
    monkeypatch.setattr(s, "field_encryption_keys", f"k2:{k2},k1:{k1}")
    crypto.reset_keyring()
    assert crypto.decrypt(old, "t.c") == "secret"  # old key still decrypts
    assert crypto.encrypt("x", "t.c").startswith("enc:v1:k2:")  # new key encrypts
    monkeypatch.setattr(s, "field_encryption_keys", f"k2:{k2}")
    crypto.reset_keyring()
    with pytest.raises(crypto.EncryptionConfigError):
        crypto.decrypt(old, "t.c")
    monkeypatch.setattr(s, "field_encryption_keys", None)
    monkeypatch.setattr(s, "environment", "cloud")
    crypto.reset_keyring()
    with pytest.raises(crypto.EncryptionConfigError):  # no development key in the cloud
        crypto.keyring()


# ---------------------------------------------------------------------------- MFA

def test_totp_matches_rfc6238_vectors():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert mfa.totp(secret, 59) == "287082"
    assert mfa.totp(secret, 1111111109) == "081804"
    assert mfa.match_step(secret, "287 082", at=59 + 30) == 1  # one step of clock drift is accepted
    assert mfa.match_step(secret, "287082", at=59 + 90) is None


def test_mfa_enrol_sign_in_replay_recovery_and_disable(client):
    uid = _make_user("mfa.tester", "investigator")
    assert "user" in login(client, "mfa.tester")
    setup = client.post("/api/auth/mfa/setup", json={}).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/") and setup["qr_svg"].startswith("data:image/svg+xml")
    r = client.post("/api/auth/mfa/enable", json={"code": "000000"})
    assert r.status_code == 422
    r = client.post("/api/auth/mfa/enable", json={"code": mfa.totp(setup["secret"])})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    codes = r.json()["recovery_codes"]
    assert client.get("/api/auth/me").json()["user"]["mfa_enabled"] is True  # the session was re-issued with MFA

    first = login(client, "mfa.tester")
    assert first["mfa_required"] and "user" not in first and not client.cookies.get("ft_session")
    pending = first["mfa_token"]
    assert client.get("/api/cases", headers={"Authorization": f"Bearer {pending}"}).status_code == 401  # never a session
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": pending, "code": "000000"}).status_code == 401
    code = mfa.totp(setup["secret"], time.time() + 30)
    ok = client.post("/api/auth/mfa/verify", json={"mfa_token": pending, "code": code})
    assert ok.status_code == 200 and client.get("/api/cases").status_code == 200

    again = login(client, "mfa.tester")["mfa_token"]
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": again, "code": code}).status_code == 401  # replay refused
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": again, "code": codes[0]})
    assert r.status_code == 200 and r.json()["recovery_codes_left"] == 9
    again = login(client, "mfa.tester")["mfa_token"]
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": again, "code": codes[0]}).status_code == 401  # single use

    from app.security import create_token

    with _session() as s:
        stale = create_token(s.get(m.User, uid), mfa_done=False)
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {stale}"}).status_code == 401

    r = client.post("/api/auth/mfa/verify", json={"mfa_token": login(client, "mfa.tester")["mfa_token"], "code": codes[1]})
    assert r.status_code == 200
    assert client.post("/api/auth/mfa/disable", json={"password": "wrong", "code": codes[2]}).status_code == 401
    r = client.post("/api/auth/mfa/disable", json={"password": PW, "code": codes[3]})
    assert r.status_code == 200 and r.json()["user"]["mfa_enabled"] is False
    assert "user" in login(client, "mfa.tester")


def test_mfa_required_role_must_enrol_at_sign_in(client, monkeypatch):
    _make_user("mfa.sup", "supervisor")
    monkeypatch.setattr(get_settings(), "mfa_required_roles", "supervisor")
    first = login(client, "mfa.sup")
    assert first["mfa_enrollment_required"] and not client.cookies.get("ft_session")
    setup = client.post("/api/auth/mfa/setup", json={"mfa_token": first["mfa_token"]}).json()
    r = client.post("/api/auth/mfa/enable", json={"code": mfa.totp(setup["secret"]), "mfa_token": first["mfa_token"]})
    assert r.status_code == 200 and r.json()["user"]["mfa_required"] is True
    assert client.get("/api/cases").status_code == 200
    r = client.post("/api/auth/mfa/disable", json={"password": PW, "code": r.json()["recovery_codes"][0]})
    assert r.status_code == 403  # cannot opt out of a required factor
    assert client.get("/api/auth/config").json()["mfa_required_roles"] == ["supervisor"]


def test_admin_mfa_reset_is_admin_only_and_audited(client):
    uid = _make_user("mfa.lost", "investigator")
    with _session() as s:
        u = s.get(m.User, uid)
        u.mfa_secret, u.mfa_enabled = mfa.new_secret(), True
        s.commit()
    login(client, "inv.asha")
    assert client.post(f"/api/admin/users/{uid}/mfa/reset", json={"reason": "lost phone, identity checked"}).status_code == 403
    login(client, "admin")
    users = {u["username"]: u for u in client.get("/api/admin/users").json()["users"]}
    assert users["mfa.lost"]["mfa_enabled"] is True
    assert client.post(f"/api/admin/users/{uid}/mfa/reset", json={"reason": "short"}).status_code == 422
    assert client.post(f"/api/admin/users/{uid}/mfa/reset", json={"reason": "lost phone, identity checked"}).status_code == 200
    me = client.get("/api/auth/me").json()["user"]["id"]
    assert client.post(f"/api/admin/users/{me}/mfa/reset", json={"reason": "resetting my own factor"}).status_code == 403
    with _session() as s:
        assert s.get(m.User, uid).mfa_enabled is False
        ev = s.scalars(select(m.AuditEvent).where(m.AuditEvent.action == "mfa_reset_by_admin")).all()
        assert ev and ev[-1].details["user"] == "mfa.lost"
    sec = client.get("/api/admin/security").json()
    assert sec["encryption"]["algorithm"] == "AES-256-GCM" and sec["dlp"]["backend"] == "local"


# ---------------------------------------------------------------------------- DLP

def test_dlp_detectors_use_checksums_and_spare_payment_references():
    masked, found = dlp.mask("Card 4111 1111 1111 1111, OTP is 482913, UTR 412345678901, OTP request for ₹50,000, Aadhaar 2345 6789 0124")
    assert "4111" not in masked and "482913" not in masked and "2345 6789" not in masked
    assert "412345678901" in masked and "₹50,000" in masked and "OTP request" in masked
    assert {f["type"] for f in found} == {"CREDIT_CARD_NUMBER", "SECRET_CODE", "INDIA_AADHAAR_INDIVIDUAL"}
    assert dlp.scan_text("card 4111 1111 1111 1112")["findings"] == []  # fails the Luhn check
    kinds = {f["type"] for f in dlp.scan_text("mail a.b@example.com, upi rahul@okaxis, PAN ABCPE1234F, call +91 98765 43210")["findings"]}
    assert kinds == {"EMAIL_ADDRESS", "UPI_ID", "INDIA_PAN_INDIVIDUAL", "PHONE_NUMBER"}


def test_notes_are_masked_before_storage_and_uploads_are_scanned(client):
    login(client, "sup.meera")
    r = client.post("/api/cases/CASE-24051/actions", json={"type": "note", "body": "Customer read out card 4111111111111111 and OTP 482913"})
    assert r.status_code == 200 and {f["type"] for f in r.json()["masked"]} == {"CREDIT_CARD_NUMBER", "SECRET_CODE"}
    note = [n for n in client.get("/api/cases/CASE-24051").json()["notes"] if n["id"] == r.json()["note_id"]][0]
    assert "4111111111111111" not in note["body"] and "[REDACTED: Card number]" in note["body"]
    f = io.BytesIO("My Aadhaar number 2345 6789 0124 and email me at a.b@example.com".encode())
    up = client.post("/api/cases/CASE-24051/evidence", files={"file": ("id.txt", f, "text/plain")})
    assert up.status_code == 200
    assert {x["type"] for x in up.json()["dlp"]["findings"]} == {"INDIA_AADHAAR_INDIVIDUAL", "EMAIL_ADDRESS"}
    ev = [e for e in client.get("/api/cases/CASE-24051/evidence").json()["evidence"] if e["id"] == up.json()["id"]][0]
    assert ev["dlp"]["status"] == "scanned"


def test_customer_text_is_masked_before_it_reaches_the_llm(db):
    from app.ai.snapshot import build_snapshot
    from app.services.investigation import build_context

    case = db.get(m.DisputeCase, "CASE-24051")
    case.allegation = "I never shared the OTP 482913 but my card 4111 1111 1111 1111 was charged ₹50,000"
    snap = build_snapshot(build_context(db, case))
    statement = snap["records"][case.id]["customer_statement"]
    assert "482913" not in statement and "4111" not in statement and "₹50,000" in statement
    db.rollback()


# ---------------------------------------------------------------------------- ledger ingest

CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
 <BkToCstmrStmt>
  <GrpHdr><MsgId>STMT-1</MsgId><CreDtTm>2020-03-02T09:00:00+05:30</CreDtTm></GrpHdr>
  <Stmt>
   <Id>S-2020-03-01</Id>
   <Acct><Id><Othr><Id>{own}</Id></Othr></Id><Ccy>INR</Ccy></Acct>
   <Ntry>
    <Amt Ccy="INR">12500.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
    <BookgDt><DtTm>2020-03-01T10:15:00+05:30</DtTm></BookgDt><AcctSvcrRef>CAMT-0001</AcctSvcrRef>
    <BkTxCd><Prtry><Cd>IMPS</Cd></Prtry></BkTxCd>
    <NtryDtls><TxDtls><Refs><ClrSysRef>006011223344</ClrSysRef></Refs>
     <RltdPties><Cdtr><Nm>Beneficiary One</Nm></Cdtr><CdtrAcct><Id><Othr><Id>50100123456789</Id></Othr></Id></CdtrAcct></RltdPties>
     <RmtInf><Ustrd>rent march</Ustrd></RmtInf></TxDtls></NtryDtls>
   </Ntry>
   <Ntry>
    <Amt Ccy="INR">800</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>PDNG</Cd></Sts>
    <BookgDt><Dt>2020-03-01</Dt></BookgDt><NtryRef>N-2</NtryRef>
    <NtryDtls><TxDtls><Refs><EndToEndId>E2E-77</EndToEndId></Refs>
     <RltdPties><Dbtr><Nm>Payer Two</Nm></Dbtr><DbtrAcct><Id><IBAN>GB33BUKB20201555555555</IBAN></Id></DbtrAcct></RltdPties></TxDtls></NtryDtls>
   </Ntry>
  </Stmt>
 </BkToCstmrStmt>
</Document>"""


def _own_account(db) -> str:
    return db.scalars(select(m.Account.id).where(m.Account.institution_id == "INST-SELF")).first()


def test_camt053_adapter_maps_iso20022_entries(db):
    own = _own_account(db)
    recs = camt053_records(CAMT.format(own=own).encode())
    assert len(recs) == 2
    out, inn = recs
    assert out["debit_account_id"] == own and out["credit_account_id"] == "50100123456789" and out["credit_account_name"] == "Beneficiary One"
    assert out["amount"] == "12500.00" and out["status"] == "posted" and out["channel"] == "IMPS" and out["reference"] == "006011223344"
    assert out["source_record_id"] == "CAMT-0001" and out["narrative"] == "rent march"
    assert inn["credit_account_id"] == own and inn["debit_account_id"] == "GB33BUKB20201555555555" and inn["status"] == "pending"
    assert inn["reference"] == "E2E-77" and inn["occurred_at"] == "2020-03-01T00:00:00"
    with pytest.raises(FormatError):
        camt053_records(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Document/>')


def test_statement_upload_is_admin_only_idempotent_and_hides_account_numbers(client, db):
    data = CAMT.format(own=_own_account(db)).encode()
    login(client, "sup.meera")
    files = {"file": ("stmt.xml", io.BytesIO(data), "application/xml")}
    assert client.post("/api/ingest/file", files=files, data={"format": "iso20022.camt.053"}).status_code == 403
    login(client, "admin")
    r = client.post("/api/ingest/file", files={"file": ("stmt.xml", io.BytesIO(data), "application/xml")},
                    data={"format": "iso20022.camt.053", "source_system": "core"})
    assert r.status_code == 200, r.text
    ev = r.json()["event"]
    assert ev["status"] == "processed" and ev["created"] == 2 and ev["placeholder_accounts"] == 2 and not r.json()["already_processed"]
    again = client.post("/api/ingest/file", files={"file": ("stmt.xml", io.BytesIO(data), "application/xml")},
                        data={"format": "iso20022.camt.053", "source_system": "core"})
    assert again.json()["already_processed"] and again.json()["event"]["id"] == ev["id"]
    with _session() as s:
        t = s.scalar(select(m.Transaction).where(m.Transaction.source_record_id == "CAMT-0001"))
        acct = s.get(m.Account, t.credit_account_id)
        assert acct.id.startswith("EXT-") and acct.masked_number == "XXXX6789" and acct.institution.kind == "external"
        assert t.amount_minor == 1250000 and t.is_synthetic is False
    assert client.get("/api/ingest/events").json()["events"][0]["id"] == ev["id"]


def test_csv_with_a_bad_row_is_partial_not_blocking(client):
    login(client, "admin")
    rows = ("source_record_id,debit_account_id,credit_account_id,amount,currency,status,channel,reference,occurred_at\n"
            "CSV-1,ACCT-CSV-A,ACCT-CSV-B,100.50,INR,posted,UPI,CSVREF1,2020-04-01T10:00:00Z\n"
            "CSV-2,ACCT-CSV-A,ACCT-CSV-B,100.50,XXX,posted,UPI,CSVREF2,2020-04-01T10:05:00Z\n"
            f"CSV-3,ACCT-CSV-A,ACCT-CSV-B,9.00,INR,posted,UPI,{'R' * 65},2020-04-01T10:06:00Z\n")
    r = client.post("/api/ingest/file", files={"file": ("x.csv", io.BytesIO(rows.encode()), "text/csv")}, data={"format": "csv"})
    ev = r.json()["event"]
    assert ev["status"] == "partial" and ev["created"] == 1 and len(ev["rejected"]) == 2
    reasons = " ".join(x["reason"] for x in ev["rejected"])
    assert "currency" in reasons and "longer than 64" in reasons
    bad = client.post("/api/ingest/file", files={"file": ("x.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}, data={"format": "csv"})
    assert bad.status_code == 422


def _push(client, records, message_id, source="core"):
    body = {"message": {"data": base64.b64encode(json.dumps(records).encode()).decode(), "messageId": message_id,
                        "attributes": {"format": "fundtrace.v1", "source_system": source}}, "subscription": "projects/p/subscriptions/s"}
    return client.post("/api/ingest/pubsub", json=body)


def test_pubsub_push_auth_merge_redelivery_and_poison_messages(client, monkeypatch):
    from app.api.ingest import verify_pubsub_push

    assert _push(client, [], "m-0").status_code == 404  # disabled until an audience is configured
    monkeypatch.setattr(get_settings(), "pubsub_push_audience", "https://fundtrace.example/api/ingest/pubsub")
    assert _push(client, [], "m-0").status_code == 401  # no Google-signed token
    pusher = "fundtrace-v2-ledger-push@fundtrace-hack-2026.iam.gserviceaccount.com"  # longer than an audit actor (64)
    client.app.dependency_overrides[verify_pubsub_push] = lambda: pusher
    try:
        rec = {"source_record_id": "CORE-9001", "debit_account_id": "ACCT-PS-A", "credit_account_id": "ACCT-PS-B", "amount": "2500",
               "currency": "INR", "status": "posted", "channel": "UPI", "reference": "PSREF9001", "occurred_at": "2020-05-01T08:00:00Z"}
        assert _push(client, [rec], "m-1").status_code == 204
        switch = {**rec, "source_record_id": "UPI-777", "amount": "2550", "occurred_at": "2020-05-01T08:01:00Z"}
        assert _push(client, [switch], "m-2", source="upi_switch").status_code == 204
        assert _push(client, [switch], "m-2", source="upi_switch").status_code == 204  # redelivery: acknowledged, not re-applied
        resp = client.post("/api/ingest/pubsub", json={"message": {"data": "!!not base64!!", "messageId": "m-3"}})
        assert resp.status_code == 204  # poison message is acknowledged and recorded, not retried forever
        with _session() as s:
            t = s.scalar(select(m.Transaction).where(m.Transaction.reference == "PSREF9001"))
            assert [x["system"] for x in t.sources] == ["core", "upi_switch"]
            assert t.sources[0]["discrepancies"][0]["fields"]["amount_minor"] == {"primary": 250000, "other": 255000}
            evs = {e.message_id: e for e in s.scalars(select(m.IngestEvent).where(m.IngestEvent.channel == "pubsub")).all()}
            assert evs["pubsub:m-2"].merged == 1 and evs["pubsub:m-3"].status == "rejected" and len(evs) == 3
            assert evs["pubsub:m-1"].received_by == pusher
            actors = s.scalars(select(m.AuditEvent.actor).where(m.AuditEvent.action == "ledger_ingested")).all()
            assert actors and all(len(a) <= m.AuditEvent.__table__.c.actor.type.length for a in actors)  # MySQL enforces this
    finally:
        client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------- evidence strength

def test_evidence_score_excludes_unassessed_categories_and_explains_each():
    item = {"analysis_status": "analysed", "reconciliation": {"checks": [], "contradictions": 0},
            "extracted": {"is_payment_record": False, "amount": None, "reference": None, "date_text": "1 Oct 2026", "time_text": None,
                          "payee": None, "payer": None, "app_or_bank": "WhatsApp", "tamper_indicators": [],
                          "embedded_instructions_detected": False, "legibility": "partial", "relevance": "related",
                          "relevance_reason": "chat about the job offer", "origin": "customer_authored"}}
    sc = score(item)
    cats = {c["key"]: c for c in sc["categories"]}
    assert cats["ledger_match"]["score"] is None and cats["relevance"]["score"] == 60 and cats["provenance"]["score"] == 50
    assert cats["legibility"]["score"] == 60 and cats["completeness"]["score"] == 29 and cats["integrity"]["score"] == 100
    # weighted over the assessed categories only: (100*25 + 60*15 + 50*10 + 29*10 + 60*10) / 70
    assert sc["overall"] == round((2500 + 900 + 500 + 290 + 600) / 70) and sc["band"] == "moderate"
    assert all(c["reasons"] for c in sc["categories"])
    assert score({**item, "analysis_status": "not_analysed"}) is None
    legacy = {**item, "extracted": {k: v for k, v in item["extracted"].items() if k not in ("relevance", "origin")}}
    assert {c["key"]: c["score"] for c in score(legacy)["categories"]}["relevance"] is None  # read before v3: not assessed
