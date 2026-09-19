"""对候选 Experiment Bundle 执行统一 Release Readiness / CI Gate。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepscout.evaluation.experiment_registry import ExperimentRegistryReport
from deepscout.evaluation.release_gate import (
    ReleaseGatePolicy,
    evaluate_release_gate,
)
from deepscout.evaluation.release_gate_report import save_release_gate_report


def _load_registry(path: Path) -> ExperimentRegistryReport:
    return ExperimentRegistryReport.model_validate_json(path.read_text(encoding="utf-8"))


def _load_policy(path: Path) -> ReleaseGatePolicy:
    return ReleaseGatePolicy.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("benchmarks/policies/release_gate.json"),
    )
    parser.add_argument("--actor", default="ci")
    parser.add_argument("--milestone-id", action="append", default=[])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/release-gate-latest"),
    )
    args = parser.parse_args()

    try:
        report = evaluate_release_gate(
            _load_registry(args.registry),
            args.candidate_id,
            policy=_load_policy(args.policy),
            actor=args.actor,
            milestone_ids=args.milestone_id,
        )
        paths = save_release_gate_report(report, args.output_dir)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"release_gate_error={exc}")
        return 2

    print(
        f"candidate={report.experiment_id} status={report.status} "
        f"promotion={report.promotion.action} blockers={len(report.blockers)} "
        f"invalid_registry={report.registry_invalid_count} json={paths['json']}"
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
