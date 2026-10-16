"""OpenTelemetry tracing + Prometheus metrics (both optional)."""

from __future__ import annotations

from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.core.config import get_settings

HTTP_REQUESTS = Counter("opspilot_http_requests_total", "HTTP requests", ["method", "path", "status"])
HTTP_LATENCY = Histogram("opspilot_http_request_seconds", "HTTP latency", ["method", "path"])
WORKFLOW_RUNS = Counter("opspilot_workflow_runs_total", "Workflow runs by final status", ["status"])
AGENT_RUNS = Counter("opspilot_agent_runs_total", "Agent runs", ["agent", "status"])
LLM_TOKENS = Counter("opspilot_llm_tokens_total", "LLM tokens", ["model", "kind"])
TOOL_CALLS = Counter("opspilot_tool_calls_total", "Tool executions", ["tool", "mode", "status"])


def setup_tracing(app: Any) -> bool:
    s = get_settings()
    if not s.otel_enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": s.otel_service_name}))
        exporter = OTLPSpanExporter(endpoint=s.otel_exporter_otlp_endpoint) if s.otel_exporter_otlp_endpoint else OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        return True
    except Exception:  # pragma: no cover - optional dependency problems must not break startup
        return False


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
