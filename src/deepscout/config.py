"""DeepScout 运行时配置。"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model: str = "anthropic:claude-sonnet-4-6"
    analysis_model: str | None = None
    planner_model: str | None = None
    researcher_model: str | None = None
    critic_model: str | None = None
    writer_model: str | None = None
    verifier_model: str | None = None

    max_concurrency: int = Field(default=3, ge=1, le=32)
    max_replans: int = Field(default=2, ge=0, le=10)
    max_research_tasks: int = Field(default=24, ge=1, le=200)
    max_evidence_items: int = Field(default=80, ge=1, le=500)
    max_searches: int = Field(default=40, ge=1, le=1000)
    max_research_tokens: int = Field(default=200000, ge=1)
    max_worker_seconds: float = Field(default=900.0, gt=0.0)
    search_max_calls_per_task: int = Field(default=5, ge=1, le=50)
    search_max_results: int = Field(default=5, ge=1, le=20)

    planner_retries: int = Field(default=2, ge=0, le=5)
    node_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    node_retry_initial_interval: float = Field(default=0.5, ge=0.0, le=30.0)
    node_retry_max_interval: float = Field(default=8.0, gt=0.0, le=120.0)

    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    mcp_tool_name_prefix: bool = True

    api_checkpoint: Literal["memory", "postgres"] = "memory"
    postgres_dsn: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_key: str | None = None
    api_rate_limit_requests: int = Field(default=60, ge=1, le=100000)
    api_rate_limit_window_seconds: float = Field(default=60.0, gt=0.0, le=3600.0)
    api_rate_limit_backend: Literal["memory", "redis"] = "memory"
    api_rate_limit_redis_url: str | None = None
    api_rate_limit_redis_timeout_seconds: float = Field(default=1.0, gt=0.0, le=30.0)
    api_metrics_enabled: bool = True

    otel_enabled: bool = False
    otel_service_name: str = "deepscout-api"

    model_config = SettingsConfigDict(env_prefix="DEEPSCOUT_", env_file=".env", extra="ignore")

    def model_for(self, role: str) -> str:
        return getattr(self, f"{role}_model", None) or self.model


_settings_override: ContextVar[Settings | None] = ContextVar(
    "deepscout_settings_override", default=None
)


@lru_cache(maxsize=1)
def _base_settings() -> Settings:
    return Settings()


def get_settings() -> Settings:
    """返回当前上下文配置；没有实验 override 时使用进程级缓存配置。"""
    return _settings_override.get() or _base_settings()


def clear_settings_cache() -> None:
    """清除环境变量驱动的基础 Settings 缓存。"""
    _base_settings.cache_clear()


# 保持既有测试/调用方对 get_settings.cache_clear() 的兼容。
get_settings.cache_clear = clear_settings_cache  # type: ignore[attr-defined]


@contextmanager
def settings_override(overrides: Mapping[str, object]) -> Iterator[Settings]:
    """在当前 ContextVar 上下文内应用经过 Pydantic 校验的 Settings override。"""
    unknown = sorted(set(overrides).difference(Settings.model_fields))
    if unknown:
        raise ValueError(f"未知 Settings override: {', '.join(unknown)}")
    payload = get_settings().model_dump()
    payload.update(overrides)
    effective = Settings.model_validate(payload)
    token = _settings_override.set(effective)
    try:
        yield effective
    finally:
        _settings_override.reset(token)
