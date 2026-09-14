"""OpenTelemetry tracer provider construction."""

from __future__ import annotations

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)

from deepscout import __version__
from deepscout.config import get_settings


def build_tracer_provider(*, exporter: SpanExporter | None = None) -> TracerProvider | None:
    """Build an app-scoped provider; OTLP settings follow standard OTEL env vars."""

    settings = get_settings()
    if not settings.otel_enabled and exporter is None:
        return None

    provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: settings.otel_service_name,
                SERVICE_VERSION: __version__,
            }
        )
    )
    if exporter is None:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider
