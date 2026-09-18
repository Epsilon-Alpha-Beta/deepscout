"""运行后 Evidence 来源政策合规评分。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.evaluation.models import BenchmarkCase
from deepscout.models.evidence import ManagedEvidence

CheckStatus = Literal["passed", "failed", "unverifiable"]


class SourcePolicyCheck(BaseModel):
    name: str
    status: CheckStatus
    actual: int | float | str | None = None
    expected: int | float | str | None = None
    detail: str = ""


class SourcePolicyComplianceReport(BaseModel):
    case_id: str
    evaluated_at: datetime
    evidence_count: int = Field(ge=0)
    primary_source_count: int = Field(ge=0)
    preferred_domain_count: int = Field(ge=0)
    recent_source_count: int = Field(ge=0)
    freshness_evaluable_count: int = Field(ge=0)
    freshness_unknown_count: int = Field(ge=0)
    passed: bool
    checks: list[SourcePolicyCheck] = Field(default_factory=list)


def _domain_matches(host: str, preferred: str) -> bool:
    host = host.lower().strip(".")
    preferred = preferred.lower().strip(".")
    return host == preferred or host.endswith("." + preferred)


def score_source_policy(
    case: BenchmarkCase,
    evidence: list[ManagedEvidence],
    *,
    evaluated_at: datetime | None = None,
) -> SourcePolicyComplianceReport:
    """基于真实 Evidence 元数据评估一个 Case 的来源政策。"""
    policy = case.source_policy
    if policy is None:
        raise ValueError(f"Case {case.case_id} 没有 source_policy，无法做来源合规评分。")

    evaluated_at = evaluated_at or datetime.now(UTC)
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at 必须包含时区。")

    primary_types = set(policy.primary_source_types)
    preferred_domains = set(policy.preferred_domains)
    primary = [item for item in evidence if item.source_class in primary_types]
    preferred = [
        item
        for item in evidence
        if any(_domain_matches(item.source_host, domain) for domain in preferred_domains)
    ]

    recent: list[ManagedEvidence] = []
    evaluable: list[ManagedEvidence] = []
    if policy.freshness_required:
        assert policy.max_age_days is not None
        cutoff = evaluated_at - timedelta(days=policy.max_age_days)
        for item in evidence:
            if item.published_at is None:
                continue
            published = item.published_at
            if published.tzinfo is None:
                continue
            evaluable.append(item)
            if cutoff <= published <= evaluated_at:
                recent.append(item)

    checks = [
        SourcePolicyCheck(
            name="minimum_primary_sources",
            status="passed" if len(primary) >= policy.min_primary_sources else "failed",
            actual=len(primary),
            expected=policy.min_primary_sources,
        )
    ]
    if policy.freshness_required:
        if not evaluable:
            checks.append(
                SourcePolicyCheck(
                    name="minimum_recent_sources",
                    status="unverifiable",
                    actual=0,
                    expected=policy.min_recent_sources,
                    detail="Evidence 缺少可靠 published_at，不能臆测其新鲜度。",
                )
            )
        else:
            checks.append(
                SourcePolicyCheck(
                    name="minimum_recent_sources",
                    status="passed" if len(recent) >= policy.min_recent_sources else "failed",
                    actual=len(recent),
                    expected=policy.min_recent_sources,
                )
            )

    passed = all(check.status == "passed" for check in checks)
    return SourcePolicyComplianceReport(
        case_id=case.case_id,
        evaluated_at=evaluated_at,
        evidence_count=len(evidence),
        primary_source_count=len(primary),
        preferred_domain_count=len(preferred),
        recent_source_count=len(recent),
        freshness_evaluable_count=len(evaluable),
        freshness_unknown_count=max(0, len(evidence) - len(evaluable))
        if policy.freshness_required
        else 0,
        passed=passed,
        checks=checks,
    )
