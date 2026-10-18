"""Recovery pools: pro-rata split of money in an account shared by several open disputes.

The arithmetic is exact integer paise; the seeded mule (Rahul K, ACC-100209) receives money from
CASE-24031, CASE-24038 and CASE-24051, whose separate hold suggestions count the same balance.
"""
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.services.recovery import ASSUMPTIONS, RECOVERY_METHOD, allocate

PW = "Investigate@2026"
RAHUL = "ACC-100209"
RAHUL_CASES = {"CASE-24031", "CASE-24038", "CASE-24051"}


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(scope="module")
def client(seeded):
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan  # DB is already initialised and seeded by the fixture
    with TestClient(app) as c:
        yield c


def login(c, user):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------- pure arithmetic

def test_worked_example_from_the_design_doc():
    # Claims ₹50,000 / ₹30,000 / ₹20,000; ₹60,000 available -> ₹30,000 / ₹18,000 / ₹12,000.
    parts = allocate([("A", 5_000_000), ("B", 3_000_000), ("C", 2_000_000)], 6_000_000)
    assert parts == {"A": 3_000_000, "B": 1_800_000, "C": 1_200_000}


def test_capped_at_each_claim_when_more_money_than_claims():
    parts = allocate([("A", 10_000), ("B", 25_000)], 1_000_000)
    assert parts == {"A": 10_000, "B": 25_000}  # never more than claimed; the rest stays unallocated


def test_largest_remainder_rounding_sums_exactly():
    parts = allocate([("A", 500), ("B", 500), ("C", 500)], 100)  # 33.33 paise each
    assert sum(parts.values()) == 100 and sorted(parts.values()) == [33, 33, 34]
    parts = allocate([("A", 1_500_000), ("B", 2_200_000), ("C", 5_000_000)], 120_001)
    assert sum(parts.values()) == 120_001
    assert all(v <= e for v, e in zip(parts.values(), (1_500_000, 2_200_000, 5_000_000)))
    # exact quotas 20689.83 / 30345.08 / 68966.09: the one spare paisa goes to the largest remainder
    assert parts == {"A": 20_690, "B": 30_345, "C": 68_966}


def test_zero_and_empty_cases():
    assert allocate([("A", 100), ("B", 0)], 0) == {"A": 0, "B": 0}
    assert allocate([("A", 0), ("B", 0)], 500) == {"A": 0, "B": 0}
    assert allocate([], 500) == {}


@pytest.mark.parametrize("available", [1, 7, 99, 12_345, 99_999, 1_000_003])
def test_allocations_always_sum_to_min_of_available_and_claims(available):
    claims = [("A", 33_333), ("B", 7), ("C", 50_001), ("D", 16_659)]
    parts = allocate(claims, available)
    assert sum(parts.values()) == min(available, sum(e for _, e in claims))
    assert all(0 <= parts[k] <= e for k, e in claims)


# ---------------------------------------------------------------------------- seeded pools through the API

def test_seeded_rahul_pool_exists_with_linked_cases(client):
    login(client, "sup.meera")
    r = client.get("/api/recovery/pools")
    assert r.status_code == 200, r.text
    pools = {p["account_id"]: p for p in r.json()["pools"]}
    assert RAHUL in pools
    p = pools[RAHUL]
    ids = {c["case_id"] for c in p["claims"]}
    assert len(ids) >= 2 and ids <= RAHUL_CASES
    assert p["method"] == RECOVERY_METHOD and p["basis"] == "traced" and p["is_estimate"] is True
    assert p["formula"].startswith("allocation = (eligible claim / total eligible claims) x money available")
    assert p["assumptions"] == ASSUMPTIONS
    assert p["available_source"]["case_id"] in ids  # one stated figure, not a sum of suggestions
    assert RAHUL in p["input_ids"] and all(c in p["input_ids"] for c in ids)
    for c in p["claims"]:
        assert c["eligible_minor"] == min(c["traced_max_minor"], c["disputed_amount_minor"])
        assert c["traced_min_minor"] <= c["traced_max_minor"]
        assert 0 <= c["allocated_minor"] <= c["eligible_minor"]
    total = sum(c["allocated_minor"] for c in p["claims"])
    assert total == p["distributable_minor"] == min(p["available_minor"], p["total_eligible_minor"])


def test_double_counting_warning_on_shared_account(client):
    login(client, "sup.meera")
    p = client.get(f"/api/recovery/pools/{RAHUL}").json()
    dc = p["double_counting"]
    assert dc["hold_total_minor"] == sum(c["hold_suggested_minor"] for c in p["claims"])
    assert dc["available_minor"] == p["available_minor"]
    assert dc["exceeds"] is True and dc["excess_minor"] == dc["hold_total_minor"] - p["available_minor"]
    assert "same money" in dc["warning"] and dc["warning"] in p["warnings"]


def test_basis_switch_uses_full_disputed_amounts(client):
    login(client, "sup.meera")
    traced = client.get(f"/api/recovery/pools/{RAHUL}?basis=traced").json()
    disputed = client.get(f"/api/recovery/pools/{RAHUL}?basis=disputed").json()
    assert disputed["basis"] == "disputed" and disputed["available_minor"] == traced["available_minor"]
    for c in disputed["claims"]:
        assert c["eligible_minor"] == c["disputed_amount_minor"]
    assert sum(c["allocated_minor"] for c in disputed["claims"]) == min(disputed["available_minor"], disputed["total_eligible_minor"])
    # recomputing the split by hand from the response gives the same answer
    expect = allocate([(c["case_id"], c["eligible_minor"]) for c in disputed["claims"]], disputed["available_minor"])
    assert {c["case_id"]: c["allocated_minor"] for c in disputed["claims"]} == expect
    assert client.get(f"/api/recovery/pools/{RAHUL}?basis=bogus").status_code == 422


def test_unknown_or_unshared_account_is_404(client):
    login(client, "sup.meera")
    assert client.get("/api/recovery/pools/ACC-NOPE").status_code == 404
    assert client.post("/api/recovery/pools/ACC-NOPE/record", json={"basis": "traced", "note": "a long enough note"}).status_code == 404


def test_investigator_sees_restricted_case_ids(client):
    login(client, "inv.asha")  # owns CASE-24051; CASE-24031 belongs to inv.ravi
    pools = client.get("/api/recovery/pools").json()["pools"]
    p = next(p for p in pools if p["account_id"] == RAHUL)
    ids = [c["case_id"] for c in p["claims"]]
    assert "CASE-24031" not in ids and "restricted" in ids
    assert "CASE-24051" in ids
    assert "CASE-24031" not in p["input_ids"]
    restricted = next(c for c in p["claims"] if c["case_id"] == "restricted")
    assert restricted["restricted"] is True and restricted["disputed_txn_id"] is None and restricted["allocated_minor"] is not None
    detail = client.get(f"/api/recovery/pools/{RAHUL}").json()
    assert "CASE-24031" not in str(detail)
    login(client, "inv.ravi")
    ids = [c["case_id"] for c in client.get(f"/api/recovery/pools/{RAHUL}").json()["claims"]]
    assert "CASE-24031" in ids and "CASE-24051" not in ids


def test_only_supervisor_or_admin_can_record_and_a_note_is_required(client):
    body = {"basis": "traced", "note": "Split agreed at the fraud review meeting"}
    login(client, "inv.asha")
    assert client.post(f"/api/recovery/pools/{RAHUL}/record", json=body).status_code == 403
    login(client, "sup.meera")
    r = client.post(f"/api/recovery/pools/{RAHUL}/record", json={"basis": "traced", "note": "too short"})
    assert r.status_code == 422
    r = client.post(f"/api/recovery/pools/{RAHUL}/record", json={"basis": "traced", "note": "          x          "})
    assert r.status_code == 422  # whitespace does not count
    assert client.post(f"/api/recovery/pools/{RAHUL}/record", json={"basis": "nope", "note": body["note"]}).status_code == 422


def test_recording_is_audited_globally_and_per_case_and_moves_no_money(client, db):
    from app import audit
    from app import models as m

    login(client, "sup.meera")
    holds_before = [(h.id, h.status, h.amount_minor) for h in db.scalars(select(m.Hold).order_by(m.Hold.id)).all()]
    r = client.post(f"/api/recovery/pools/{RAHUL}/record", json={"basis": "disputed", "note": "Pro-rata split noted for the review file"})
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert rec["basis"] == "disputed" and rec["method"] == RECOVERY_METHOD and rec["recorded_by"] == "sup.meera"
    assert "No money was moved" in rec["effect"]
    assert sum(a["allocated_minor"] for a in rec["allocations"]) == min(rec["available_minor"],
                                                                       sum(a["eligible_minor"] for a in rec["allocations"]))
    case_ids = {a["case_id"] for a in rec["allocations"]}
    assert case_ids <= RAHUL_CASES and len(case_ids) >= 2

    db.expire_all()
    glob = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id.is_(None), m.AuditEvent.action == "recovery_allocation_recorded")
                      .order_by(m.AuditEvent.id.desc())).first()
    assert glob is not None and glob.details["recovery_allocation_id"] == rec["id"] and glob.details["money_moved"] is False
    for cid in case_ids:
        ev = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == cid, m.AuditEvent.action == "recovery_allocation_recorded")
                        .order_by(m.AuditEvent.id.desc())).first()
        assert ev is not None and ev.details["recovery_allocation_id"] == rec["id"]
        assert audit.verify(db, cid)["valid"]
    stored = db.get(m.RecoveryAllocation, rec["id"])
    assert stored.note == "Pro-rata split noted for the review file" and stored.allocations == rec["allocations"]
    # recording changes no hold
    assert [(h.id, h.status, h.amount_minor) for h in db.scalars(select(m.Hold).order_by(m.Hold.id)).all()] == holds_before

    hist = client.get(f"/api/recovery/pools/{RAHUL}/history").json()
    assert hist["records"][0]["id"] == rec["id"]
    assert client.get(f"/api/recovery/pools/{RAHUL}").json()["last_recorded"]["id"] == rec["id"]
    login(client, "inv.asha")
    hist = client.get(f"/api/recovery/pools/{RAHUL}/history").json()
    assert "CASE-24031" not in str(hist) and any(a["case_id"] == "restricted" for a in hist["records"][0]["allocations"])


def test_case_screen_hint_lists_other_cases_sharing_the_account(client):
    login(client, "sup.meera")
    r = client.get("/api/recovery/cases/CASE-24051/shared")
    assert r.status_code == 200
    rows = {x["account_id"]: x["other_cases"] for x in r.json()["accounts"]}
    assert RAHUL in rows and "CASE-24051" not in rows[RAHUL] and set(rows[RAHUL]) <= RAHUL_CASES
    login(client, "inv.asha")
    rows = {x["account_id"]: x["other_cases"] for x in client.get("/api/recovery/cases/CASE-24051/shared").json()["accounts"]}
    assert "CASE-24031" not in rows.get(RAHUL, [])
    assert client.get("/api/recovery/cases/CASE-24031/shared").status_code == 404  # not her case


def test_auth_required(client):
    client.cookies.clear()
    for path in ("/api/recovery/pools", f"/api/recovery/pools/{RAHUL}", f"/api/recovery/pools/{RAHUL}/history"):
        assert client.get(path).status_code == 401
