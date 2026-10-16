from app.services.trace import CONFIRMED, TraceParams, trace

from tests.builders import acct, s1_store, store, txn


def P(**kw):
    return TraceParams(**kw)


def test_headline_trail_reconstructed_from_records():
    res = trace(s1_store(), "TXN-1", P())
    assert set(res.txns) == {"TXN-1", "TXN-2", "TXN-3"}
    # every transaction node and sent/received edge is confirmed by a record
    for e in res.edges.values():
        assert e["provenance"] == CONFIRMED and e["source_ids"]
    assert res.nodes["ACC-D"]["endpoint"] == "visibility_ends"
    assert res.nodes["ACC-C"]["endpoint"] == "funds_remain"
    chains = {p["endpoint_account_id"]: p["txn_ids"] for p in res.paths}
    assert chains["ACC-C"] == ["TXN-1", "TXN-2"]
    assert chains["ACC-D"] == ["TXN-1", "TXN-3"]


def test_hops_must_respect_time_order():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 100000), acct("ACC-C", 0)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 50000, 60),
        txn("TXN-EARLY", "ACC-B", "ACC-C", 30000, 0),  # before the disputed funds arrived
    ]
    res = trace(store(accounts, txns), "TXN-1", P())
    assert "TXN-EARLY" not in res.txns
    assert res.nodes["ACC-B"]["endpoint"] == "funds_remain"


def test_cycle_detected_without_infinite_expansion():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 50000, 0),
        txn("TXN-2", "ACC-B", "ACC-C", 50000, 5),
        txn("TXN-3", "ACC-C", "ACC-A", 50000, 10),
        txn("TXN-4", "ACC-A", "ACC-B", 50000, 15),
    ]
    res = trace(store(accounts, txns), "TXN-1", P(depth=5))
    assert res.cycles, "cycle should be reported"
    assert res.nodes["ACC-A"]["endpoint"] == "cycle"


def test_failed_and_reversed_are_shown_but_not_followed():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0), acct("ACC-E", 0), acct("ACC-F", 0)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 50000, 0),
        txn("TXN-F", "ACC-B", "ACC-C", 10000, 5, status="failed"),
        txn("TXN-R", "ACC-B", "ACC-E", 10000, 6, status="reversed"),
        txn("TXN-RV", "ACC-E", "ACC-B", 10000, 30, reversal_of="TXN-R"),
        txn("TXN-C2", "ACC-C", "ACC-F", 10000, 40),
    ]
    res = trace(store(accounts, txns), "TXN-1", P())
    assert "TXN-F" in res.txns and "TXN-R" in res.txns
    assert "TXN-C2" not in res.txns  # C only got a failed transfer
    assert "TXN-RV" in res.txns  # reversal attached
    assert any(e["type"] == "reversal_of" for e in res.edges.values())


def test_hub_account_pauses_expansion_and_is_expandable():
    accounts = [acct("ACC-A", 100000), acct("ACC-H", 0, kind="current")] + [acct(f"ACC-X{i}", 0) for i in range(30)]
    txns = [txn("TXN-1", "ACC-A", "ACC-H", 50000, 0)]
    txns += [txn(f"TXN-H{i}", "ACC-H", f"ACC-X{i}", 100, 5 + i) for i in range(30)]
    res = trace(store(accounts, txns), "TXN-1", P(hub_threshold=25))
    assert res.nodes["ACC-H"]["endpoint"] == "hub_paused"
    assert res.nodes["ACC-H"]["expandable"]
    assert len(res.txns) == 1
    res2 = trace(store(accounts, txns), "TXN-1", P(hub_threshold=25, expand_accounts=("ACC-H",)))
    assert len(res2.txns) == 31


def test_depth_and_node_caps_are_reported():
    accounts = [acct(f"ACC-{i}", 0) for i in range(8)]
    accounts[0] = acct("ACC-0", 100000)
    txns = [txn(f"TXN-{i}", f"ACC-{i}", f"ACC-{i+1}", 1000, i) for i in range(7)]
    res = trace(store(accounts, txns), "TXN-0", P(depth=2))
    assert res.nodes["ACC-3"]["endpoint"] == "depth_limit"
    assert "TXN-3" not in res.txns
    res2 = trace(store(accounts, txns), "TXN-0", P(depth=5, max_nodes=10))
    assert res2.truncated


def test_window_boundary():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-LATE", "ACC-B", "ACC-C", 50000, 60 * 73)]
    assert "TXN-LATE" not in trace(store(accounts, txns), "TXN-1", P(window_hours=72)).txns
    assert "TXN-LATE" in trace(store(accounts, txns), "TXN-1", P(window_hours=74)).txns


def test_missing_reference_is_flagged_not_dropped():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0), txn("TXN-2", "ACC-B", "ACC-C", 1000, 3, ref=None)]
    res = trace(store(accounts, txns), "TXN-1", P())
    assert res.nodes["TXN-2"]["data"]["reference_missing"]
    assert "missing_reference" in res.nodes["TXN-2"]["flags"]


def test_backward_trace_finds_source_of_funds():
    accounts = [acct("ACC-S", 100000), acct("ACC-A", 0), acct("ACC-B", 0)]
    txns = [txn("TXN-0", "ACC-S", "ACC-A", 60000, -30), txn("TXN-1", "ACC-A", "ACC-B", 50000, 0)]
    res = trace(store(accounts, txns), "TXN-1", P(direction="both"))
    assert "TXN-0" in res.txns
    assert "upstream" in res.nodes["ACC-S"]["roles"]


def test_failed_disputed_transaction_has_no_trail():
    accounts = [acct("ACC-A", 100000), acct("ACC-B", 0), acct("ACC-C", 0)]
    txns = [txn("TXN-1", "ACC-A", "ACC-B", 50000, 0, status="failed"), txn("TXN-2", "ACC-B", "ACC-C", 100, 5)]
    res = trace(store(accounts, txns), "TXN-1", P())
    assert set(res.txns) == {"TXN-1"} and res.warnings


def test_params_are_clamped():
    p = TraceParams(depth=99, window_hours=99999, max_nodes=99999).clamp(5, 720, 300)
    assert (p.depth, p.window_hours, p.max_nodes) == (5, 720, 300)


def test_merchant_account_ends_trail_by_default():
    accounts = [acct("ACC-A", 100000), acct("ACC-M", 0, kind="merchant"), acct("ACC-S", external=True)]
    txns = [txn("TXN-1", "ACC-A", "ACC-M", 649, 0), txn("TXN-2", "ACC-M", "ACC-S", 5000, 30)]
    res = trace(store(accounts, txns), "TXN-1", P())
    assert res.nodes["ACC-M"]["endpoint"] == "merchant" and "TXN-2" not in res.txns
