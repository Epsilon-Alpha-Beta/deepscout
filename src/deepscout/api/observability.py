"""HTTP metrics, request IDs, tracing and structured access logging."""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

_LOGGER = logging.getLogger("deepscout.api")

HTTP_REQUESTS = Counter(
    "deepscout_http_requests_total",
    "DeepScout HTTP requests.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "deepscout_http_request_duration_seconds",
    "DeepScout HTTP request latency.",
    ("method", "route"),
)
HTTP_ACTIVE = Gauge("deepscout_http_requests_active", "Active DeepScout HTTP requests.")
RESEARCH_RUNS = Counter(
    "deepscout_research_runs_total",
    "DeepScout research API outcomes.",
    ("status",),
)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach request IDs and collect Prometheus + OpenTelemetry telemetry."""

    def __init__(self, app, tracer_provider: TracerProvider | None = None):
        super().__init__(app)
        provider = tracer_provider or trace.get_tracer_provider()
        self._tracer = provider.get_tracer("deepscout.api")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        HTTP_ACTIVE.inc()
        span_name = f"HTTP {request.method} {request.url.path}"
        with self._tracer.start_as_current_span(span_name, kind=SpanKind.SERVER) as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("deepscout.request_id", request_id)
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["X-Request-ID"] = request_id
                if status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                return response
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                elapsed = time.perf_counter() - started
                HTTP_ACTIVE.dec()
                route = getattr(request.scope.get("route"), "path", request.url.path)
                span.update_name(f"HTTP {request.method} {route}")
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status_code)
                HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
                HTTP_DURATION.labels(request.method, route).observe(elapsed)
                _LOGGER.info(
                    json.dumps(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "method": request.method,
                            "route": route,
                            "status": status_code,
                            "duration_ms": round(elapsed * 1000, 3),
                        },
                        ensure_ascii=False,
                    )
                )


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
