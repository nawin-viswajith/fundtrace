"""Forensic calculation record: reproducible inputs, unchanged outputs, and checks on the arithmetic."""
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.services import calc_record as cr
from app.services.attribution import METHODS, attribute
from app.services.trace import TraceParams, trace

from tests.builders import acct, rupees, s1_store, store, txn

PW = "Investigate@2026"


def record(st, root="TXN-1", **kw):
    return cr.build_record(st, root, TraceParams(**kw), case_id="CASE-T")


def check(rec, cid):
    return next(c for c in rec["checks"] if c["id"] == cid)


# ---------------------------------------------------------------------------- unit (in-memory ledgers)

def test_outputs_are_exactly_the_attribution_figures():
    st = s1_store()
    att = attribute(st, trace(st, "TXN-1", TraceParams()))
    rec = record(s1_store())
    for k in ("per_transaction", "per_account", "buckets", "coverage", "exits", "holdable"):
        assert rec["outputs"][k] == json.loads(json.dumps(att[k])), k
    assert rec["outputs"]["per_transaction"]["TXN-2"]["min"] == rupees(28800)


def test_record_names_methods_versions_assumptions_and_inputs():
    rec = record(s1_store())
    assert [m["id"] for m in rec["methods"]] == list(METHODS)
    assert all(m["version"] and m["definition"] and m["formula"] for m in rec["methods"])
    assert {a["id"] for a in rec["assumptions"]} >= {"commingling", "time_order", "balances", "external_not_visible",
                                                      "excluded_records", "limits"}
    inp = rec["inputs"]
    assert [t["id"] for t in inp["transactions"]] == ["TXN-1", "TXN-2", "TXN-3"]  # order applied
    assert inp["transactions"][0]["role"] == "disputed" and all(t["treatment"] == "used" for t in inp["transactions"])
    bal = {b["account_id"]: b["balance_minor"] for b in inp["opening_balances"]}
    # B held ₹1,200 before the disputed money arrived; C (also followed) held ₹500
    assert bal == {"ACC-B": rupees(1200), "ACC-C": rupees(500)}
    treat = {a["id"]: a["treatment"] for a in inp["accounts"]}
    assert treat["ACC-B"] == "followed" and treat["ACC-D"] == "left_visibility"
    assert inp["trace_parameters"]["window_hours"] == 72 and inp["trace_parameters"]["depth"] == 3
    assert len(inp["fingerprint"]["value"]) == 64


def test_fingerprint_is_stable_and_changes_when_an_input_changes():
    a, b = record(s1_store()), record(s1_store())
    assert a["inputs"]["fingerprint"] == b["inputs"]["fingerprint"]
    assert a["outputs"]["fingerprint"] == b["outputs"]["fingerprint"]

    st = s1_store()
    st.txns["TXN-2"] = replace(st.txns["TXN-2"], amount_minor=rupees(29999))  # one rupee less onward
    changed = record(st)
    assert changed["inputs"]["fingerprint"]["value"] != a["inputs"]["fingerprint"]["value"]
    assert changed["outputs"]["fingerprint"]["value"] != a["outputs"]["fingerprint"]["value"]

    # an opening balance is an input too
    st2 = s1_store()
    st2.accounts["ACC-B"] = replace(st2.accounts["ACC-B"], opening_balance_minor=rupees(1300))
    assert record(st2)["inputs"]["fingerprint"]["value"] != a["inputs"]["fingerprint"]["value"]

    # so are the trace limits
    assert record(s1_store(), window_hours=48)["inputs"]["fingerprint"]["value"] != a["inputs"]["fingerprint"]["value"]


def test_record_alone_recreates_the_figures():
    rec = record(s1_store())
    downloaded = json.loads(json.dumps(rec))  # nothing but the JSON file
    again = cr.replay(downloaded)
    assert again["fingerprint"] == rec["outputs"]["fingerprint"]
    assert again["buckets"] == rec["outputs"]["buckets"]
    assert check(rec, "recompute")["status"] == "pass"


def test_tampered_record_fails_recompute():
    rec = record(s1_store())
    rec["inputs"]["transactions"][1]["amount_minor"] -= 100  # someone edits the input
    assert cr.replay(rec)["fingerprint"] != rec["outputs"]["fingerprint"]
    assert cr._check_recompute(rec)["status"] == "fail"


def test_conservation_passes_and_bounds_are_in_order_on_the_headline_case():
    rec = record(s1_store())
    cons = check(rec, "conservation")
    assert cons["status"] == "pass" and len(cons["items"]) == 4
    assert check(rec, "double_counting")["status"] == "pass"
    assert "must not be added" in check(rec, "double_counting")["detail"]
    assert check(rec, "bounds_order")["status"] == "pass"
    assert check(rec, "impossible_balances")["status"] == "pass"
    assert check(rec, "duplicates")["status"] == "pass"
    assert check(rec, "source_agreement")["status"] == "not_applicable"
    assert rec["checks_summary"]["fail"] == 0


def test_overdraft_is_reported_as_an_impossible_balance():
    # B had nothing, received ₹50,000 disputed, then sent ₹80,000 onward: the ledger is missing money in.
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 80000, 5)]
    rec = record(store(accounts, txns))
    bal = check(rec, "impossible_balances")
    assert bal["status"] == "warn"
    texts = " ".join(i["text"] for i in bal["items"])
    assert "TXN-2" in texts and "below zero" in texts
    assert check(rec, "recompute")["status"] == "pass"


def test_negative_opening_balance_is_flagged():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", -500), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 10000, 5)]
    bal = check(record(store(accounts, txns)), "impossible_balances")
    assert bal["status"] in ("warn", "fail")
    assert any("already below zero" in i["text"] for i in bal["items"])


def test_failed_and_reversed_records_are_listed_but_excluded():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-E", 0), acct("ACC-C", 0)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 50000, 0),
        txn("TXN-F", "ACC-B", "ACC-C", 10000, 3, status="failed"),
        txn("TXN-R", "ACC-B", "ACC-E", 50000, 5, status="reversed"),
        txn("TXN-RV", "ACC-E", "ACC-B", 50000, 20, reversal_of="TXN-R"),
    ]
    rec = record(store(accounts, txns))
    treat = {t["id"]: t["treatment"] for t in rec["inputs"]["transactions"]}
    assert treat["TXN-F"] == "excluded_failed"
    assert treat["TXN-R"] == "excluded_reversed" and treat["TXN-RV"] == "excluded_reverses_reversed"
    assert check(rec, "conservation")["status"] == "pass"


def test_source_record_counted_twice_fails_and_merged_sources_pass():
    st = s1_store()
    src = ({"system": "core", "record_id": "core-TXN-2", "amount_minor": rupees(30000), "currency": "INR", "status": "posted"},)
    st.txns["TXN-3"] = replace(st.txns["TXN-3"], sources=src)  # TXN-3 claims TXN-2's source record
    assert check(record(st), "duplicates")["status"] == "fail"

    st = s1_store()
    both = ({"system": "core", "record_id": "core-TXN-2", "amount_minor": rupees(30000), "currency": "INR", "status": "posted"},
            {"system": "upi_switch", "record_id": "npci-2", "amount_minor": rupees(30000), "currency": "INR", "status": "posted"})
    st.txns["TXN-2"] = replace(st.txns["TXN-2"], sources=both)
    rec = record(st)
    dup = check(rec, "duplicates")
    assert dup["status"] == "pass" and any("merged into one payment" in i["text"] for i in dup["items"])
    assert check(rec, "source_agreement")["status"] == "pass"
    assert rec["amount_ranges"] == []


def test_same_reference_kept_separate_is_a_possible_duplicate():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 10000, 5, ref="UTR-SAME"),
            txn("TXN-3", "ACC-B", "ACC-C", 10000, 30, ref="UTR-SAME")]
    assert check(record(store(accounts, txns)), "duplicates")["status"] == "warn"


def test_amount_range_when_sources_disagree_on_a_trail_payment():
    st = s1_store()
    both = ({"system": "core", "record_id": "core-TXN-2", "amount_minor": rupees(30000), "currency": "INR", "status": "posted",
             "discrepancies": [{"source": "upi_switch", "fields": {"amount_minor": {"primary": rupees(30000), "other": rupees(29500)}}}]},
            {"system": "upi_switch", "record_id": "npci-2", "amount_minor": rupees(29500), "currency": "INR", "status": "posted"})
    st.txns["TXN-2"] = replace(st.txns["TXN-2"], sources=both)
    rec = record(st)
    (r,) = rec["amount_ranges"]
    assert (r["txn_id"], r["role"], r["min_minor"], r["max_minor"], r["used_minor"]) == ("TXN-2", "trail", rupees(29500), rupees(30000), rupees(30000))
    assert r["used_system"] == "core" and "₹29,500 ≤ amount ≤ ₹30,000" == r["statement"]
    assert check(rec, "source_agreement")["status"] == "warn"


def test_diff_lists_paths():
    assert cr.diff({"a": {"b": 1, "c": [1, 2]}}, {"a": {"b": 2, "c": [1, 3]}}) == ["a.b: 1 → 2", "a.c[1]: 2 → 3"]


# ---------------------------------------------------------------------------- API (seeded database)

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


def login(c, user):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text


def test_seeded_cases_conserve_money_and_recompute(client):
    login(client, "sup.meera")
    for cid in ("CASE-24051", "CASE-24044", "CASE-24031", "CASE-24039", "CASE-24045"):
        rec = client.get(f"/api/cases/{cid}/calculation").json()
        assert check(rec, "conservation")["status"] == "pass", cid
        assert check(rec, "recompute")["status"] == "pass", cid
        assert rec["checks_summary"]["fail"] == 0, cid
        graph = client.get(f"/api/cases/{cid}/graph").json()["attribution"]
        assert rec["outputs"]["buckets"] == graph["buckets"], cid  # same figures as the trail view


def test_s10_sources_disagree_gives_an_amount_range(client):
    login(client, "inv.asha")
    rec = client.get("/api/cases/CASE-24045/calculation").json()
    (r,) = rec["amount_ranges"]
    assert r["role"] == "disputed" and r["txn_id"] == rec["disputed_txn_id"]
    assert (r["min_minor"], r["max_minor"]) == (999000, 999900)
    assert r["used_system"] == "core" and r["used_minor"] == 999900  # the ledger keeps core banking as the main record
    assert {s["system"]: s["amount_minor"] for s in r["reported"]} == {"core": 999900, "upi_switch": 999000}
    assert "₹9,990–₹9,999" in r["explanation"] and "core banking amount ₹9,999" in r["explanation"]
    assert check(rec, "source_agreement")["status"] == "warn"
    dup = check(rec, "duplicates")
    assert dup["status"] == "pass" and any("merged" in i["text"] for i in dup["items"])
    assert rec["outputs"]["disputed_amount_minor"] == 999900


def test_verify_endpoint(client):
    login(client, "inv.asha")
    rec = client.get("/api/cases/CASE-24051/calculation").json()
    fp = rec["inputs"]["fingerprint"]["value"]
    v = client.get(f"/api/cases/CASE-24051/calculation/verify?fingerprint={fp}").json()
    assert v["matches"] is True and v["fingerprint"] == fp and v["differences"] == []
    assert v["output_fingerprint"] == rec["outputs"]["fingerprint"]["value"]
    stale = client.get(f"/api/cases/CASE-24051/calculation/verify?fingerprint={'0' * 64}").json()
    assert stale["matches"] is False and any("changed" in d for d in stale["differences"])
    assert client.get("/api/cases/CASE-24051/calculation/verify?fingerprint=nothex").status_code == 422
    # other parameters give another (still reproducible) record
    v48 = client.get("/api/cases/CASE-24051/calculation/verify?window_hours=48").json()
    assert v48["matches"] is True


def test_download_is_an_audited_attachment(client):
    login(client, "inv.asha")
    before = [e for e in client.get("/api/cases/CASE-24051/audit").json()["events"] if e["action"] == "calculation_exported"]
    plain = client.get("/api/cases/CASE-24051/calculation")
    after_view = [e for e in client.get("/api/cases/CASE-24051/audit").json()["events"] if e["action"] == "calculation_exported"]
    assert len(after_view) == len(before)  # viewing is not exporting
    r = client.get("/api/cases/CASE-24051/calculation?download=1")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;") and ".json" in r.headers["content-disposition"]
    body = json.loads(r.content)
    assert body["inputs"]["fingerprint"] == plain.json()["inputs"]["fingerprint"]
    events = [e for e in client.get("/api/cases/CASE-24051/audit").json()["events"] if e["action"] == "calculation_exported"]
    assert len(events) == len(before) + 1
    assert events[-1]["details"]["fingerprint"] == body["inputs"]["fingerprint"]["value"]
    assert events[-1]["actor"] == "inv.asha"
    assert client.get("/api/cases/CASE-24051/audit").json()["verification"]["valid"] is True


def test_access_control(client):
    client.cookies.clear()
    assert client.get("/api/cases/CASE-24031/calculation").status_code == 401
    login(client, "inv.asha")  # CASE-24031 belongs to inv.ravi
    for path in ("/api/cases/CASE-24031/calculation", "/api/cases/CASE-24031/calculation/verify",
                 "/api/cases/CASE-24031/calculation?download=1", "/api/cases/CASE-NOPE/calculation"):
        assert client.get(path).status_code == 404, path
    login(client, "inv.ravi")
    assert client.get("/api/cases/CASE-24031/calculation").status_code == 200


def test_input_validation(client):
    login(client, "inv.asha")
    assert client.get("/api/cases/CASE-24051/calculation?depth=0").status_code == 422
    assert client.get("/api/cases/CASE-24051/calculation?direction=sideways").status_code == 422
    assert client.get("/api/cases/CASE-24051/calculation?expand=ACC-NOT-ON-TRAIL").status_code == 422
