"""Versioned Gemini price table (USD per 1M tokens) used for cost accounting.

Values are list prices for standard (≤200K-token) context on Vertex AI, taken from the public
Vertex AI generative-AI pricing page. Thinking tokens are billed as output. Override at deploy time
with LLM_PRICE_OVERRIDES='{"model": {"input": x, "output": y}}' when prices change.
"""
from __future__ import annotations

import json

from app.config import get_settings

PRICE_TABLE_VERSION = "2026-10-17"
PRICE_SOURCE = "https://cloud.google.com/vertex-ai/generative-ai/pricing"

_BASE = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}


def table() -> dict[str, dict[str, float]]:
    t = dict(_BASE)
    raw = get_settings().llm_price_overrides
    if raw:
        try:
            t.update(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return t


def price_for(model: str) -> dict[str, float] | None:
    t = table()
    if model in t:
        return t[model]
    # tolerate version suffixes such as "-001" or "-preview-06-17"
    for k in sorted(t, key=len, reverse=True):
        if model.startswith(k):
            return t[k]
    return None


def cost_usd(model: str, input_tokens: int, output_tokens: int, thinking_tokens: int = 0) -> tuple[float, bool]:
    """Returns (cost, price_known)."""
    p = price_for(model)
    if p is None:
        return 0.0, False
    return round((input_tokens * p["input"] + (output_tokens + thinking_tokens) * p["output"]) / 1_000_000, 8), True
