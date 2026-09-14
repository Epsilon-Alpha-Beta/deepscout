from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deepscout.api import rate_limit
from deepscout.api.app import create_app
from deepscout.config import get_settings


class FakeGraph:
    async def ainvoke(self, input_value, config):
        return {"final_report": "ok"}

    async def astream(self, input_value, config, *, stream_mode):
        yield {"writer": {"final_report": "ok"}}

    async def aget_state(self, config):
        return SimpleNamespace(next=(), values={"final_report": "ok"})


@pytest.fixture(autouse=True)
def reset_runtime_settings():
    get_settings.cache_clear()
    rate_limit._LIMITERS.clear()
    yield
    get_settings.cache_clear()
    rate_limit._LIMITERS.clear()


def test_api_key_auth_supports_header_and_bearer(monkeypatch):
    monkeypatch.setenv("DEEPSCOUT_API_KEY", "integration-secret")
    with TestClient(create_app(graph=FakeGraph())) as client:
        missing = client.post("/v1/research", json={"query": "x"})
        header = client.post(
            "/v1/research",
            json={"query": "x"},
            headers={"X-API-Key": "integration-secret"},
        )
        bearer = client.post(
            "/v1/research",
            json={"query": "x"},
            headers={"Authorization": "Bearer integration-secret"},
        )
    assert missing.status_code == 401
    assert header.status_code == 200
    assert bearer.status_code == 200


def test_rate_limit_returns_retry_after(monkeypatch):
    monkeypatch.setenv("DEEPSCOUT_API_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("DEEPSCOUT_API_RATE_LIMIT_WINDOW_SECONDS", "60")
    with TestClient(create_app(graph=FakeGraph())) as client:
        assert client.post("/v1/research", json={"query": "a"}).status_code == 200
        assert client.post("/v1/research", json={"query": "b"}).status_code == 200
        limited = client.post("/v1/research", json={"query": "c"})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_request_id_and_prometheus_metrics_are_exposed():
    with TestClient(create_app(graph=FakeGraph())) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "req-123"})
        metrics = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"
    assert metrics.status_code == 200
    assert "deepscout_http_requests_total" in metrics.text
    assert "deepscout_research_runs_total" in metrics.text


def test_metrics_requires_auth_when_service_is_protected(monkeypatch):
    name = "DEEPSCOUT_" + "API" + "_KEY"
    monkeypatch.setenv(name, "metrics-test-token")
    with TestClient(create_app(graph=FakeGraph())) as client:
        denied = client.get("/metrics")
        allowed = client.get("/metrics", headers={"X-API-Key": "metrics-test-token"})
    assert denied.status_code == 401
    assert allowed.status_code == 200
