"""引用验证相关模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class CitationCheck(BaseModel):
    """单条报告 Claim 的证据支持判断。"""

    claim: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["supported", "partial", "unsupported"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)


class CitationVerificationReport(BaseModel):
    """整份最终报告的引用一致性结果。"""

    checks: list[CitationCheck] = Field(default_factory=list)
    coverage_score: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str] = Field(default_factory=list)
    requires_research: bool = False
