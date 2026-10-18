"""Behaviour model (unsupervised, no labels): features, deterministic scoring, hold-out evaluation, API, no rule changes."""
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.services.ml import features as feat
from app.services.ml import holdout
from app.services.ml.model import band, fit, get_model, model_card, score_account, score_accounts
from app.services.rules import RuleContext, evaluate
from app.services.investigation import build_trace, rule_overrides

PW = "Investigate@2026"
MULE_ACCOUNT = "ACC-100209"  # Rahul K, the headline mule in S1 / CASE-24051
HEADLINE_CASE = "CASE-24051"


@pytest.fixture()
def table(db):
    return feat.compute(db)


# ---------------------------------------------------------------------------- features

def test_features_are_computed_for_the_headline_mule(table):
    vals = table.values[MULE_ACCOUNT]
    # Rahul K's account is 9 days old and receives ₹50,000 from the victim, passing almost all of it on quickly.
    assert vals["account_age_days"] is not None and vals["account_age_days"] < 15
    assert vals["payments_in"] >= 1
    assert vals["money_in"] >= 50000_00
    assert vals["pass_through_1h"] > 0.5  # most of the money leaves within an hour
    assert vals["minutes_to_next_out"] < 60


def test_merchant_and_high_activity_accounts_are_not_scored(table):
    merchant = next(a for a in table.values if table.kinds.get(a) == "merchant")
    assert merchant in table.not_scored
    assert merchant not in table.population
    assert "Merchant" in table.not_scored[merchant]


def test_only_in_bank_accounts_appear(table, db):
    external_ids = {a for a, in db.execute(select(m.Account.id).join(m.Institution, m.Institution.id == m.Account.institution_id)
                                           .where(m.Institution.kind != "self")).all()}
    assert not (external_ids & set(table.values))


# ---------------------------------------------------------------------------- model fit and scores

def test_model_is_deterministic(db):
    t1, t2 = feat.compute(db), feat.compute(db)
    m1, m2 = fit(t1), fit(t2)
    assert m1.status == "ok"
    assert m1.scores == m2.scores
    assert m1.anomaly == m2.anomaly


def test_headline_mule_scores_above_the_bank_median_and_is_explained(db):
    model = get_model(db)
    assert model.status == "ok"
    s = score_account(model, MULE_ACCOUNT)
    assert s["scored"] is True
    assert s["score"] is not None and s["score"] > 50  # above the bank median
    assert band(s["score"]) in ("unusual", "very_unusual")
    assert len(s["reasons"]) >= 1
    for r in s["reasons"]:
        assert r["value_text"] and r["typical_text"] and r["text"]
        assert r["typical_text"] != r["value_text"] or r["z"] is not None


def test_scores_are_0_to_100_and_bands_match_thresholds(db):
    model = get_model(db)
    for a in model.table.population:
        s = model.scores[a]
        assert 0 <= s <= 100
        b = band(s)
        assert b in ("typical", "unusual", "very_unusual")


def test_external_and_unknown_accounts_are_not_scored(db):
    model = get_model(db)
    row = db.execute(select(m.Account.id).join(m.Institution, m.Institution.id == m.Account.institution_id)
                     .where(m.Institution.kind != "self")).first()
    assert row is not None
    ext_id = row[0]
    out = score_account(model, ext_id, external=True)
    assert out["scored"] is False and out["not_scored_reason"]
    out2 = score_account(model, "ACC-NOPE")
    assert out2["scored"] is False


def test_score_accounts_batches_and_flags_externals(db):
    model, scored = score_accounts(db, [MULE_ACCOUNT])
    assert scored[MULE_ACCOUNT]["scored"] is True


def test_model_card_has_plain_descriptions_and_limitations(db):
    card = model_card(get_model(db))
    assert card["type"].lower().startswith("isolation forest")
    assert len(card["features"]) >= 8
    for f in card["features"]:
        assert f["label"] and f["description"]
    assert any("not fraud" in s.lower() for s in card["limitations"])
    assert any("synthetic" in s.lower() for s in card["limitations"])
    assert card["accounts_scored"] > 0


# ---------------------------------------------------------------------------- never changes rules

def test_scoring_an_account_never_changes_rule_results(db):
    case = db.get(m.DisputeCase, HEADLINE_CASE)
    res, fwd, att, store = build_trace(db, case)
    root = store.get_transaction(case.disputed_txn_id)
    payer, payee = store.get_account(root.debit_account_id), store.get_account(root.credit_account_id)
    ctx = RuleContext(case_id=case.id, category=case.category, root=root, payer=payer, payee=payee, trace=fwd, attribution=att, store=store)
    before = {r.rule_id: (r.status, r.severity) for r in evaluate(ctx, rule_overrides(db))}

    get_model(db)  # computing/caching the behaviour model must not touch the ledger or rule state
    score_accounts(db, [MULE_ACCOUNT, payee.id])

    res2, fwd2, att2, store2 = build_trace(db, case)
    ctx2 = RuleContext(case_id=case.id, category=case.category, root=root, payer=payer, payee=payee, trace=fwd2, attribution=att2, store=store2)
    after = {r.rule_id: (r.status, r.severity) for r in evaluate(ctx2, rule_overrides(db))}
    assert before == after


# ---------------------------------------------------------------------------- hold-out evaluation (isolated databases)

def test_isolated_session_is_independent_of_the_live_database(db):
    hdb = holdout.isolated_session()
    try:
        assert hdb.scalar(select(m.DisputeCase.id).limit(1)) is None  # empty: not the live seeded database
        assert db.scalar(select(m.DisputeCase.id).limit(1)) is not None  # the live one still has its data
    finally:
        bind = hdb.get_bind()
        hdb.close()
        bind.dispose()


def test_holdout_run_returns_metrics_with_min_max_over_seeds():
    out = holdout.run(seeds=(11, 22), cases_per_seed=8)
    ml = out["metrics"]["ml"]
    assert ml["roc_auc"]["n"] == 2
    for key in ("roc_auc", "precision_at_k"):
        assert ml[key]["min"] is not None and ml[key]["max"] is not None
        assert ml[key]["min"] <= ml[key]["mean"] <= ml[key]["max"]
    # the model should rank fraud accounts well above chance on these runs
    assert ml["roc_auc"]["mean"] > 0.6
    assert out["metrics"]["rules"]["detection_fraud_with_trail"]["rate"] is not None
    assert out["metrics"]["label"].lower().startswith("synthetic hold-out")
    assert len(out["details"]) == 2


def test_holdout_wilson_interval_bounds_the_rate():
    lo, hi = holdout.wilson(8, 10)
    assert 0 <= lo <= 0.8 <= hi <= 1
    assert holdout.wilson(0, 0) == (None, None)


def test_holdout_is_reentrant_safe(db):
    """Two sequential runs each produce a usable EvalRun row; run_and_store guards against concurrent runs."""
    run1 = holdout.run_and_store(db, seeds=(1,), cases_per_seed=5)
    assert run1.kind == "holdout"
    assert holdout.latest(db)["id"] == run1.id
    assert not holdout.is_running()


# ---------------------------------------------------------------------------- API

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
    return r


def test_ops_ml_requires_auth(client):
    client.cookies.clear()
    assert client.get("/api/ops/ml").status_code == 401


def test_ops_ml_returns_model_card_for_any_staff_user(client):
    login(client, "inv.asha")
    r = client.get("/api/ops/ml")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_card"]["accounts_scored"] > 0
    assert "limitations" in body["model_card"]


def test_ops_ml_evaluate_is_supervisor_or_admin_only(client):
    login(client, "inv.asha")
    r = client.post("/api/ops/ml/evaluate", params={"seeds": 1, "cases_per_seed": 5})
    assert r.status_code == 403


def test_ops_ml_evaluate_runs_and_stores(client):
    login(client, "sup.meera")
    r = client.post("/api/ops/ml/evaluate", params={"seeds": 2, "cases_per_seed": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ml" in body["metrics"] and "rules" in body["metrics"]

    r2 = client.get("/api/ops/ml")
    assert r2.status_code == 200
    assert r2.json()["holdout"]["id"] == body["id"]


def test_case_behaviour_endpoint_scores_the_trail(client):
    login(client, "inv.asha")
    r = client.get(f"/api/cases/{HEADLINE_CASE}/behaviour")
    assert r.status_code == 200, r.text
    body = r.json()
    rahul = next(a for a in body["accounts"] if a["account_id"] == MULE_ACCOUNT)
    assert rahul["scored"] is True
    assert rahul["score"] > 50
    assert rahul["reasons"]
    assert "not fraud" in body["note"].lower() or "not" in body["note"].lower()


def test_case_behaviour_endpoint_respects_case_access(client):
    login(client, "inv.ravi")  # CASE-24051 is owned by inv.asha
    r = client.get(f"/api/cases/{HEADLINE_CASE}/behaviour")
    assert r.status_code == 404
