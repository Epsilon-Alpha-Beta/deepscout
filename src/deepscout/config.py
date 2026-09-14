"""DeepScout 运行时配置。"""

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
