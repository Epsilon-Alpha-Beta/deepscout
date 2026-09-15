"""Benchmark Case 质量控制、来源政策与平衡性审计。"""

from __future__ import annotations

import re
from collections import Counter
from itertools import combinations
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.evaluation.models import BenchmarkCase, BenchmarkCorpus

Severity = Literal["error", "warning"]
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class BenchmarkQualityPolicy(BaseModel):
    """Core Benchmark 的可版本化质量门槛。"""

    min_cases: int = Field(default=20, ge=1)
    min_topic_groups: int = Field(default=6, ge=1)
    max_topic_share: float = Field(default=0.25, gt=0.0, le=1.0)
    max_category_share: float = Field(default=0.25, gt=0.0, le=1.0)
    min_medium_share: float = Field(default=0.20, ge=0.0, le=1.0)
    max_hard_share: float = Field(default=0.80, gt=0.0, le=1.0)
    min_freshness_share: float = Field(default=0.50, ge=0.0, le=1.0)
    min_preferred_domains: int = Field(default=2, ge=1)
    min_required_points: int = Field(default=3, ge=1)
    min_critical_errors: int = Field(default=1, ge=0)
    max_single_domain_share: float = Field(default=0.40, gt=0.0, le=1.0)
    max_case_overlap: float = Field(default=0.60, ge=0.0, le=1.0)


class BenchmarkQualityIssue(BaseModel):
    severity: Severity
    code: str
    message: str
    case_id: str | None = None


class BenchmarkQualitySnapshot(BaseModel):
    case_count: int
    topic_group_count: int
    freshness_case_count: int
    rubric_case_count: int
    source_policy_case_count: int
    topic_counts: dict[str, int]
    category_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    preferred_domain_case_counts: dict[str, int]


class BenchmarkQualityReport(BaseModel):
    corpus_name: str
    corpus_version: str
    passed: bool
    error_count: int
    warning_count: int
    snapshot: BenchmarkQualitySnapshot
    policy: BenchmarkQualityPolicy
    issues: list[BenchmarkQualityIssue]


def _ratio(value: int, total: int) -> float:
    return value / total if total else 0.0


def _case_signature(case: BenchmarkCase) -> set[str]:
    tokens = {case.topic_group.lower(), case.category.lower()}
    tokens.update(tag.strip().lower() for tag in case.tags if tag.strip())
    tokens.update(keyword.strip().lower() for keyword in case.expected_keywords if keyword.strip())
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _snapshot(corpus: BenchmarkCorpus) -> BenchmarkQualitySnapshot:
    topic_counts = Counter(case.topic_group for case in corpus.cases)
    category_counts = Counter(case.category for case in corpus.cases)
    difficulty_counts = Counter(case.difficulty for case in corpus.cases)
    domain_counts: Counter[str] = Counter()
    for case in corpus.cases:
        if case.source_policy:
            domain_counts.update(set(case.source_policy.preferred_domains))
    return BenchmarkQualitySnapshot(
        case_count=len(corpus.cases),
        topic_group_count=len(topic_counts),
        freshness_case_count=sum(
            bool(case.source_policy and case.source_policy.freshness_required)
            for case in corpus.cases
        ),
        rubric_case_count=sum(case.gold_rubric is not None for case in corpus.cases),
        source_policy_case_count=sum(case.source_policy is not None for case in corpus.cases),
        topic_counts=dict(sorted(topic_counts.items())),
        category_counts=dict(sorted(category_counts.items())),
        difficulty_counts=dict(sorted(difficulty_counts.items())),
        preferred_domain_case_counts=dict(sorted(domain_counts.items())),
    )


def audit_benchmark_corpus(
    corpus: BenchmarkCorpus,
    policy: BenchmarkQualityPolicy | None = None,
) -> BenchmarkQualityReport:
    """对 Case 级来源、rubric、重复度以及 Corpus balance 做静态审计。"""
    policy = policy or BenchmarkQualityPolicy()
    snapshot = _snapshot(corpus)
    issues: list[BenchmarkQualityIssue] = []

    def issue(severity: Severity, code: str, message: str, case_id: str | None = None) -> None:
        issues.append(
            BenchmarkQualityIssue(
                severity=severity,
                code=code,
                message=message,
                case_id=case_id,
            )
        )

    total = snapshot.case_count
    if total < policy.min_cases:
        issue("error", "corpus_too_small", f"Case 数 {total} < 最低要求 {policy.min_cases}。")
    if snapshot.topic_group_count < policy.min_topic_groups:
        issue(
            "error",
            "too_few_topic_groups",
            f"topic_group 数 {snapshot.topic_group_count} < {policy.min_topic_groups}。",
        )

    for case in corpus.cases:
        if case.topic_group == "unclassified":
            issue("error", "unclassified_topic", "Case 未分配 topic_group。", case.case_id)
        if len(case.expected_keywords) < 3:
            issue("error", "too_few_keywords", "expected_keywords 至少需要 3 个。", case.case_id)
        if len(set(case.tags)) != len(case.tags):
            issue("error", "duplicate_tags", "tags 存在重复值。", case.case_id)

        source = case.source_policy
        if source is None:
            issue("error", "missing_source_policy", "缺少 source_policy。", case.case_id)
        else:
            domains = [domain.lower() for domain in source.preferred_domains]
            if len(domains) < policy.min_preferred_domains:
                issue(
                    "error",
                    "too_few_preferred_domains",
                    f"preferred_domains 少于 {policy.min_preferred_domains}。",
                    case.case_id,
                )
            if len(domains) != len(set(domains)):
                issue("error", "duplicate_domains", "preferred_domains 存在重复。", case.case_id)
            for domain in domains:
                if not _DOMAIN_RE.fullmatch(domain):
                    issue("error", "invalid_domain", f"非法域名：{domain}", case.case_id)
            if source.min_primary_sources > len(set(domains)):
                issue(
                    "warning",
                    "primary_source_domain_pressure",
                    "min_primary_sources 大于 preferred domain 数，可能造成来源集中。",
                    case.case_id,
                )

        rubric = case.gold_rubric
        if rubric is None:
            issue("error", "missing_gold_rubric", "缺少人工 gold_rubric。", case.case_id)
        else:
            if len(rubric.required_points) < policy.min_required_points:
                issue(
                    "error",
                    "too_few_required_points",
                    f"required_points 少于 {policy.min_required_points}。",
                    case.case_id,
                )
            if len(rubric.critical_errors) < policy.min_critical_errors:
                issue(
                    "warning",
                    "missing_critical_error_guard",
                    "未定义足够的 critical_errors。",
                    case.case_id,
                )
            if len(set(rubric.required_points)) != len(rubric.required_points):
                issue(
                    "error", "duplicate_required_points", "required_points 存在重复。", case.case_id
                )

    if total:
        max_topic, topic_count = max(snapshot.topic_counts.items(), key=lambda item: item[1])
        if _ratio(topic_count, total) > policy.max_topic_share:
            issue(
                "error",
                "topic_concentration",
                f"topic_group={max_topic} 占比 {_ratio(topic_count, total):.1%} 超过 "
                f"{policy.max_topic_share:.1%}。",
            )
        max_category, category_count = max(
            snapshot.category_counts.items(), key=lambda item: item[1]
        )
        if _ratio(category_count, total) > policy.max_category_share:
            issue(
                "error",
                "category_concentration",
                f"category={max_category} 占比 {_ratio(category_count, total):.1%} 超过 "
                f"{policy.max_category_share:.1%}。",
            )
        medium_share = _ratio(snapshot.difficulty_counts.get("medium", 0), total)
        hard_share = _ratio(snapshot.difficulty_counts.get("hard", 0), total)
        if medium_share < policy.min_medium_share:
            issue("error", "too_few_medium_cases", f"medium 占比仅 {medium_share:.1%}。")
        if hard_share > policy.max_hard_share:
            issue("error", "too_many_hard_cases", f"hard 占比达到 {hard_share:.1%}。")
        freshness_share = _ratio(snapshot.freshness_case_count, total)
        if freshness_share < policy.min_freshness_share:
            issue(
                "error",
                "insufficient_freshness_coverage",
                f"要求 freshness 的 Case 仅 {freshness_share:.1%}。",
            )
        for domain, count in snapshot.preferred_domain_case_counts.items():
            if _ratio(count, total) > policy.max_single_domain_share:
                issue(
                    "warning",
                    "source_domain_concentration",
                    f"preferred domain={domain} 覆盖 {_ratio(count, total):.1%} Case。",
                )

    signatures = {case.case_id: _case_signature(case) for case in corpus.cases}
    for left, right in combinations(corpus.cases, 2):
        overlap = _jaccard(signatures[left.case_id], signatures[right.case_id])
        if overlap > policy.max_case_overlap:
            issue(
                "warning",
                "case_semantic_overlap",
                f"与 {right.case_id} 的标签/关键词 Jaccard={overlap:.2f}。",
                left.case_id,
            )

    errors = sum(item.severity == "error" for item in issues)
    warnings = sum(item.severity == "warning" for item in issues)
    return BenchmarkQualityReport(
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        passed=errors == 0,
        error_count=errors,
        warning_count=warnings,
        snapshot=snapshot,
        policy=policy,
        issues=issues,
    )
