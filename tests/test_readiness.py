import pytest
from fastapi.testclient import TestClient

from deepscout.api.app import create_app
from deepscout.api.rate_limit import close_rate_limiters, rate_limit_readiness
from deepscout.config import get_settings


class FakeGraph:
    pass


def test_readyz_succeeds_with_default_limiter():
    with TestClient(create_app(graph=FakeGraph())) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_readyz_dependency_probe_detects_unavailable_redis(monkeypatch):
    monkeypatch.setenv("DEEPSCOUT_API_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("DEEPSCOUT_API_RATE_LIMIT_REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("DEEPSCOUT_API_RATE_LIMIT_REDIS_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()
    try:
        ready, backend = await rate_limit_readiness()
        assert ready is False
        assert backend == "redis_unavailable"
    finally:
        await close_rate_limiters()
        get_settings.cache_clear()
