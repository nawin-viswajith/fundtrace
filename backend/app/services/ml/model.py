"""Behaviour model: IsolationForest over per-account behaviour features (unsupervised; no labels are used).

Score (0-100): the account's percentile among the bank's scored personal accounts by isolation-forest anomaly
score, i.e. "more unusual than N% of the bank's other accounts". Bands are relative: the top 5% (the model's
contamination setting) are "very unusual", the next 15% "unusual", the rest "typical".

Reasons: for each feature, a robust z-score (distance from the bank's median in units of the median absolute
deviation, on the same log/raw scale the model uses). The three features furthest from typical (|z| >= 2) are
shown in plain words with the account's value, the bank's typical (median) value and a percentile. This is an
honest, approximate explanation of *what is unusual*, not the forest's exact internal logic.

The fitted model is cached in memory per data fingerprint (ledger counts and latest timestamps), so it refits
only when the ledger changes. Fitting is deterministic (fixed random_state, accounts sorted by id).
"""
from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.services.graph_store import EFFECTIVE_STATUSES
from app.services.ml.features import (FEATURE_BY_KEY, FEATURE_KEYS, FEATURES, NO_OUTFLOW_MINUTES, WINDOW_DAYS, FeatureTable,
                                      compute)
from app.services.trace import fmt_amount

MODEL_VERSION = "behaviour-iforest-v1"
N_ESTIMATORS = 200
CONTAMINATION = 0.05
RANDOM_STATE = 2026
MIN_ACCOUNTS = 20
VERY_UNUSUAL, UNUSUAL = 95, 80  # score thresholds (percentiles)
REASON_MIN_Z = 2.0
BAND_LABELS = {"very_unusual": "Very unusual", "unusual": "Unusual", "typical": "Typical"}
# (word when the account's value is higher than typical, word when lower)
DIRECTION_WORDS = {"account_age_days": ("older", "newer"), "minutes_to_next_out": ("slower", "faster")}

LIMITATIONS = [
    "Unusual is not fraud. A new salary account, a customer who moved house or a small business run from a personal "
    "account can all look unusual. Use the score to decide where to look first, never as a finding.",
    "No labels are used: the model has never been told which accounts are mules. It learns only what is common in "
    "this bank's own data.",
    "The features were chosen by the team with known money-mule behaviour in mind (new accounts, money passed on "
    "quickly, shared devices). That design choice, not training labels, is where expert knowledge enters.",
    "Trained and tested only on synthetic demo data. Real-world performance is unknown.",
    "Scores are relative to this bank's other personal accounts at this moment, so they change as the ledger changes.",
    "Reasons explain the score approximately (how far each measure is from the bank's typical value), not the "
    "model's exact internal logic.",
    "Merchant accounts and high-activity business accounts are not scored, and activity at other banks is invisible.",
    "The score never changes warning signs, priority, holds or any decision. It is shown beside them.",
]


@dataclass
class FittedModel:
    status: str  # ok | not_enough_data
    fingerprint: str
    trained_at: datetime
    table: FeatureTable
    features: list[str]
    fit_seconds: float = 0.0
    medians: dict[str, float] = field(default_factory=dict)  # raw scale, for display
    t_medians: dict[str, float] = field(default_factory=dict)  # transformed scale
    t_scales: dict[str, float] = field(default_factory=dict)
    raw: dict[str, np.ndarray] = field(default_factory=dict)  # feature -> population values (raw, imputed)
    anomaly: dict[str, float] = field(default_factory=dict)  # account -> anomaly score (higher = more unusual)
    scores: dict[str, int] = field(default_factory=dict)  # account -> 0..100 percentile
    flagged: dict[str, bool] = field(default_factory=dict)  # IsolationForest.predict == -1


def _t(key: str, v: float) -> float:
    return math.log1p(max(0.0, v)) if FEATURE_BY_KEY[key].transform == "log" else float(v)


def fingerprint(db: Session) -> str:
    """Cheap summary of the ledger: changes whenever records are added or changed in a way the features can see."""
    t = db.execute(select(func.count(m.Transaction.id), func.max(m.Transaction.occurred_at), func.max(m.Transaction.ingested_at),
                          func.sum(m.Transaction.amount_minor))).one()
    eff = db.scalar(select(func.count(m.Transaction.id)).where(m.Transaction.status.in_(EFFECTIVE_STATUSES)))
    a = db.execute(select(func.count(m.AuthEvent.id), func.max(m.AuthEvent.occurred_at))).one()
    acc = db.execute(select(func.count(m.Account.id), func.max(m.Account.opened_at))).one()
    kinds = db.scalar(select(func.count(m.Account.id)).where(m.Account.kind == "merchant"))
    parts = [MODEL_VERSION, get_settings().trace_hub_threshold, *t, eff, *a, *acc, kinds]
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def fit(table: FeatureTable, features: list[str] | None = None, random_state: int = RANDOM_STATE, fp: str = "") -> FittedModel:
    """Fit on all scored accounts in ``table``. Deterministic for the same table."""
    t0 = time.perf_counter()
    keys = list(features or FEATURE_KEYS)
    pop = table.population
    model = FittedModel(status="ok", fingerprint=fp, trained_at=m.utcnow(), table=table, features=keys)
    if len(pop) < MIN_ACCOUNTS:
        model.status = "not_enough_data"
        return model
    cols = []
    for k in keys:
        known = [table.values[a][k] for a in pop if table.values[a][k] is not None]
        med = float(np.median(known)) if known else 0.0
        vals = np.array([table.values[a][k] if table.values[a][k] is not None else med for a in pop], dtype=float)
        tv = np.array([_t(k, v) for v in vals])
        t_med = float(np.median(tv))
        mad = 1.4826 * float(np.median(np.abs(tv - t_med)))
        q75, q25 = np.percentile(tv, [75, 25])
        model.medians[k], model.t_medians[k] = med, t_med
        model.t_scales[k] = max(mad, float(q75 - q25) / 1.349, FEATURE_BY_KEY[k].scale_floor)
        model.raw[k] = vals
        cols.append(tv)
    x = np.column_stack(cols)
    forest = IsolationForest(n_estimators=N_ESTIMATORS, contamination=CONTAMINATION, random_state=random_state, max_samples="auto")
    forest.fit(x)
    anomaly = -forest.score_samples(x)
    flagged = forest.predict(x) == -1
    n = len(pop)
    for i, a in enumerate(pop):
        below = int(np.sum(anomaly < anomaly[i]))
        ties = int(np.sum(anomaly == anomaly[i])) - 1
        model.anomaly[a] = float(anomaly[i])
        model.scores[a] = int(round(100 * (below + 0.5 * ties) / (n - 1)))
        model.flagged[a] = bool(flagged[i])
    model.fit_seconds = round(time.perf_counter() - t0, 3)
    return model


_CACHE: dict[str, FittedModel] = {}
_LOCK = threading.Lock()


def get_model(db: Session) -> FittedModel:
    """The model for the current ledger, fitted once per data fingerprint and kept in memory."""
    fp = fingerprint(db)
    with _LOCK:
        hit = _CACHE.get(fp)
        if hit is not None:
            return hit
        model = fit(compute(db), fp=fp)
        _CACHE.clear()  # one ledger per process: keep only the current fit
        _CACHE[fp] = model
        return model


# ---------------------------------------------------------------------------- explanations

def band(score: int) -> str:
    return "very_unusual" if score >= VERY_UNUSUAL else "unusual" if score >= UNUSUAL else "typical"


def fmt_value(key: str, v: float | None) -> str:
    if v is None:
        return "unknown"
    unit = FEATURE_BY_KEY[key].unit
    if unit == "money":
        return fmt_amount(int(round(v)), "INR")
    if unit == "share":
        return f"{round(100 * v)}%"
    if unit == "days":
        return "less than a day" if v < 1 else f"{int(v):,} day{'s' if int(v) != 1 else ''}"
    if unit == "minutes":
        if v >= NO_OUTFLOW_MINUTES:
            return "nothing went out afterwards"
        if v < 60:
            return f"{max(0, round(v))} min"
        if v < 48 * 60:
            return f"{v / 60:.1f} hours"
        return f"{v / 1440:.0f} days"
    return f"{int(round(v)):,}"


def _feature_rows(model: FittedModel, acct: str) -> list[dict]:
    rows = []
    vals = model.table.values[acct]
    for k in model.features:
        fd = FEATURE_BY_KEY[k]
        v = vals.get(k)
        row = {"key": k, "label": fd.label, "description": fd.description, "value": v, "value_text": fmt_value(k, v),
               "typical": model.medians[k], "typical_text": fmt_value(k, model.medians[k]), "z": None, "direction": None,
               "percentile_text": None}
        if v is not None:
            z = (_t(k, v) - model.t_medians[k]) / model.t_scales[k]
            pop = model.raw[k]
            higher, lower = DIRECTION_WORDS.get(k, ("higher", "lower"))
            if z > 0:
                share = float(np.mean(pop < v))
                row["percentile_text"] = f"{higher} than {round(100 * share)}% of accounts"
            elif z < 0:
                share = float(np.mean(pop > v))
                row["percentile_text"] = f"{lower} than {round(100 * share)}% of accounts"
            row["z"] = round(z, 2)
            row["direction"] = "higher" if z > 0 else "lower" if z < 0 else "same"
        rows.append(row)
    return rows


def explain(model: FittedModel, acct: str) -> list[dict]:
    """Up to three features furthest from the bank's typical value (|z| >= 2), in plain words."""
    rows = [r for r in _feature_rows(model, acct) if r["z"] is not None and abs(r["z"]) >= REASON_MIN_Z]
    rows.sort(key=lambda r: (-abs(r["z"]), FEATURE_KEYS.index(r["key"])))
    out = []
    for r in rows[:3]:
        out.append({**r, "text": f"{r['label']}: {r['value_text']}, {r['percentile_text']} (typical: {r['typical_text']})."})
    return out


def score_account(model: FittedModel, acct: str, external: bool = False) -> dict:
    base = {"account_id": acct, "scored": False, "score": None, "band": None, "band_label": None, "reasons": [], "features": [],
            "not_scored_reason": None}
    if external:
        return {**base, "not_scored_reason": "At another bank: only the payments that touch this bank are visible, so it is not scored."}
    if model.status != "ok":
        return {**base, "not_scored_reason": "Not enough accounts in the ledger to compare behaviour."}
    if acct not in model.table.values:
        return {**base, "not_scored_reason": "No ledger records for this account."}
    if acct in model.table.not_scored:
        return {**base, "not_scored_reason": model.table.not_scored[acct], "features": _feature_rows(model, acct)}
    s = model.scores[acct]
    b = band(s)
    reasons = explain(model, acct)
    return {**base, "scored": True, "score": s, "band": b, "band_label": BAND_LABELS[b], "anomaly_score": round(model.anomaly[acct], 4),
            "reasons": reasons, "features": _feature_rows(model, acct),
            "summary": f"More unusual than {s}% of the bank's other personal accounts.",
            "no_single_reason": not reasons}


def score_accounts(db: Session, account_ids: list[str]) -> tuple[FittedModel, dict[str, dict]]:
    model = get_model(db)
    ext = {a for a, in db.execute(select(m.Account.id).join(m.Institution, m.Institution.id == m.Account.institution_id)
                                  .where(m.Account.id.in_(account_ids), m.Institution.kind != "self")).all()}
    return model, {a: score_account(model, a, external=a in ext) for a in account_ids}


def model_brief(model: FittedModel) -> dict:
    return {"version": MODEL_VERSION, "status": model.status, "trained_at": model.trained_at.isoformat() + "Z",
            "data_as_of": model.table.as_of.isoformat() + "Z", "window_days": WINDOW_DAYS, "accounts_scored": len(model.table.population),
            "fingerprint": model.fingerprint,
            "bands": {"very_unusual": f"score {VERY_UNUSUAL} or more (top {100 - VERY_UNUSUAL}%)",
                      "unusual": f"score {UNUSUAL}–{VERY_UNUSUAL - 1}", "typical": f"score below {UNUSUAL}"}}


def model_card(model: FittedModel) -> dict:
    not_scored = model.table.not_scored.values()
    return {
        **model_brief(model),
        "name": "Behaviour model",
        "type": f"Isolation Forest (scikit-learn {sklearn.__version__}), unsupervised anomaly detection",
        "question": "How unlike the bank's other personal accounts does this account behave?",
        "training": "Fitted on every in-bank personal account in the ledger. No labels are used; nothing tells the model which "
                    "accounts are mules or victims.",
        "fit_seconds": model.fit_seconds,
        "accounts_not_scored": {"merchant": sum(1 for r in not_scored if r.startswith("Merchant")),
                                "high_activity": sum(1 for r in not_scored if r.startswith("High-activity"))},
        "settings": {"n_estimators": N_ESTIMATORS, "contamination": CONTAMINATION, "random_state": RANDOM_STATE,
                     "max_samples": "auto (up to 256 accounts per tree)", "window_days": WINDOW_DAYS,
                     "high_activity_threshold": model.table.hub_threshold},
        "contamination_note": f"Contamination {CONTAMINATION} means the model expects about {round(CONTAMINATION * 100)}% of accounts "
                              "to stand out. It is a setting, not an estimate of how many accounts are fraudulent.",
        "features": [{"key": f.key, "label": f.label, "description": f.description,
                      "typical": fmt_value(f.key, model.medians.get(f.key)) if model.status == "ok" else None} for f in FEATURES],
        "how_scores_work": "Each account is isolated by many random splits on its measures; accounts that are isolated quickly are "
                           "unlike the rest. The score is the account's percentile: 97 means more unusual than 97% of the bank's "
                           "other personal accounts.",
        "how_reasons_work": "Reasons list the measures where the account is furthest from the bank's typical (median) value, "
                            "measured in robust spread units (median absolute deviation). At most three are shown, and only "
                            "measures at least 2 units from typical.",
        "intended_use": "Helps an investigator decide which accounts on a money trail to look at first. Not a fraud verdict and "
                        "not an input to warning signs, priority or decisions.",
        "limitations": LIMITATIONS,
    }
