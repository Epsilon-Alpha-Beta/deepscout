"""Runtime configuration for DeepScout."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model: str = "anthropic:claude-sonnet-4-6"
    analysis_model: str | None = None
    planner_model: str | None = None
    researcher_model: str | None = None
    critic_model: str | None = None
    writer_model: str | None = None
    max_concurrency: int = Field(default=3, ge=1, le=32)
    max_replans: int = Field(default=2, ge=0, le=10)
    planner_retries: int = Field(default=2, ge=0, le=5)
    search_max_results: int = Field(default=5, ge=1, le=20)
    model_config = SettingsConfigDict(env_prefix="DEEPSCOUT_", env_file=".env", extra="ignore")

    def model_for(self, role: str) -> str:
        return getattr(self, f"{role}_model", None) or self.model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
