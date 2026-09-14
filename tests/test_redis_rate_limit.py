import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from deepscout.api.rate_limit import RedisSlidingWindowLimiter

_REDIS_URL = os.getenv("DEEPSCOUT_TEST_REDIS_URL")


@pytest.mark.skipif(not _REDIS_URL, reason="DEEPSCOUT_TEST_REDIS_URL not configured")
@pytest.mark.asyncio
async def test_redis_rate_limit_is_shared_across_clients():
    prefix = f"deepscout:test:{uuid4()}"
    client_a = Redis.from_url(_REDIS_URL, decode_responses=True)
    client_b = Redis.from_url(_REDIS_URL, decode_responses=True)
    limiter_a = RedisSlidingWindowLimiter(client_a, requests=2, window_seconds=10, prefix=prefix)
    limiter_b = RedisSlidingWindowLimiter(client_b, requests=2, window_seconds=10, prefix=prefix)

    try:
        assert await limiter_a.acquire("principal") is None
        assert await limiter_b.acquire("principal") is None
        retry_after = await limiter_a.acquire("principal")
        assert retry_after is not None
        assert 0 < retry_after <= 10
    finally:
        await client_a.delete(f"{prefix}:principal")
        await client_a.aclose()
        await client_b.aclose()
