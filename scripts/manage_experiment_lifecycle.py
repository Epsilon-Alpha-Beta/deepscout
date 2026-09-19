"""管理 Experiment promotion / retention lifecycle。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepscout.evaluation.experiment_lifecycle import (
    PromotionOverride,
    RetentionPolicy,
    apply_retention_plan,
    build_retention_plan,
    decide_experiment_promotion,
    load_promotion_decision,
)
from deepscout.evaluation.experiment_lifecycle_report import (
    save_promotion_report,
    save_retention_report,
)
from deepscout.evaluation.experiment_registry import ExperimentRegistryReport


def _load_registry(path: Path) -> ExperimentRegistryReport:
    return ExperimentRegistryReport.model_validate_json(path.read_text(encoding="utf-8"))


def _promotion_command(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    override = None
    if args.override_reason or args.override_actor:
        if not args.override_reason or not args.override_actor:
            raise ValueError("override 需要同时提供 --override-actor 与 --override-reason。")
        override = PromotionOverride(actor=args.override_actor, reason=args.override_reason)

    decision = decide_experiment_promotion(
        registry,
        args.candidate_id,
        actor=args.actor,
        promote_if_eligible=args.promote_if_eligible,
        override=override,
        reject=args.reject,
    )
    paths = save_promotion_report(decision, args.output_dir)
    print(
        f"candidate={decision.experiment_id} eligible={str(decision.eligible).lower()} "
        f"action={decision.action} overridden={str(decision.overridden).lower()} "
        f"blockers={len(decision.blockers)} json={paths['json']}"
    )
    if decision.registry_status == "invalid":
        return 2
    if args.fail_if_blocked and decision.action == "hold" and not decision.eligible:
        return 1
    return 0


def _retention_command(args: argparse.Namespace) -> int:
    registry = _load_registry(args.registry)
    decisions = [load_promotion_decision(path) for path in args.promotion_decision]
    policy = RetentionPolicy(
        keep_latest_accepted_per_group=args.keep_accepted,
        keep_latest_regressions_per_group=args.keep_regressions,
        keep_invalid=args.keep_invalid,
        protect_promoted=not args.no_protect_promoted,
        protect_lineage_roots=not args.no_protect_roots,
        preserve_lineage_closure=not args.no_lineage_closure,
    )
    plan = build_retention_plan(
        registry,
        policy=policy,
        promotion_decisions=decisions,
        milestone_ids=args.milestone_id,
    )
    apply_report = None
    if args.apply_retention:
        apply_report = apply_retention_plan(plan, dry_run=False)
    elif args.dry_run_apply:
        apply_report = apply_retention_plan(plan, dry_run=True)

    paths = save_retention_report(
        plan,
        args.output_dir,
        apply_report=apply_report,
    )
    print(
        f"keep={plan.keep_count} delete={plan.delete_count} "
        f"apply={str(args.apply_retention).lower()} json={paths['json']}"
    )
    if apply_report is not None:
        print(
            f"would_delete={len(apply_report.would_delete)} "
            f"deleted={len(apply_report.deleted)} skipped={len(apply_report.skipped)} "
            f"dry_run={str(apply_report.dry_run).lower()}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    promotion = subparsers.add_parser("promotion")
    promotion.add_argument("--registry", type=Path, required=True)
    promotion.add_argument("--candidate-id", required=True)
    promotion.add_argument("--actor", default="ci")
    promotion.add_argument("--promote-if-eligible", action="store_true")
    promotion.add_argument("--reject", action="store_true")
    promotion.add_argument("--override-actor", default=None)
    promotion.add_argument("--override-reason", default=None)
    promotion.add_argument("--fail-if-blocked", action="store_true")
    promotion.add_argument("--output-dir", type=Path, required=True)
    promotion.set_defaults(func=_promotion_command)

    retention = subparsers.add_parser("retention")
    retention.add_argument("--registry", type=Path, required=True)
    retention.add_argument(
        "--promotion-decision",
        type=Path,
        action="append",
        default=[],
    )
    retention.add_argument("--milestone-id", action="append", default=[])
    retention.add_argument("--keep-accepted", type=int, default=3)
    retention.add_argument("--keep-regressions", type=int, default=2)
    retention.add_argument("--keep-invalid", action="store_true")
    retention.add_argument("--no-protect-promoted", action="store_true")
    retention.add_argument("--no-protect-roots", action="store_true")
    retention.add_argument("--no-lineage-closure", action="store_true")
    retention.add_argument("--dry-run-apply", action="store_true")
    retention.add_argument("--apply-retention", action="store_true")
    retention.add_argument("--output-dir", type=Path, required=True)
    retention.set_defaults(func=_retention_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "promote_if_eligible", False) and getattr(args, "reject", False):
        parser.error("--promote-if-eligible 与 --reject 不能同时使用。")
    if getattr(args, "apply_retention", False) and getattr(args, "dry_run_apply", False):
        parser.error("--apply-retention 与 --dry-run-apply 不能同时使用。")
    try:
        return args.func(args)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"lifecycle_error={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
