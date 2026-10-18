"""Gemini gateway: the only place the application calls an LLM.

Guarantees for every call:
- bounded time (timeout), bounded spend (daily and per-case budget guard)
- structured output validated against a Pydantic schema; invalid output is a failure, not a guess
- model fallback chain from config (first model that answers is used); a model that is out of capacity
  (429 / 503) is retried once, then the next model is tried
- one `ai_calls` row with tokens, cost, latency, status and trace id
- failures return `ok=False` with a status; callers must then show "Not analysed"
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from app import models as m
from app.ai.pricing import cost_usd
from app.config import get_settings
from app.db import session_scope
from app.telemetry import current_trace_id, span

log = logging.getLogger("fundtrace.llm")

_BUSY = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "overloaded")


_LEVELS = {"minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
_BUDGETS_25 = {"minimal": 0, "low": 1024, "medium": 4096, "high": -1}  # Gemini 2.5 uses a token budget instead of a level


def _thinking_config(types, model: str, level: str | None):
    """How long the model may think. None leaves the model's own default."""
    level = (level or "").lower()
    if level not in _LEVELS:
        return None
    if model.startswith("gemini-2.5"):
        budget = _BUDGETS_25[level]
        if "pro" in model:
            budget = max(budget, 128) if budget >= 0 else budget  # 2.5 Pro cannot switch thinking off
        return types.ThinkingConfig(thinking_budget=budget)
    return types.ThinkingConfig(thinking_level=_LEVELS[level])


def _busy(msg: str) -> bool:
    """Vertex AI is out of capacity for this model right now (rate limit or overload), not a problem with the request."""
    return any(k in msg for k in _BUSY)


@dataclass
class LLMResult:
    ok: bool
    status: str  # ok | disabled | budget | timeout | error | invalid
    data: Any = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    avg_logprob: float | None = None
    error: str | None = None
    attempts: list[dict] = field(default_factory=list)

    @property
    def not_analysed_reason(self) -> str:
        return {
            "disabled": "AI is not configured for this environment",
            "budget": "AI budget limit reached",
            "timeout": "AI request timed out",
            "invalid": "AI returned output that failed validation",
            "error": "AI service error",
        }.get(self.status, self.status)


class Gateway(Protocol):
    def generate(self, *, node: str, prompt_version: str, contents: list, schema: type[BaseModel], tier: str = "fast",
                 system: str | None = None, temperature: float = 0.2, case_id: str | None = None,
                 run_id: str | None = None, db=None, timeout_s: float | None = None, thinking: str | None = None) -> LLMResult: ...


class CallBuffer:
    """Stands in for `db` when calls run on worker threads: rows are collected and the caller adds them to its
    own session afterwards (a session must not be shared between threads). `spend` is the (day, case) spend
    measured before the threads started, used for the budget guard."""

    def __init__(self, spend: tuple[float, float]):
        self.spend = spend
        self.rows: list[m.AICall] = []


def _record(res: LLMResult, node: str, prompt_version: str, case_id: str | None, run_id: str | None, db=None) -> None:
    log.info("ai_call", extra={"fields": {"event": "ai_call", "node": node, "model": res.model, "status": res.status,
                                          "input_tokens": res.input_tokens, "output_tokens": res.output_tokens + res.thinking_tokens,
                                          "cost_usd": res.cost_usd, "latency_ms": res.latency_ms, "prompt_version": prompt_version}})
    try:
        if isinstance(db, CallBuffer):
            db.rows.append(_call_row(res, node, prompt_version, case_id, run_id))
            return
        if db is not None:
            db.add(_call_row(res, node, prompt_version, case_id, run_id))
            db.flush()
            return
        with session_scope() as s:
            s.add(_call_row(res, node, prompt_version, case_id, run_id))
    except Exception as exc:  # telemetry must never break the request
        log.warning("could not record ai_call: %s", exc)


def _call_row(res: LLMResult, node: str, prompt_version: str, case_id: str | None, run_id: str | None) -> m.AICall:
    return (m.AICall(run_id=run_id, case_id=case_id, node=node, model=res.model or "-", prompt_version=prompt_version,
                            status=res.status, input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                            thinking_tokens=res.thinking_tokens, cost_usd=res.cost_usd, latency_ms=res.latency_ms,
                            avg_logprob=res.avg_logprob, trace_id=current_trace_id(), error=(res.error or "")[:500] or None))


def _spend(case_id: str | None, db=None) -> tuple[float, float]:
    if isinstance(db, CallBuffer):
        return db.spend
    if db is None:
        with session_scope() as s:
            return _spend(case_id, s)
    since = m.utcnow() - timedelta(days=1)
    day = db.scalar(select(func.coalesce(func.sum(m.AICall.cost_usd), 0.0)).where(m.AICall.created_at >= since)) or 0.0
    case = 0.0
    if case_id:
        case = db.scalar(select(func.coalesce(func.sum(m.AICall.cost_usd), 0.0)).where(m.AICall.case_id == case_id)) or 0.0
    return float(day), float(case)


class GeminiGateway:
    BUSY_RETRIES = 1  # one more try on the same model when it is out of capacity
    BUSY_BACKOFF_S = 2.0

    def __init__(self):
        self.s = get_settings()
        self._client = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.s.llm_enabled and self.s.gcp_project)

    def client(self):
        # One shared client. Without the lock, parallel calls on a fresh instance each built a client, and the ones
        # overwritten were closed while their requests were still in flight ("client has been closed").
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from google import genai

                    self._client = genai.Client(vertexai=True, project=self.s.gcp_project, location=self.s.gemini_location)
        return self._client

    def generate(self, *, node, prompt_version, contents, schema, tier="fast", system=None, temperature=0.2,
                 case_id=None, run_id=None, db=None, timeout_s=None, thinking=None) -> LLMResult:
        if not self.available():
            res = LLMResult(ok=False, status="disabled", error="LLM disabled or GCP project not set")
            _record(res, node, prompt_version, case_id, run_id, db)
            return res
        day, case = _spend(case_id, db)
        if day >= self.s.llm_daily_budget_usd or (case_id and case >= self.s.llm_case_budget_usd):
            res = LLMResult(ok=False, status="budget", error=f"budget reached (day ${day:.4f}, case ${case:.4f})")
            _record(res, node, prompt_version, case_id, run_id, db)
            return res

        from google.genai import types

        models = self.s.pro_models if tier == "pro" else self.s.fast_models
        timeout_s = timeout_s or (self.s.llm_pro_timeout_seconds if tier == "pro" else self.s.llm_timeout_seconds)
        level = thinking or (self.s.llm_thinking_pro if tier == "pro" else self.s.llm_thinking_fast)
        res = LLMResult(ok=False, status="error")
        done = False
        for model in models:
            think = _thinking_config(types, model, level)
            for attempt in range(2 + self.BUSY_RETRIES):  # one extra pass is reserved for dropping an unsupported thinking setting
                t0 = time.perf_counter()
                with span("gemini.generate", node=node, model=model, prompt_version=prompt_version, case_id=case_id) as sp:
                    try:
                        cfg = types.GenerateContentConfig(
                            system_instruction=system, temperature=temperature, response_mime_type="application/json",
                            response_schema=schema, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
                            **({"thinking_config": think} if think is not None else {}),
                        )
                        resp = self.client().models.generate_content(model=model, contents=contents, config=cfg)
                    except Exception as exc:
                        msg = f"{type(exc).__name__}: {exc}"[:400]
                        status = "timeout" if "timeout" in msg.lower() or "deadline" in msg.lower() else "error"
                        res = LLMResult(ok=False, status=status, model=model, error=msg, latency_ms=int((time.perf_counter() - t0) * 1000),
                                        attempts=res.attempts + [{"model": model, "status": status}])
                        sp.set_attribute("llm.status", status)
                        if think is not None and "thinking" in msg.lower() and ("400" in msg or "INVALID_ARGUMENT" in msg):
                            think = None
                            continue  # this model does not accept the thinking setting: ask again with its default
                        if "DEADLINE_EXCEEDED" in msg or "504" in msg:
                            break  # Vertex gave up on its side: the next model in the chain is the quickest way to an answer
                        if _busy(msg) and attempt >= self.BUSY_RETRIES:
                            break  # still busy after a retry: try the next model in the chain
                        if _busy(msg):
                            time.sleep(self.BUSY_BACKOFF_S * (attempt + 1) + random.uniform(0, 0.5))
                            continue  # out of capacity for a moment: try the same model once more
                        if "404" in msg or "not found" in msg.lower() or "NOT_FOUND" in msg:
                            break  # model unavailable: try the next model in the chain
                        if status == "timeout" and tier == "pro":
                            break  # a slow Pro model falls back to the next (faster) model in its chain
                        done = True  # anything else (bad request, fast-model timeout) is not retried
                        break
                    res = self._parse(resp, model, schema, t0, res.attempts)
                    sp.set_attribute("llm.status", res.status)
                    sp.set_attribute("llm.input_tokens", res.input_tokens)
                    sp.set_attribute("llm.output_tokens", res.output_tokens)
                    sp.set_attribute("llm.cost_usd", res.cost_usd)
                    done = True
                    break
            if done:
                break
        _record(res, node, prompt_version, case_id, run_id, db)
        return res

    def _parse(self, resp, model: str, schema: type[BaseModel], t0: float, attempts: list) -> LLMResult:
        um = getattr(resp, "usage_metadata", None)
        it = int(getattr(um, "prompt_token_count", 0) or 0)
        ot = int(getattr(um, "candidates_token_count", 0) or 0)
        tt = int(getattr(um, "thoughts_token_count", 0) or 0)
        cost, _ = cost_usd(model, it, ot, tt)
        cand = (getattr(resp, "candidates", None) or [None])[0]
        avg_lp = getattr(cand, "avg_logprobs", None) if cand is not None else None
        base = dict(model=model, input_tokens=it, output_tokens=ot, thinking_tokens=tt, cost_usd=cost,
                    latency_ms=int((time.perf_counter() - t0) * 1000), avg_logprob=avg_lp)
        try:
            parsed = getattr(resp, "parsed", None)
            if isinstance(parsed, schema):
                data = parsed
            else:
                data = schema.model_validate(json.loads(resp.text))
        except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return LLMResult(ok=False, status="invalid", error=f"schema validation failed: {str(exc)[:300]}", **base,
                             attempts=attempts + [{"model": model, "status": "invalid"}])
        return LLMResult(ok=True, status="ok", data=data, **base, attempts=attempts + [{"model": model, "status": "ok"}])


class FakeGateway:
    """Deterministic stand-in for tests: `responder(node, contents)` returns a dict, a model, or raises."""

    def __init__(self, responder: Callable[[str, list], Any], status: str = "ok"):
        self.responder = responder
        self.status = status
        self.calls: list[dict] = []

    def available(self) -> bool:
        return self.status == "ok"

    def generate(self, *, node, prompt_version, contents, schema, tier="fast", system=None, temperature=0.2,
                 case_id=None, run_id=None, db=None, timeout_s=None, thinking=None) -> LLMResult:
        self.calls.append({"node": node, "contents": contents, "system": system})
        if self.status != "ok":
            res = LLMResult(ok=False, status=self.status, model="fake", error="fake failure")
        else:
            try:
                out = self.responder(node, contents)
                data = out if isinstance(out, schema) else schema.model_validate(out)
                res = LLMResult(ok=True, status="ok", data=data, model="fake-gemini", input_tokens=1000, output_tokens=300,
                                cost_usd=0.001, latency_ms=5, avg_logprob=-0.05)
            except (ValidationError, ValueError, KeyError) as exc:
                res = LLMResult(ok=False, status="invalid", model="fake-gemini", error=str(exc)[:200])
        _record(res, node, prompt_version, case_id, run_id, db)
        return res


_gateway: Gateway | None = None


def get_gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = GeminiGateway()
    return _gateway


def set_gateway(g: Gateway | None) -> None:
    global _gateway
    _gateway = g
