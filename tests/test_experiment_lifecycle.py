from pathlib import Path

from deepscout.evaluation.experiment_bundle import load_bundle_manifest
from deepscout.evaluation.experiment_lifecycle import (
    PromotionOverride,
    RetentionAction,
    RetentionPlan,
    RetentionPolicy,
    apply_retention_plan,
    build_retention_plan,
    decide_experiment_promotion,
)
from deepscout.evaluation.experiment_lifecycle_report import (
    save_promotion_report,
    save_retention_report,
)
from deepscout.evaluation.experiment_registry import build_experiment_registry
from tests.test_experiment_bundle import _bundle
from tests.test_experiment_registry import _stamp


def _history(tmp_path: Path):
    specs = [
        ("b1", 0.00, 0.00, 0.00),
        ("b2", -0.10, 0.30, -0.10),
        ("b3", 0.05, -0.10, 0.05),
        ("b4", -0.10, 0.30, -0.10),
        ("b5", 0.08, -0.15, 0.08),
        ("b6", -0.10, 0.30, -0.10),
        ("b7", 0.10, -0.20, 0.10),
    ]
    bundles = {}
    for index, (name, quality, wall, gold) in enumerate(specs):
        bundle = _bundle(
            tmp_path,
            name,
            quality_shift=quality,
            wall_shift=wall,
            gold_shift=gold,
        )
        _stamp(
            bundle,
            created_at=f"2026-09-19T0{index}:00:00+00:00",
        )
        manifest = load_bundle_manifest(bundle)
        manifest.git_dirty = False
        (bundle / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        bundles[name] = bundle
    return bundles, build_experiment_registry(tmp_path)


def test_promotion_policy_and_manual_override(tmp_path: Path):
    _, registry = _history(tmp_path)

    accepted = decide_experiment_promotion(
        registry,
        "b3",
        actor="ci",
        promote_if_eligible=True,
    )
    assert accepted.eligible is True
    assert accepted.action == "promote"
    assert accepted.overridden is False

    blocked = decide_experiment_promotion(
        registry,
        "b2",
        actor="ci",
        promote_if_eligible=True,
    )
    assert blocked.eligible is False
    assert blocked.action == "hold"
    assert blocked.overridden is False
    assert any("not promotable" in item for item in blocked.blockers)

    overridden = decide_experiment_promotion(
        registry,
        "b2",
        promote_if_eligible=True,
        override=PromotionOverride(
            actor="release-owner",
            reason="known provider transition accepted for milestone",
        ),
    )
    assert overridden.action == "promote"
    assert overridden.overridden is True
    assert overridden.actor == "release-owner"
    assert any("manual override" in item for item in overridden.reasons)

    paths = save_promotion_report(overridden, tmp_path / "promotion-report")
    assert paths["json"].exists()
    assert paths["markdown"].exists()


def test_dirty_worktree_blocks_promotion_but_can_be_overridden(tmp_path: Path):
    bundles, _ = _history(tmp_path)
    manifest = load_bundle_manifest(bundles["b3"])
    manifest.git_dirty = True
    (bundles["b3"] / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    registry = build_experiment_registry(tmp_path)

    blocked = decide_experiment_promotion(registry, "b3", actor="ci", promote_if_eligible=True)
    assert blocked.action == "hold"
    assert any("dirty" in item for item in blocked.blockers)

    overridden = decide_experiment_promotion(
        registry,
        "b3",
        promote_if_eligible=True,
        override=PromotionOverride(actor="owner", reason="validated dirty metadata only"),
    )
    assert overridden.action == "promote"
    assert overridden.overridden is True


def test_invalid_bundle_cannot_be_overridden(tmp_path: Path):
    bundles, _ = _history(tmp_path)
    manifest = load_bundle_manifest(bundles["b7"])
    repeated = next(item for item in manifest.artifacts if item.role == "repeated")
    (bundles["b7"] / repeated.path).write_text("tampered\n", encoding="utf-8")
    registry = build_experiment_registry(tmp_path)

    decision = decide_experiment_promotion(
        registry,
        "b7",
        promote_if_eligible=True,
        override=PromotionOverride(actor="owner", reason="force"),
    )
    assert decision.registry_status == "invalid"
    assert decision.action == "hold"
    assert decision.overridden is False
    assert any("invalid" in item for item in decision.blockers)


def test_retention_policy_preserves_promoted_milestone_and_lineage(tmp_path: Path):
    bundles, registry = _history(tmp_path)
    promoted = decide_experiment_promotion(
        registry,
        "b3",
        actor="ci",
        promote_if_eligible=True,
    )
    plan = build_retention_plan(
        registry,
        policy=RetentionPolicy(
            keep_latest_accepted_per_group=1,
            keep_latest_regressions_per_group=1,
        ),
        promotion_decisions=[promoted],
        milestone_ids=["b2"],
    )
    actions = {item.experiment_id: item for item in plan.actions}

    assert actions["b1"].action == "keep"
    assert actions["b2"].action == "keep"
    assert actions["b3"].action == "keep"
    assert actions["b4"].action == "delete"
    assert actions["b5"].action == "keep"
    assert actions["b6"].action == "keep"
    assert actions["b7"].action == "keep"
    assert any("lineage ancestor" in reason for reason in actions["b5"].reasons)
    assert plan.delete_count == 1

    dry_run = apply_retention_plan(plan, dry_run=True)
    assert dry_run.would_delete == ["b4"]
    assert not dry_run.deleted
    assert not dry_run.skipped
    assert bundles["b4"].exists()

    applied = apply_retention_plan(plan, dry_run=False)
    assert applied.deleted == ["b4"]
    assert not bundles["b4"].exists()
    assert bundles["b2"].exists()
    assert bundles["b3"].exists()

    paths = save_retention_report(
        plan,
        tmp_path / "retention-report",
        apply_report=applied,
    )
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert paths["csv"].exists()
    assert paths["apply_json"].exists()


def test_latest_promotion_decision_controls_retention(tmp_path: Path):
    _, registry = _history(tmp_path)
    promoted = decide_experiment_promotion(
        registry,
        "b3",
        actor="ci",
        promote_if_eligible=True,
    )
    rejected = decide_experiment_promotion(
        registry,
        "b3",
        actor="release-owner",
        reject=True,
    )
    rejected = rejected.model_copy(update={"decided_at": "2099-01-01T00:00:00+00:00"})

    plan = build_retention_plan(
        registry,
        policy=RetentionPolicy(
            keep_latest_accepted_per_group=0,
            keep_latest_regressions_per_group=0,
        ),
        promotion_decisions=[promoted, rejected],
    )
    actions = {item.experiment_id: item for item in plan.actions}
    assert "b3" not in plan.promoted_ids
    assert actions["b3"].action == "delete"


def test_stale_promotion_decision_is_rejected_by_retention(tmp_path: Path):
    _, registry = _history(tmp_path)
    promoted = decide_experiment_promotion(
        registry,
        "b3",
        actor="ci",
        promote_if_eligible=True,
    ).model_copy(update={"compatibility_key": "stale-key"})

    import pytest

    with pytest.raises(ValueError, match="compatibility_key 已过期"):
        build_retention_plan(
            registry,
            promotion_decisions=[promoted],
        )


def test_retention_apply_refuses_to_delete_bundles_root(tmp_path: Path):
    plan = RetentionPlan(
        generated_at="2026-09-19T00:00:00+00:00",
        bundles_root=str(tmp_path),
        policy=RetentionPolicy(),
        actions=[
            RetentionAction(
                experiment_id="root",
                bundle_path=".",
                registry_status="regression",
                action="delete",
                reasons=["test"],
            )
        ],
        keep_count=0,
        delete_count=1,
    )
    report = apply_retention_plan(plan, dry_run=False)
    assert report.deleted == []
    assert any("refusing to delete bundles root" in item for item in report.skipped)
    assert tmp_path.exists()
