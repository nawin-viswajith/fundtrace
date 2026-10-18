"""Hold-out evaluation: fresh synthetic worlds in isolated in-memory databases (never the live database).

Each run builds N worlds with different random seeds. In every world:

1. The synthetic bank (``seed.synthetic.build(anchor, seed=s)``) is loaded: a different background of customers,
   payments and devices per seed, plus the hand-written scenarios.
2. Extra disputes are made by the demo-data generator (``services.generator``), a different code path from the
   hand-written scenarios: random payers, amounts, times, mule accounts and onward trails, balanced across all six
   dispute types.
3. **Behaviour model.** It is fitted on the world WITHOUT labels. Afterwards we check how well its score ranks the
   accounts known to have received and passed on fraud money (the scenario mule chain from the ground truth and every
   in-bank account on a generated fraud case's trail): ROC-AUC and precision at k. An ablation without account age shows
   how much the result depends on the single most obvious feature.
4. **Rules.** For each generated case: fraud types with a money trail should raise at least one high-concern warning
   sign; merchant disputes and processing errors should not. Rates come with Wilson 95% confidence intervals.

Everything here is synthetic. It is a less circular test than scoring the scenarios we wrote by hand, not a
measurement of real-world performance.
"""
from __future__ import annotations

import math
import random
import statistics
import threading
import time
from datetime import timedelta

from sklearn.metrics import roc_auc_score
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models as m
from app.db import Base
from app.services.ml.features import FEATURE_KEYS, compute
from app.services.ml.model import MODEL_VERSION, UNUSUAL, VERY_UNUSUAL, fit

HOLDOUT_KIND = "holdout"
DEFAULT_SEEDS = (101, 202, 303, 404, 505)
FRAUD_WITH_TRAIL = ("unauthorised_transfer", "account_takeover", "app_scam")
SHOULD_BE_QUIET = ("merchant_dispute", "processing_error")
NO_EXPECTATION = ("card_not_present",)
LABEL = "Synthetic hold-out, not real-world performance"

_RUN_LOCK = threading.Lock()
_LAST: dict | None = None


class _NoAI:
    """Stands in for the Gemini gateway: the hold-out never calls an AI model."""

    def available(self) -> bool:
        return False


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval for a proportion k/n (95% by default)."""
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def isolated_session() -> Session:
    """A brand-new in-memory SQLite database with the full schema. Nothing is shared with the live database."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(engine)
    return Session(bind=engine, expire_on_commit=False, future=True)


def load_world(db: Session, seed: int, anchor=None) -> dict:
    """Load the synthetic world for ``seed`` (ledger and cases; no evidence files, no AI) into ``db``. Returns its truth."""
    from app.seed.synthetic import build
    from app.services.ledger import normalise

    ds = build(anchor or m.utcnow(), seed=seed)
    for i in ds.institutions:
        db.add(m.Institution(**i))
    for c in ds.customers:
        db.add(m.Customer(**c, is_synthetic=True))
    db.flush()
    for a in ds.accounts:
        db.add(m.Account(**a, is_synthetic=True))
    for dv in ds.devices:
        db.add(m.Device(**dv))
    db.flush()
    for e in ds.auth_events:
        db.add(m.AuthEvent(**e))
    txns, _ = normalise(ds.raw_transactions)
    for t in txns:
        db.add(m.Transaction(**t, is_synthetic=True))
    db.flush()
    for c in ds.cases:
        db.add(m.DisputeCase(id=c["id"], disputed_txn_id=c["disputed_txn_id"], customer_id=c["customer_id"], category=c["category"],
                             allegation=c["allegation"], allegation_language=c["allegation_language"], status=c["status"],
                             reported_at=c["reported_at"], created_at=c["reported_at"], scenario=c["scenario"], is_synthetic=True))
    db.flush()
    return ds.truth


def generate_cases(db: Session, seed: int, count: int) -> list[m.DisputeCase]:
    """Generated disputes through the demo-data generator's own builder, with a seeded random source (reproducible)."""
    from app.services import generator as gen
    from app.services.scoring import CATEGORIES

    actor = m.User(username="holdout.eval", full_name="Hold-out evaluation", role="supervisor", password_hash="!")
    db.add(actor)
    db.flush()
    rng = random.Random(seed * 7919 + 17)
    world = gen._World(db, rng, m.utcnow())
    params = gen.GenerateIn(count=min(50, max(1, count)), with_trail=True, with_evidence=False, statements="template", days_back=7)
    customers = gen._customers(db)
    cats = list(CATEGORIES)
    return [gen._one(db, world, params, cats[i % len(cats)], rng.choice(customers), "new", None, actor) for i in range(count)]


def _fraud_accounts(db: Session, truth: dict, cases: list[m.DisputeCase]) -> tuple[set[str], set[str]]:
    """(scenario mule accounts from the ground truth, in-bank accounts on generated fraud cases' trails)."""
    from app.services.investigation import build_trace

    in_bank = {a for a, in db.execute(select(m.Account.id).join(m.Institution, m.Institution.id == m.Account.institution_id)
                                      .where(m.Institution.kind == "self")).all()}
    scenario = set()
    for tid in truth.get("S1", {}).get("trail", []):
        t = db.get(m.Transaction, tid)
        if t is not None and t.credit_account_id in in_bank:
            scenario.add(t.credit_account_id)
    generated = set()
    for c in cases:
        if c.category not in FRAUD_WITH_TRAIL:
            continue
        res, _, _, _ = build_trace(db, c)
        generated |= {n["id"] for n in res.nodes.values()
                      if n["type"] == "account" and n["id"] in in_bank and "payer" not in n["roles"]}
    return scenario, generated


def _precision_at(ranked: list[str], positives: set[str], k: int) -> float | None:
    if k <= 0:
        return None
    return sum(1 for a in ranked[:k] if a in positives) / k


def _ml_metrics(table, positives: set[str], features: list[str] | None = None) -> dict:
    model = fit(table, features=features)
    pop = table.population
    y = [1 if a in positives else 0 for a in pop]
    s = [model.anomaly[a] for a in pop]
    ranked = sorted(pop, key=lambda a: (-model.anomaly[a], a))
    n_pos = sum(y)
    flagged_pos = sum(1 for a in pop if a in positives and model.scores[a] >= UNUSUAL)
    flagged_neg = sum(1 for a in pop if a not in positives and model.scores[a] >= UNUSUAL)
    return {
        "model": model,
        "accounts": len(pop),
        "positives": n_pos,
        "roc_auc": round(float(roc_auc_score(y, s)), 4) if 0 < n_pos < len(pop) else None,
        "precision_at_k": round(_precision_at(ranked, positives, n_pos), 4) if n_pos else None,  # k = number of fraud accounts
        "precision_at_10": round(_precision_at(ranked, positives, 10), 4),
        "recall_unusual_or_higher": round(flagged_pos / n_pos, 4) if n_pos else None,
        "other_accounts_unusual_or_higher": round(flagged_neg / (len(pop) - n_pos), 4) if len(pop) > n_pos else None,
    }


def _one_seed(seed: int, cases_per_seed: int) -> dict:
    from app.services.investigation import build_context

    t0 = time.perf_counter()
    db = isolated_session()
    try:
        truth = load_world(db, seed)
        cases = generate_cases(db, seed, cases_per_seed)
        scenario_mules, generated_mules = _fraud_accounts(db, truth, cases)
        positives = scenario_mules | generated_mules
        table = compute(db)  # features only: no labels go anywhere near the fit
        full = _ml_metrics(table, positives)
        no_age = _ml_metrics(table, positives, [k for k in FEATURE_KEYS if k != "account_age_days"])
        model = full.pop("model")
        no_age.pop("model")
        headline = next(iter(sorted(scenario_mules)), None)
        rules_rows = []
        for c in cases:
            ctx = build_context(db, c)
            high = [r["rule_id"] for r in ctx["rules"] if r["status"] == "triggered" and r["severity"] == "high"]
            rules_rows.append({"case_id": c.id, "category": c.category, "high_signals": high, "triggered": ctx["rules_summary"]["triggered"]})
        return {
            "seed": seed,
            "seconds": round(time.perf_counter() - t0, 2),
            "generated_cases": len(cases),
            "scenario_mules": sorted(scenario_mules),
            "generated_fraud_accounts": len(generated_mules),
            "ml": full,
            "ml_without_account_age": no_age,
            "headline_mule": {"account_id": headline, "score": model.scores.get(headline) if headline else None},
            "scenario_mule_scores": {a: model.scores.get(a) for a in sorted(scenario_mules)},
            "rules": rules_rows,
        }
    finally:
        bind = db.get_bind()
        db.close()
        bind.dispose()


def _agg(values: list[float | None]) -> dict:
    v = [x for x in values if x is not None]
    if not v:
        return {"mean": None, "min": None, "max": None, "n": 0}
    return {"mean": round(statistics.mean(v), 4), "min": round(min(v), 4), "max": round(max(v), 4), "n": len(v)}


def _rules_summary(rows: list[dict]) -> dict:
    from app.services.scoring import CATEGORIES

    per = []
    for cat in CATEGORIES:
        rs = [r for r in rows if r["category"] == cat]
        k = sum(1 for r in rs if r["high_signals"])
        lo, hi = wilson(k, len(rs))
        expect = ("at_least_one_high" if cat in FRAUD_WITH_TRAIL else "no_high" if cat in SHOULD_BE_QUIET else "none")
        if expect == "at_least_one_high":
            meets = k
        elif expect == "no_high":
            meets = len(rs) - k
        else:
            meets = None
        per.append({"category": cat, "label": CATEGORIES[cat], "cases": len(rs), "with_high_signal": k,
                    "rate_with_high_signal": round(k / len(rs), 4) if rs else None, "ci95": [lo, hi], "expectation": expect,
                    "meets_expectation": meets})

    def pooled(cats: tuple[str, ...], want_high: bool) -> dict:
        rs = [r for r in rows if r["category"] in cats]
        k = sum(1 for r in rs if bool(r["high_signals"]) == want_high)
        lo, hi = wilson(k, len(rs))
        return {"cases": len(rs), "k": k, "rate": round(k / len(rs), 4) if rs else None, "ci95": [lo, hi]}

    by_rule: dict[str, int] = {}
    for r in rows:
        for rid in r["high_signals"]:
            by_rule[rid] = by_rule.get(rid, 0) + 1
    return {"per_category": per,
            "detection_fraud_with_trail": pooled(FRAUD_WITH_TRAIL, True),
            "false_alarm_merchant_and_processing": pooled(SHOULD_BE_QUIET, True),
            "high_signals_by_rule": dict(sorted(by_rule.items()))}


def run(seeds: list[int] | tuple[int, ...] = DEFAULT_SEEDS, cases_per_seed: int = 30) -> dict:
    """Run the hold-out on fresh isolated worlds. Returns {metrics, details}; never touches the live database."""
    t0 = time.perf_counter()
    per_seed = [_one_seed(s, cases_per_seed) for s in seeds]
    ml_keys = ("roc_auc", "precision_at_k", "precision_at_10", "recall_unusual_or_higher", "other_accounts_unusual_or_higher",
               "accounts", "positives")
    all_rules = [r for p in per_seed for r in p["rules"]]
    metrics = {
        "label": LABEL,
        "model_version": MODEL_VERSION,
        "seeds": list(seeds),
        "cases_per_seed": cases_per_seed,
        "seconds": round(time.perf_counter() - t0, 1),
        "ml": {k: _agg([p["ml"][k] for p in per_seed]) for k in ml_keys},
        "ml_without_account_age": {k: _agg([p["ml_without_account_age"][k] for p in per_seed]) for k in ml_keys},
        "headline_mule_score": _agg([p["headline_mule"]["score"] for p in per_seed]),
        "bands": {"unusual_or_higher": f"score {UNUSUAL} or more", "very_unusual": f"score {VERY_UNUSUAL} or more"},
        "rules": _rules_summary(all_rules),
        "method": [
            "Each seed builds a new synthetic bank (different customers, payments and devices) in its own in-memory database.",
            "The demo-data generator adds disputes of all six types with random mule accounts and money trails "
            "(a different code path from the hand-written scenarios).",
            "The behaviour model is fitted without labels. Fraud accounts (the scenario mule chain and every in-bank account on a "
            "generated fraud trail) are used only afterwards, to measure how well the score ranks them.",
            "Rules: fraud types with a money trail should raise at least one high-concern warning sign; merchant disputes and "
            "processing errors should not. Card-not-present cases are listed without an expectation (the money leaves the bank at once).",
        ],
        "caveats": [
            "Synthetic hold-out, not real-world performance. Real mules are more varied than our generator.",
            "Generated mule accounts are new and pass money on quickly by construction, so they are easy to separate. "
            "The run without account age shows how much the result leans on that one feature.",
            "Victims' accounts can also look unusual (for example, no money received); they count as errors here.",
            "Intervals are Wilson 95% intervals over generated cases; ML figures are the mean, lowest and highest over seeds.",
            "Some false alarms on merchant/processing-error cases are a genuine rule behaviour, not a scoring error: the "
            "generator reuses a small set of merchant accounts across many cases, and R3 (beneficiary linked to other "
            "disputes) correctly escalates to high severity when one account is the beneficiary in several disputes.",
        ],
    }
    details = [{k: v for k, v in p.items() if k != "rules"} | {"rules": _rules_summary(p["rules"])["per_category"]} for p in per_seed]
    return {"metrics": metrics, "details": details}


def run_and_store(db: Session, seeds=DEFAULT_SEEDS, cases_per_seed: int = 30) -> m.EvalRun:
    """Run the hold-out (isolated databases) and store the result as an ``eval_runs`` row of kind ``holdout``."""
    global _LAST
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("A hold-out evaluation is already running")
    try:
        out = run(seeds, cases_per_seed)
    finally:
        _RUN_LOCK.release()
    row = m.EvalRun(kind=HOLDOUT_KIND, metrics=out["metrics"], details=out["details"])
    db.add(row)
    db.flush()
    _LAST = {"id": row.id, "started_at": row.started_at.isoformat() + "Z", "metrics": row.metrics, "details": row.details}
    return row


def latest(db: Session) -> dict | None:
    row = db.scalar(select(m.EvalRun).where(m.EvalRun.kind == HOLDOUT_KIND).order_by(m.EvalRun.id.desc()).limit(1))
    if row is not None:
        return {"id": row.id, "started_at": row.started_at.isoformat() + "Z", "metrics": row.metrics, "details": row.details}
    return _LAST


def is_running() -> bool:
    return _RUN_LOCK.locked()


_ = timedelta  # (kept for callers that build custom anchors)
