"""Evidence schemas."""

from pydantic import BaseModel, Field, HttpUrl


class Evidence(BaseModel):
    title: str = Field(min_length=1)
    url: HttpUrl
    content: str = Field(min_length=1)
    source_type: str = "web"
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    claims: list[str] = Field(default_factory=list)
