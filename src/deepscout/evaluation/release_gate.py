"""Release readiness gate：把 Registry、Promotion 与 Retention 串成单次 CI 判定。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.evaluation.experiment_lifecycle import (
    PromotionDecision,
    PromotionPolicy,
    RetentionPlan,
    RetentionPolicy,
    build_retention_plan,
    decide_experiment_promotion,
)
from deepscout.evaluation.experiment_registry import (
    ExperimentRegistryReport,
    registry_entry,
)

ReleaseGateStatus = Literal["passed", "blocked"]


class ReleaseGatePolicy(BaseModel):
    schema_version: str = "1.0"
    require_zero_invalid_registry: bool = True
    promotion_policy: PromotionPolicy = Field(default_factory=PromotionPolicy)
    retention_policy: RetentionPolicy = Field(default_factory=RetentionPolicy)


class ReleaseGateReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: str
    experiment_id: str
    compatibility_key: str | None = None
    status: ReleaseGateStatus
    passed: bool
    registry_invalid_count: int = Field(ge=0)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy: ReleaseGatePolicy
    promotion: PromotionDecision
    retention: RetentionPlan


def evaluate_release_gate(
    registry: ExperimentRegistryReport,
    experiment_id: str,
    *,
    policy: ReleaseGatePolicy | None = None,
    actor: str = "ci",
    milestone_ids: list[str] | None = None,
) -> ReleaseGateReport:
    policy = policy or ReleaseGatePolicy()
    entry = registry_entry(registry, experiment_id)
    blockers: list[str] = []
    warnings = list(entry.warnings)

    if registry.invalid_count:
        message = f"registry contains {registry.invalid_count} invalid bundle(s)"
        if policy.require_zero_invalid_registry:
            blockers.append(message)
        else:
            warnings.append(message)

    promotion = decide_experiment_promotion(
        registry,
        experiment_id,
        policy=policy.promotion_policy,
        actor=actor,
        promote_if_eligible=True,
    )
    if promotion.action != "promote":
        if promotion.blockers:
            blockers.extend(f"promotion: {item}" for item in promotion.blockers)
        else:
            blockers.append("promotion action is not promote")

    retention = build_retention_plan(
        registry,
        policy=policy.retention_policy,
        promotion_decisions=[promotion],
        milestone_ids=milestone_ids,
    )
    passed = not blockers and promotion.action == "promote"
    return ReleaseGateReport(
        generated_at=datetime.now(UTC).isoformat(),
        experiment_id=entry.experiment_id,
        compatibility_key=entry.compatibility_key,
        status="passed" if passed else "blocked",
        passed=passed,
        registry_invalid_count=registry.invalid_count,
        blockers=blockers,
        warnings=warnings,
        policy=policy,
        promotion=promotion,
        retention=retention,
    )


def load_release_gate_policy(path: str | Path) -> ReleaseGatePolicy:
    return ReleaseGatePolicy.model_validate_json(Path(path).read_text(encoding="utf-8"))
