"""原始证据、归一化证据与 Claim-Evidence 映射模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

SourceClass = Literal[
    "official_docs",
    "standards",
    "academic",
    "government",
    "source_repository",
    "vendor_engineering",
    "secondary",
    "unknown",
]


class Evidence(BaseModel):
    """Researcher 返回的原始证据。"""

    title: str = Field(min_length=1)
    url: HttpUrl
    content: str = Field(min_length=1)
    source_type: str = "web"
    source_class: SourceClass = "unknown"
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    claims: list[str] = Field(default_factory=list)


class ManagedEvidence(BaseModel):
    """Evidence Manager 处理后的稳定证据记录。"""

    evidence_id: str
    title: str
    url: str
    canonical_url: str
    source_host: str
    content: str
    content_hash: str
    source_type: str = "web"
    source_class: SourceClass = "unknown"
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    claims: list[str] = Field(default_factory=list)
    duplicate_count: int = Field(default=1, ge=1)


class ClaimEvidenceLink(BaseModel):
    """一个规范化 Claim 与支持它的 Evidence ID 集合。"""

    claim_id: str
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
