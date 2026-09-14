"""Caller-scoped memory or Redis sliding-window rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis

from deepscout.api.security import Principal, require_api_principal
from deepscout.config import get_settings


class RateLimiter(Protocol):
    async def acquire(self, key: str) -> float | None: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


@dataclass
class SlidingWindowLimiter:
    requests: int
    window_seconds: float

    def __post_init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> float | None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.requests:
                return max(0.0, self.window_seconds - (now - events[0]))
            events.append(now)
            return None

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


_REDIS_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = math.max(0, window - (now - tonumber(oldest[2])))
  end
  redis.call('PEXPIRE', key, math.ceil(window))
  return {0, math.ceil(retry)}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window))
return {1, 0}
"""


@dataclass
class RedisSlidingWindowLimiter:
    client: Redis
    requests: int
    window_seconds: float
    prefix: str = "deepscout:ratelimit"

    async def acquire(self, key: str) -> float | None:
        now_ms = int(time.time() * 1000)
        window_ms = int(self.window_seconds * 1000)
        redis_key = f"{self.prefix}:{key}"
        member = f"{now_ms}:{uuid4()}"
        allowed, retry_ms = await self.client.eval(
            _REDIS_LUA,
            1,
            redis_key,
            now_ms,
            window_ms,
            self.requests,
            member,
        )
        return None if int(allowed) == 1 else max(0.001, int(retry_ms) / 1000)

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def aclose(self) -> None:
        await self.client.aclose()


_LIMITERS: dict[tuple[int, float], SlidingWindowLimiter] = {}
_REDIS_LIMITERS: dict[tuple[str, int, float, float], RedisSlidingWindowLimiter] = {}


def _memory_limiter() -> SlidingWindowLimiter:
    settings = get_settings()
    key = (settings.api_rate_limit_requests, settings.api_rate_limit_window_seconds)
    if key not in _LIMITERS:
        _LIMITERS[key] = SlidingWindowLimiter(*key)
    return _LIMITERS[key]


def _redis_limiter() -> RedisSlidingWindowLimiter:
    settings = get_settings()
    if not settings.api_rate_limit_redis_url:
        raise RuntimeError("Redis 限流已启用，但未配置 Redis URL。")
    cache_key = (
        settings.api_rate_limit_redis_url,
        settings.api_rate_limit_requests,
        settings.api_rate_limit_window_seconds,
        settings.api_rate_limit_redis_timeout_seconds,
    )
    if cache_key not in _REDIS_LIMITERS:
        client = Redis.from_url(
            settings.api_rate_limit_redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.api_rate_limit_redis_timeout_seconds,
            socket_timeout=settings.api_rate_limit_redis_timeout_seconds,
        )
        _REDIS_LIMITERS[cache_key] = RedisSlidingWindowLimiter(
            client=client,
            requests=settings.api_rate_limit_requests,
            window_seconds=settings.api_rate_limit_window_seconds,
        )
    return _REDIS_LIMITERS[cache_key]


def current_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.api_rate_limit_backend == "redis":
        return _redis_limiter()
    return _memory_limiter()


async def rate_limit_readiness() -> tuple[bool, str]:
    settings = get_settings()
    if settings.api_rate_limit_backend == "memory":
        return True, "memory"
    try:
        ready = await _redis_limiter().ping()
    except Exception:
        return False, "redis_unavailable"
    return (True, "redis") if ready else (False, "redis_unavailable")


async def close_rate_limiters() -> None:
    limiters = list(_REDIS_LIMITERS.values())
    _REDIS_LIMITERS.clear()
    for limiter in limiters:
        await limiter.aclose()


async def enforce_rate_limit(
    principal: Annotated[Principal, Depends(require_api_principal)],
) -> Principal:
    """Authenticate, then enforce a caller-scoped request budget."""

    try:
        retry_after = await current_limiter().acquire(principal.key)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="限流后端暂不可用。",
        ) from exc
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试。",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )
    return principal
