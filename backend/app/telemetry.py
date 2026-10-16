"""Tracing (OpenTelemetry → Cloud Trace) and structured, redacted JSON logging (→ Cloud Logging)."""
from __future__ import annotations

import json
import logging
import re
import sys
from contextlib import contextmanager

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_tracer = otel_trace.get_tracer("fundtrace")
_project: str | None = None

_REDACTIONS = [
    (re.compile(r"\b\d{9,18}\b"), "[ACCOUNT]"),  # long digit runs (account / card / phone numbers)
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\b[\w.-]+@(?:ok\w+|upi|ybl|paytm|ibl|axl)\b", re.I), "[VPA]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
]


def redact(text: str) -> str:
    for rx, rep in _REDACTIONS:
        text = rx.sub(rep, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = redact(record.getMessage())
        out = {"severity": record.levelname, "message": msg, "logger": record.name}
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):  # structured fields become jsonPayload.* in Cloud Logging
            out.update({k: v for k, v in fields.items() if k not in out})
        tid = current_trace_id()
        if tid:
            out["trace_id"] = tid
            if _project:
                out["logging.googleapis.com/trace"] = f"projects/{_project}/traces/{tid}"
        if record.exc_info:
            out["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False)


def setup(exporter: str = "none", project: str | None = None, level: str = "INFO") -> None:
    global _tracer, _project
    _project = project
    provider = TracerProvider(resource=Resource.create({"service.name": "fundtrace-api"}))
    if exporter == "gcp":
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter  # type: ignore

            provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=project)))
        except Exception as exc:  # exporter not installed / no credentials: keep running, log it
            logging.getLogger("fundtrace").warning("Cloud Trace exporter unavailable: %s", exc)
    elif exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    otel_trace.set_tracer_provider(provider)
    _tracer = otel_trace.get_tracer("fundtrace")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def tracer():
    return _tracer


@contextmanager
def span(name: str, **attrs):
    with _tracer.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            if v is not None:
                sp.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else str(v))
        yield sp


def current_trace_id() -> str | None:
    ctx = otel_trace.get_current_span().get_span_context()
    if ctx and ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return None


def trace_url(trace_id: str | None) -> str | None:
    if not trace_id or not _project:
        return None
    return f"https://console.cloud.google.com/traces/list?project={_project}&tid={trace_id}"
