from app.services.attribution import METHODS, annotate_graph, attribute
from app.services.trace import DERIVED, INFERRED, TraceParams, trace

from tests.builders import acct, rupees, s1_store, store, txn


def run(st, root="TXN-1", **kw):
    res = trace(st, root, TraceParams(**kw))
    return res, attribute(st, res)


def test_headline_bounds_match_balance_arithmetic():
    _, a = run(s1_store())
    t2, t3 = a["per_transaction"]["TXN-2"], a["per_transaction"]["TXN-3"]
    # B held ₹1,200 before receiving ₹50,000, so at least ₹28,800 of the ₹30,000 must be disputed funds
    assert t2["min"] == rupees(28800) and t2["max"] == rupees(30000)
    assert t2["fifo"] == rupees(28800)
    assert t2["pro_rata"] == round(rupees(30000) * rupees(50000) / rupees(51200))
    assert t3["min"] == rupees(20000) and t3["max"] == rupees(20000)
    assert t2["provenance"] == DERIVED


def test_money_is_conserved_under_every_method():
    for st in (s1_store(),):
        _, a = run(st)
        total = a["disputed_amount_minor"]
        for m in METHODS:
            b = a["buckets"][m]
            assert b["unaccounted"] == 0, (m, b)
            assert sum(v for k, v in b.items() if k != "unaccounted") == total


def test_mixed_funds_make_bounds_diverge():
    # B2 receives ₹40,000 disputed, then ₹60,000 unrelated salary, then sends ₹70,000 onward.
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-S", 500000), acct("ACC-C", 0)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 40000, 0),
        txn("TXN-SAL", "ACC-S", "ACC-B", 60000, 5),
        txn("TXN-2", "ACC-B", "ACC-C", 70000, 10),
    ]
    _, a = run(store(accounts, txns))
    t2 = a["per_transaction"]["TXN-2"]
    assert t2["max"] == rupees(40000)
    assert t2["min"] == rupees(10000)  # only ₹60,000 clean available, so ≥ ₹10,000 must be disputed
    assert t2["fifo"] == rupees(40000)  # disputed funds arrived first
    assert t2["pro_rata"] == rupees(28000)
    assert t2["min"] < t2["pro_rata"] < t2["max"]


def test_clean_balance_alone_can_cover_a_debit_so_link_is_only_inferred():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 500000), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 30000, 5)]
    res, a = run(store(accounts, txns))
    t2 = a["per_transaction"]["TXN-2"]
    assert t2["min"] == 0 and t2["max"] == rupees(30000)
    assert t2["provenance"] == INFERRED
    annotate_graph(res, a)
    edge = next(e for e in res.edges.values() if e["type"] == "possible_onward_funding")
    assert edge["provenance"] == INFERRED and "not established" in edge["label"]


def test_unknown_opening_balance_limits_methods():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", None), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 30000, 5)]
    _, a = run(store(accounts, txns))
    t2 = a["per_transaction"]["TXN-2"]
    assert t2["min"] == 0 and t2["max"] == rupees(30000)
    assert t2["fifo"] is None and t2["pro_rata"] is None
    assert a["coverage"]["fifo"] is None


def test_reversed_onward_transfer_moves_no_taint():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-E", 0)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 50000, 0),
        txn("TXN-R", "ACC-B", "ACC-E", 50000, 5, status="reversed"),
        txn("TXN-RV", "ACC-E", "ACC-B", 50000, 20, reversal_of="TXN-R"),
    ]
    _, a = run(store(accounts, txns))
    assert a["per_account"]["ACC-B"]["residual"]["max"] == rupees(50000)
    assert a["buckets"]["max"]["unaccounted"] == 0


def test_hold_candidates_are_visible_accounts_with_residual():
    _, a = run(s1_store())
    ids = [h["account_id"] for h in a["holdable"]]
    assert "ACC-C" in ids and "ACC-D" not in ids  # external accounts cannot be held by this bank


def test_returned_to_payer_bucket():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-A", 50000, 5)]
    _, a = run(store(accounts, txns))
    assert a["buckets"]["max"]["returned_to_payer"] == rupees(50000)


def test_disputed_payment_straight_to_external_or_merchant_is_conserved():
    for kind, external, bucket in (("savings", True, "left_visibility"), ("merchant", False, "reached_merchant_or_hub")):
        accounts = [acct("ACC-A", 100000), acct("ACC-X", 0, external=external, kind=kind)]
        _, a = run(store(accounts, [txn("TXN-1", "ACC-A", "ACC-X", 50000, 0)]))
        assert a["buckets"]["max"][bucket] == rupees(50000)
        assert all(a["buckets"][m]["unaccounted"] == 0 for m in METHODS)
