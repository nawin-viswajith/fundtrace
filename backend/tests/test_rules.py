"""Every rule: triggers, does not trigger, and is not evaluable when its data is missing."""
from app.services.attribution import attribute
from app.services.rules import NOT_EVALUABLE, NOT_TRIGGERED, TRIGGERED, RuleContext, evaluate
from app.services.trace import TraceParams, trace

from tests.builders import acct, auth, device, link, s1_store, store, txn


def ctx_for(st, case_id="CASE-1", evidence=None, root="TXN-1"):
    res = trace(st, root, TraceParams())
    att = attribute(st, res)
    t = st.get_transaction(root)
    return RuleContext(case_id=case_id, category="unauthorised_transfer", root=t, payer=st.get_account(t.debit_account_id),
                       payee=st.get_account(t.credit_account_id), trace=res, attribution=att, store=st, evidence=evidence or [])


def by_id(ctx):
    return {r.rule_id: r for r in evaluate(ctx)}


def quiet_store(**kw):
    """A payment with no onward movement, old beneficiary, normal history."""
    accounts = [acct("ACC-A", 200000), acct("ACC-B", 1000, opened_days_ago=900)]
    txns = [txn(f"TXN-H{i}", "ACC-A", "ACC-B", 1000, -60 * 24 * (i + 1)) for i in range(8)]
    txns.append(txn("TXN-1", "ACC-A", "ACC-B", 1500, 0, device="DEV-OLD"))
    return store(accounts, txns, devices=[device("DEV-OLD", -60 * 24 * 300)],
                 auth=[auth("AU-0", "ACC-A", "success", -60 * 24 * 100, "DEV-OLD"),
                       auth("AU-1", "ACC-A", "success", -5, "DEV-OLD")], **kw)


def test_headline_triggers_movement_rules():
    r = by_id(ctx_for(s1_store()))
    assert r["R1"].status == TRIGGERED and "TXN-2" in r["R1"].source_ids
    assert r["R2"].status == TRIGGERED
    assert r["R7"].status == TRIGGERED  # beneficiary opened 9 days ago
    assert r["R11"].status == TRIGGERED  # ₹20,000 left to the external bank
    for res in r.values():
        assert res.limitations, f"{res.rule_id} must state limitations"
        if res.status == TRIGGERED:
            assert res.facts and res.source_ids


def test_quiet_case_does_not_trigger():
    r = by_id(ctx_for(quiet_store()))
    for rid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12"):
        assert r[rid].status == NOT_TRIGGERED, (rid, r[rid].status, r[rid].missing_fields)


def test_missing_data_is_not_evaluable_never_clear():
    r = by_id(ctx_for(s1_store()))  # no auth logs, no device, short history, no evidence
    for rid in ("R4", "R5", "R6", "R9"):
        assert r[rid].status == NOT_EVALUABLE and r[rid].missing_fields, rid


def test_external_beneficiary_makes_movement_rules_not_evaluable():
    st = store([acct("ACC-A", 100000), acct("ACC-X", external=True)], [txn("TXN-1", "ACC-A", "ACC-X", 50000, 0)])
    r = by_id(ctx_for(st))
    assert r["R1"].status == NOT_EVALUABLE and r["R2"].status == NOT_EVALUABLE and r["R7"].status == NOT_EVALUABLE


def test_r1_slow_movement_does_not_trigger():
    st = store([acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)],
               [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 50000, 300)])
    assert by_id(ctx_for(st))["R1"].status == NOT_TRIGGERED


def test_r3_shared_beneficiary():
    r = by_id(ctx_for(s1_store(links=[link("CASE-9", "TXN-X", "ACC-B"), link("CASE-8", "TXN-Y", "ACC-B")])))
    assert r["R3"].status == TRIGGERED and r["R3"].severity == "high"
    own = by_id(ctx_for(s1_store(links=[link("CASE-1", "TXN-1", "ACC-B")])))
    assert own["R3"].status == NOT_TRIGGERED  # its own case does not count


def test_r4_failed_logins_then_success():
    evs = [auth(f"AU-F{i}", "ACC-A", "failure", -12 + i, "DEV-N") for i in range(4)] + [auth("AU-S", "ACC-A", "success", -6, "DEV-N")]
    r = by_id(ctx_for(s1_store(auth=evs)))
    assert r["R4"].status == TRIGGERED and "AU-S" in r["R4"].source_ids
    few = [auth("AU-F1", "ACC-A", "failure", -12), auth("AU-S", "ACC-A", "success", -6)]
    assert by_id(ctx_for(s1_store(auth=few)))["R4"].status == NOT_TRIGGERED


def test_r5_new_device_on_this_account():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0)]
    hist = [auth("AU-OLD", "ACC-A", "success", -60 * 24 * 30, "DEV-OLD"), auth("AU-N", "ACC-A", "success", -20, "DEV-N")]
    st = store(accounts, [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0, device="DEV-N")], auth=hist)
    assert by_id(ctx_for(st))["R5"].status == TRIGGERED
    st2 = store(accounts, [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0, device="DEV-OLD")], auth=hist)
    assert by_id(ctx_for(st2))["R5"].status == NOT_TRIGGERED


def test_r6_unusual_amount():
    accounts = [acct("ACC-A", 500000), acct("ACC-B", 0)]
    hist = [txn(f"TXN-H{i}", "ACC-A", "ACC-B", 2000, -60 * 24 * (i + 1)) for i in range(6)]
    st = store(accounts, hist + [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0)])
    assert by_id(ctx_for(st))["R6"].status == TRIGGERED


def test_r8_reversal_then_resend():
    accounts = [acct("ACC-A", 200000), acct("ACC-B", 0), acct("ACC-Z", 0)]
    txns = [txn("TXN-R", "ACC-A", "ACC-Z", 50000, -60, status="reversed"), txn("TXN-RV", "ACC-Z", "ACC-A", 50000, -50, reversal_of="TXN-R"),
            txn("TXN-1", "ACC-A", "ACC-B", 50000, 0)]
    assert by_id(ctx_for(store(accounts, txns)))["R8"].status == TRIGGERED


def test_r9_evidence_contradiction():
    ev = [{"id": "EV-1", "analysis_status": "analysed", "reconciliation": {"checks": [
        {"field": "amount", "result": "contradicts", "document_value": "45000.00", "ledger_value": "50000.00", "ledger_id": "TXN-1"}]}}]
    r = by_id(ctx_for(s1_store(), evidence=ev))
    assert r["R9"].status == TRIGGERED and "EV-1" in r["R9"].source_ids
    ok = [{"id": "EV-2", "analysis_status": "analysed", "reconciliation": {"checks": [{"field": "amount", "result": "matches"}]}}]
    assert by_id(ctx_for(s1_store(), evidence=ok))["R9"].status == NOT_TRIGGERED
    not_analysed = [{"id": "EV-3", "analysis_status": "not_analysed", "reconciliation": None}]
    assert by_id(ctx_for(s1_store(), evidence=not_analysed))["R9"].status == NOT_EVALUABLE


def test_r10_shared_device():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-Q", 50000)]
    txns = [txn("TXN-Q", "ACC-Q", "ACC-B", 100, -500, device="DEV-S"), txn("TXN-1", "ACC-A", "ACC-B", 50000, 0, device="DEV-S")]
    st = store(accounts, txns, devices=[device("DEV-S", -9000)])
    assert by_id(ctx_for(st))["R10"].status == TRIGGERED


def test_r12_missing_reference():
    st = store([acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)],
               [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 100, 5, ref=None)])
    assert by_id(ctx_for(st))["R12"].status == TRIGGERED


def test_disabled_rule_is_skipped_and_params_override():
    ctx = ctx_for(s1_store())
    res = {r.rule_id: r for r in evaluate(ctx, {"R7": (2, {"max_age_days": 5}, True), "R12": (2, {}, False)})}
    assert "R12" not in res
    assert res["R7"].status == NOT_TRIGGERED and res["R7"].version == 2


def test_rules_are_reproducible():
    a = [(r.rule_id, r.status, r.source_ids) for r in evaluate(ctx_for(s1_store()))]
    b = [(r.rule_id, r.status, r.source_ids) for r in evaluate(ctx_for(s1_store()))]
    assert a == b
