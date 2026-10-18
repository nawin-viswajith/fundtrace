"""Behaviour model: an unsupervised (no labels) machine-learning signal about how each account behaves.

It answers one question: *how unlike the bank's other personal accounts does this account behave?*
It is a separate signal shown beside the rules. It never changes rule results, priority, scores or the
evaluation ground truth, and "unusual" is never treated as "fraud".

- ``features``  per-account behaviour measures computed from the ledger (90-day window)
- ``model``     IsolationForest fit, cached per data fingerprint; scores, bands, plain-language reasons, model card
- ``holdout``   evaluation on fresh synthetic worlds in isolated in-memory databases (never the live DB)
"""
from app.services.ml.model import MODEL_VERSION, get_model, model_card, score_accounts  # noqa: F401
