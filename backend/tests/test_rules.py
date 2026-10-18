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
    for rid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12", "R13", "R14", "R15"):
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


def external_payer_store():
    return store([acct("ACC-X", external=True), acct("ACC-B", 0)], [txn("TXN-1", "ACC-X", "ACC-B", 48000, 0)])


def payer_store(payments, history_to="ACC-M", history=6):
    """ACC-A pays ``payments`` [(id, dst, amount, minutes)] after ``history`` ordinary payments (2 days apart)."""
    accounts = [acct("ACC-A", 1_000_000), acct("ACC-B", 0), acct("ACC-C", 0), acct("ACC-M", 0, kind="merchant")]
    hist = [txn(f"TXN-H{i}", "ACC-A", history_to, 900, -60 * 24 * 2 * (i + 1)) for i in range(history)]
    return store(accounts, hist + [txn(i, "ACC-A", dst, amt, mins) for i, dst, amt, mins in payments])


def test_r13_many_payments_in_a_short_time():
    burst = [(f"TXN-V{i}", "ACC-C", 2000, -20 + 5 * i) for i in range(4)] + [("TXN-1", "ACC-B", 50000, 0)]
    r = by_id(ctx_for(payer_store(burst)))["R13"]
    assert r.status == TRIGGERED and r.severity == "medium"
    assert {"TXN-1", "TXN-V0", "TXN-V3"} <= set(r.source_ids)
    assert all(f["source_ids"] for f in r.facts)
    # payments after the disputed one count too (the window covers before and after)
    after = [("TXN-1", "ACC-B", 50000, 0)] + [(f"TXN-V{i}", "ACC-C", 2000, 5 + 5 * i) for i in range(4)]
    assert by_id(ctx_for(payer_store(after)))["R13"].status == TRIGGERED
    # five payments spread over 40 minutes: no 30-minute stretch holds five
    spread = [(f"TXN-V{i}", "ACC-C", 2000, -40 + 10 * i) for i in range(4)] + [("TXN-1", "ACC-B", 50000, 0)]
    nt = by_id(ctx_for(payer_store(spread)))["R13"]
    assert nt.status == NOT_TRIGGERED and nt.facts
    # failed attempts moved no money and are not counted
    failed = store([acct("ACC-A", 100000), acct("ACC-B", 0)],
                   [txn(f"TXN-F{i}", "ACC-A", "ACC-B", 100, -10 + i, status="failed") for i in range(4)] + [txn("TXN-1", "ACC-A", "ACC-B", 500, 0)])
    assert by_id(ctx_for(failed))["R13"].status == NOT_TRIGGERED
    ne = by_id(ctx_for(external_payer_store()))["R13"]
    assert ne.status == NOT_EVALUABLE and ne.missing_fields
    lowered = {r.rule_id: r for r in evaluate(ctx_for(payer_store(spread)), {"R13": (2, {"window_minutes": 45}, True)})}
    assert lowered["R13"].status == TRIGGERED and lowered["R13"].version == 2


def test_r14_first_payment_to_this_beneficiary():
    r = by_id(ctx_for(payer_store([("TXN-1", "ACC-B", 50000, 0)])))["R14"]
    assert r.status == TRIGGERED and r.severity == "medium"
    assert "TXN-1" in r.source_ids and r.facts and all(f["source_ids"] for f in r.facts)
    # paid this beneficiary before -> not triggered, citing the earlier payment
    known = by_id(ctx_for(payer_store([("TXN-1", "ACC-B", 50000, 0)], history_to="ACC-B")))["R14"]
    assert known.status == NOT_TRIGGERED and "TXN-H0" in known.source_ids
    # small amount -> not triggered
    assert by_id(ctx_for(payer_store([("TXN-1", "ACC-B", 4000, 0)])))["R14"].status == NOT_TRIGGERED
    # too little history to say the beneficiary is new -> not evaluable, never clear
    thin = by_id(ctx_for(payer_store([("TXN-1", "ACC-B", 50000, 0)], history=2)))["R14"]
    assert thin.status == NOT_EVALUABLE and "found 2" in thin.missing_fields[0]
    assert by_id(ctx_for(s1_store()))["R14"].status == NOT_EVALUABLE
    assert by_id(ctx_for(external_payer_store()))["R14"].status == NOT_EVALUABLE
    raised = {r.rule_id: r for r in evaluate(ctx_for(payer_store([("TXN-1", "ACC-B", 50000, 0)])),
                                              {"R14": (3, {"min_amount_rupees": 60000}, True)})}
    assert raised["R14"].status == NOT_TRIGGERED and raised["R14"].params["lookback_days"] == 180
    # a first order at a merchant is ordinary: the sign does not apply (and says why)
    shop = by_id(ctx_for(payer_store([("TXN-1", "ACC-M", 50000, 0)], history_to="ACC-C")))["R14"]
    assert shop.status == NOT_TRIGGERED and "merchant" in shop.facts[0]["text"]


def test_r15_payments_just_below_a_review_limit():
    pays = [("TXN-P", "ACC-C", 48000, -300), ("TXN-1", "ACC-B", 47500, 0)]
    r = by_id(ctx_for(payer_store(pays)))["R15"]
    assert r.status == TRIGGERED and r.severity == "low"
    assert {"TXN-P", "TXN-1"} <= set(r.source_ids) and all(f["source_ids"] for f in r.facts)
    # one payment exactly at the limit and one well below the band -> not triggered
    nt = by_id(ctx_for(payer_store([("TXN-P", "ACC-C", 44000, -300), ("TXN-1", "ACC-B", 50000, 0)])))["R15"]
    assert nt.status == NOT_TRIGGERED and nt.facts
    # outside the 24-hour window
    far = [("TXN-P", "ACC-C", 48000, -60 * 25), ("TXN-1", "ACC-B", 47500, 0)]
    assert by_id(ctx_for(payer_store(far)))["R15"].status == NOT_TRIGGERED
    assert by_id(ctx_for(external_payer_store()))["R15"].status == NOT_EVALUABLE
    wider = {r.rule_id: r for r in evaluate(ctx_for(payer_store(far)), {"R15": (2, {"window_hours": 30}, True)})}
    assert wider["R15"].status == TRIGGERED


def test_rules_are_reproducible():
    a = [(r.rule_id, r.status, r.source_ids) for r in evaluate(ctx_for(s1_store()))]
    b = [(r.rule_id, r.status, r.source_ids) for r in evaluate(ctx_for(s1_store()))]
    assert a == b
