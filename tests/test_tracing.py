from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from deepscout.api.app import create_app
from deepscout.api.tracing import build_tracer_provider


class FakeGraph:
    pass


def test_http_request_emits_opentelemetry_span():
    exporter = InMemorySpanExporter()
    provider = build_tracer_provider(exporter=exporter)
    assert provider is not None

    with TestClient(create_app(graph=FakeGraph(), tracer_provider=provider)) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "otel-test"})

    provider.force_flush()
    spans = exporter.get_finished_spans()
    assert response.status_code == 200
    assert spans
    span = spans[-1]
    assert span.name == "HTTP GET /healthz"
    assert span.attributes["deepscout.request_id"] == "otel-test"
    assert span.attributes["http.response.status_code"] == 200
