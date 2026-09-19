"""Experiment lifecycle：promotion decision、manual override 与 retention plan。"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from deepscout.evaluation.experiment_bundle import load_bundle_manifest
from deepscout.evaluation.experiment_registry import (
    ExperimentRegistryEntry,
    ExperimentRegistryReport,
    registry_entry,
)

PromotionAction = Literal["hold", "promote", "reject"]
RetentionActionType = Literal["keep", "delete"]


class PromotionPolicy(BaseModel):
    require_valid: bool = True
    allowed_registry_statuses: list[str] = Field(default_factory=lambda: ["baseline", "accepted"])
    require_clean_git: bool = True
    max_regressions: int = Field(default=0, ge=0)
    require_zero_regressions: bool = True


class PromotionOverride(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class PromotionDecision(BaseModel):
    schema_version: str = "1.0"
    experiment_id: str
    compatibility_key: str | None = None
    registry_status: str
    decided_at: str
    actor: str
    action: PromotionAction
    eligible: bool
    overridden: bool = False
    blockers: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    policy: PromotionPolicy

    @model_validator(mode="after")
    def validate_override(self) -> PromotionDecision:
        if self.action == "promote" and not self.eligible and not self.overridden:
            raise ValueError("不满足 promotion policy 时只能通过显式 override 晋级。")
        return self


class RetentionPolicy(BaseModel):
    keep_latest_accepted_per_group: int = Field(default=3, ge=0)
    keep_latest_regressions_per_group: int = Field(default=2, ge=0)
    keep_invalid: bool = False
    protect_promoted: bool = True
    protect_lineage_roots: bool = True
    preserve_lineage_closure: bool = True


class RetentionAction(BaseModel):
    experiment_id: str
    bundle_path: str
    registry_status: str
    action: RetentionActionType
    reasons: list[str] = Field(default_factory=list)


class RetentionPlan(BaseModel):
    schema_version: str = "1.0"
    generated_at: str
    bundles_root: str
    policy: RetentionPolicy
    milestone_ids: list[str] = Field(default_factory=list)
    promoted_ids: list[str] = Field(default_factory=list)
    actions: list[RetentionAction]
    keep_count: int = Field(ge=0)
    delete_count: int = Field(ge=0)


class RetentionApplyReport(BaseModel):
    applied_at: str
    dry_run: bool
    would_delete: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def _promotion_blockers(entry: ExperimentRegistryEntry, policy: PromotionPolicy) -> list[str]:
    blockers: list[str] = []
    if policy.require_valid and not entry.valid:
        blockers.append("bundle is invalid")
    if entry.status not in policy.allowed_registry_statuses:
        blockers.append(f"registry status {entry.status!r} is not promotable")
    if policy.require_clean_git and entry.git_dirty is True:
        blockers.append("git worktree was dirty")
    if policy.require_zero_regressions and entry.regression_count > policy.max_regressions:
        blockers.append(
            f"regression_count={entry.regression_count} exceeds {policy.max_regressions}"
        )
    return blockers


def decide_experiment_promotion(
    registry: ExperimentRegistryReport,
    experiment_id: str,
    *,
    policy: PromotionPolicy | None = None,
    actor: str = "ci",
    promote_if_eligible: bool = False,
    override: PromotionOverride | None = None,
    reject: bool = False,
) -> PromotionDecision:
    policy = policy or PromotionPolicy()
    entry = registry_entry(registry, experiment_id)
    blockers = _promotion_blockers(entry, policy)
    eligible = not blockers
    reasons: list[str] = []
    overridden = False

    if reject:
        action: PromotionAction = "reject"
        reasons.append("explicit rejection")
    elif promote_if_eligible and eligible:
        action = "promote"
        reasons.append("promotion policy satisfied")
    elif promote_if_eligible and not eligible and override is not None:
        if not entry.valid:
            action = "hold"
            reasons.append("invalid bundle cannot be overridden")
        else:
            action = "promote"
            overridden = True
            actor = override.actor
            reasons.append(f"manual override: {override.reason}")
    else:
        action = "hold"
        reasons.append("awaiting promotion or blocked by policy")

    return PromotionDecision(
        experiment_id=entry.experiment_id,
        compatibility_key=entry.compatibility_key,
        registry_status=entry.status,
        decided_at=datetime.now(UTC).isoformat(),
        actor=actor,
        action=action,
        eligible=eligible,
        overridden=overridden,
        blockers=blockers,
        reasons=reasons,
        policy=policy,
    )


def effective_promotion_decisions(
    decisions: list[PromotionDecision],
) -> dict[str, PromotionDecision]:
    effective: dict[str, PromotionDecision] = {}
    for decision in sorted(decisions, key=lambda item: item.decided_at):
        effective[decision.experiment_id] = decision
    return effective


def latest_promoted_by_group(
    decisions: list[PromotionDecision],
) -> dict[str, PromotionDecision]:
    promoted: dict[str, PromotionDecision] = {}
    effective = effective_promotion_decisions(decisions)
    for decision in sorted(effective.values(), key=lambda item: item.decided_at):
        if decision.action != "promote" or not decision.compatibility_key:
            continue
        promoted[decision.compatibility_key] = decision
    return promoted


def _entry_time(entry: ExperimentRegistryEntry) -> datetime:
    if entry.created_at is None:
        return datetime.min.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(entry.created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_retention_plan(
    registry: ExperimentRegistryReport,
    *,
    policy: RetentionPolicy | None = None,
    promotion_decisions: list[PromotionDecision] | None = None,
    milestone_ids: list[str] | None = None,
) -> RetentionPlan:
    policy = policy or RetentionPolicy()
    decisions = promotion_decisions or []
    milestones = set(milestone_ids or [])
    effective_decisions = effective_promotion_decisions(decisions)
    promoted = {
        decision.experiment_id
        for decision in effective_decisions.values()
        if decision.action == "promote"
    }
    known_ids = {entry.experiment_id for entry in registry.entries}
    unknown_milestones = milestones - known_ids
    if unknown_milestones:
        raise ValueError("milestone experiment_id 不存在: " + ", ".join(sorted(unknown_milestones)))
    unknown_promoted = promoted - known_ids
    if unknown_promoted:
        raise ValueError(
            "promotion decision 引用了未知 experiment_id: " + ", ".join(sorted(unknown_promoted))
        )

    entries_by_id = {entry.experiment_id: entry for entry in registry.entries}
    for experiment_id, decision in effective_decisions.items():
        entry = entries_by_id.get(experiment_id)
        if entry is None:
            continue
        if decision.compatibility_key != entry.compatibility_key:
            raise ValueError(f"promotion decision compatibility_key 已过期: {experiment_id}")

    keep_reasons: dict[str, list[str]] = defaultdict(list)
    if policy.protect_promoted:
        for experiment_id in promoted:
            keep_reasons[experiment_id].append("promoted baseline protected")
    for experiment_id in milestones:
        keep_reasons[experiment_id].append("milestone protected")

    groups: dict[str, list[ExperimentRegistryEntry]] = defaultdict(list)
    for entry in registry.entries:
        if entry.valid and entry.compatibility_key:
            groups[entry.compatibility_key].append(entry)
        elif entry.status == "invalid" and policy.keep_invalid:
            keep_reasons[entry.experiment_id].append("invalid retention enabled")

    for entries in groups.values():
        ordered = sorted(entries, key=_entry_time, reverse=True)
        if policy.protect_lineage_roots:
            for entry in ordered:
                if entry.status == "baseline":
                    keep_reasons[entry.experiment_id].append("lineage root protected")
        accepted = [entry for entry in ordered if entry.status == "accepted"]
        regressions = [entry for entry in ordered if entry.status == "regression"]
        for entry in accepted[: policy.keep_latest_accepted_per_group]:
            keep_reasons[entry.experiment_id].append("recent accepted retained")
        for entry in regressions[: policy.keep_latest_regressions_per_group]:
            keep_reasons[entry.experiment_id].append("recent regression retained")

    if policy.preserve_lineage_closure:
        by_id = {entry.experiment_id: entry for entry in registry.entries}
        changed = True
        while changed:
            changed = False
            for experiment_id in list(keep_reasons):
                entry = by_id.get(experiment_id)
                if entry is None or not entry.baseline_experiment_id:
                    continue
                baseline_id = entry.baseline_experiment_id
                if baseline_id not in keep_reasons:
                    keep_reasons[baseline_id].append(f"lineage ancestor of {experiment_id}")
                    changed = True

    actions: list[RetentionAction] = []
    for entry in registry.entries:
        reasons = keep_reasons.get(entry.experiment_id, [])
        action: RetentionActionType = "keep" if reasons else "delete"
        if action == "delete":
            reasons = ["outside retention policy"]
        actions.append(
            RetentionAction(
                experiment_id=entry.experiment_id,
                bundle_path=entry.bundle_path,
                registry_status=entry.status,
                action=action,
                reasons=reasons,
            )
        )

    return RetentionPlan(
        generated_at=datetime.now(UTC).isoformat(),
        bundles_root=registry.bundles_root,
        policy=policy,
        milestone_ids=sorted(milestones),
        promoted_ids=sorted(promoted),
        actions=actions,
        keep_count=sum(item.action == "keep" for item in actions),
        delete_count=sum(item.action == "delete" for item in actions),
    )


def apply_retention_plan(plan: RetentionPlan, *, dry_run: bool = True) -> RetentionApplyReport:
    root = Path(plan.bundles_root).resolve()
    would_delete: list[str] = []
    deleted: list[str] = []
    skipped: list[str] = []
    for action in plan.actions:
        if action.action != "delete":
            continue
        bundle = (root / action.bundle_path).resolve()
        try:
            bundle.relative_to(root)
        except ValueError:
            skipped.append(f"{action.experiment_id}: path outside bundles root")
            continue
        if bundle == root:
            skipped.append(f"{action.experiment_id}: refusing to delete bundles root")
            continue
        manifest_path = bundle / "manifest.json"
        if not manifest_path.is_file():
            skipped.append(f"{action.experiment_id}: manifest missing")
            continue
        try:
            manifest = load_bundle_manifest(bundle)
        except Exception as exc:
            skipped.append(f"{action.experiment_id}: manifest parse {type(exc).__name__}")
            continue
        if manifest.experiment_id != action.experiment_id:
            skipped.append(f"{action.experiment_id}: manifest experiment_id mismatch")
            continue
        if dry_run:
            would_delete.append(action.experiment_id)
            continue
        shutil.rmtree(bundle)
        deleted.append(action.experiment_id)
    return RetentionApplyReport(
        applied_at=datetime.now(UTC).isoformat(),
        dry_run=dry_run,
        would_delete=would_delete,
        deleted=deleted,
        skipped=skipped,
    )


def load_promotion_decision(path: str | Path) -> PromotionDecision:
    return PromotionDecision.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_promotion_decision(decision: PromotionDecision, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def save_retention_plan(plan: RetentionPlan, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
