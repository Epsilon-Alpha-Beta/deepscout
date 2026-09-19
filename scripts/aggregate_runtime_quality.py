"""把 source compliance / human review sidecar 聚合到 repeated ablation。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from deepscout.evaluation.quality_aggregate import (
    BlindReviewAssignment,
    SourceQualityObservation,
    build_runtime_quality_aggregate,
)
from deepscout.evaluation.quality_aggregate_report import save_runtime_quality_aggregate
from deepscout.evaluation.repeated import RepeatedExperimentReport
from deepscout.evaluation.review_audit import HumanReviewAuditReport

T = TypeVar("T", bound=BaseModel)


def _load_model(path: Path, model_type: type[T]) -> T:
    return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _load_many(paths: list[Path], model_type: type[T]) -> list[T]:
    items: list[T] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
        items.extend(model_type.model_validate(row) for row in rows)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="聚合 DeepScout 运行后质量 sidecar。")
    parser.add_argument("--repeated", type=Path, required=True)
    parser.add_argument("--source-observation", type=Path, action="append", default=[])
    parser.add_argument("--review-assignment", type=Path, action="append", default=[])
    parser.add_argument("--review-audit", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/runtime-quality-latest"),
    )
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--exact-permutation-max-pairs", type=int, default=16)
    parser.add_argument("--permutation-resamples", type=int, default=20000)
    parser.add_argument("--permutation-seed", type=int, default=20260915)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not 0.0 < args.alpha < 1.0:
        parser.error("--alpha 必须位于 (0,1)。")
    if args.exact_permutation_max_pairs < 1:
        parser.error("--exact-permutation-max-pairs 必须 >= 1。")
    if args.permutation_resamples < 1:
        parser.error("--permutation-resamples 必须 >= 1。")

    repeated = _load_model(args.repeated, RepeatedExperimentReport)
    source_observations = _load_many(args.source_observation, SourceQualityObservation)
    assignments = _load_many(args.review_assignment, BlindReviewAssignment)
    human_audit = (
        _load_model(args.review_audit, HumanReviewAuditReport)
        if args.review_audit is not None
        else None
    )
    report = build_runtime_quality_aggregate(
        repeated,
        source_observations=source_observations,
        assignments=assignments,
        human_audit=human_audit,
        alpha=args.alpha,
        exact_permutation_max_pairs=args.exact_permutation_max_pairs,
        permutation_resamples=args.permutation_resamples,
        permutation_seed=args.permutation_seed,
    )
    unresolved = human_audit.unresolved_item_count if human_audit is not None else 0
    significance_count = (
        len(report.human_gold_significance.comparisons)
        if report.human_gold_significance is not None
        else 0
    )
    if args.validate_only:
        print(
            f"runs={len(repeated.runs)} source_observations={len(source_observations)} "
            f"assignments={len(assignments)} unresolved={unresolved} "
            f"human_gold_significance_rows={significance_count} status=valid"
        )
        return 2 if args.strict and unresolved else 0

    paths = save_runtime_quality_aggregate(report, args.output_dir)
    json_path = paths["json"]
    markdown_path = paths["markdown"]
    print(
        f"runs={len(repeated.runs)} source_observations={len(source_observations)} "
        f"assignments={len(assignments)} unresolved={unresolved} "
        f"human_gold_significance_rows={significance_count} "
        f"json={json_path} markdown={markdown_path}"
    )
    return 2 if args.strict and unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
