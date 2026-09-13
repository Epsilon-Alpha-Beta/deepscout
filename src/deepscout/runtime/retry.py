"""LangGraph 节点级重试策略。"""

from langgraph.types import RetryPolicy

from deepscout.config import get_settings


def llm_retry_policy() -> RetryPolicy:
    """为可能发生瞬时网络/Provider 错误的 LLM 节点提供指数退避重试。"""
    settings = get_settings()
    return RetryPolicy(
        initial_interval=settings.node_retry_initial_interval,
        backoff_factor=2.0,
        max_interval=settings.node_retry_max_interval,
        max_attempts=settings.node_retry_max_attempts,
        jitter=True,
    )
