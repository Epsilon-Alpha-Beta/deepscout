"""Simple per-process sliding-window rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from deepscout.api.security import Principal, require_api_principal
from deepscout.config import get_settings


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


_LIMITERS: dict[tuple[int, float], SlidingWindowLimiter] = {}


def _limiter() -> SlidingWindowLimiter:
    settings = get_settings()
    key = (settings.api_rate_limit_requests, settings.api_rate_limit_window_seconds)
    if key not in _LIMITERS:
        _LIMITERS[key] = SlidingWindowLimiter(*key)
    return _LIMITERS[key]


async def enforce_rate_limit(
    principal: Annotated[Principal, Depends(require_api_principal)],
) -> Principal:
    """Authenticate, then enforce a caller-scoped request budget."""

    retry_after = await _limiter().acquire(principal.key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试。",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )
    return principal
