"""Researcher 内部的 Web Search 硬预算。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class SearchCounter:
    quota: int
    used: int = 0


_counter: ContextVar[SearchCounter | None] = ContextVar("deepscout_search_counter", default=None)


@contextmanager
def research_search_budget(quota: int) -> Iterator[SearchCounter]:
    """为当前异步 Researcher 上下文绑定独立搜索额度。"""
    counter = SearchCounter(quota=max(0, quota))
    token = _counter.set(counter)
    try:
        yield counter
    finally:
        _counter.reset(token)


def consume_search() -> bool:
    """尝试消费一次搜索额度；没有绑定预算时保持向后兼容。"""
    counter = _counter.get()
    if counter is None:
        return True
    if counter.used >= counter.quota:
        return False
    counter.used += 1
    return True
