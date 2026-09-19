"""构建 DeepScout Experiment Registry / History dashboard。"""

from __future__ import annotations

import argparse
from pathlib import Path

from deepscout.evaluation.experiment_registry import (
    build_experiment_registry,
    registry_entry,
)
from deepscout.evaluation.experiment_registry_report import save_experiment_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundles-root", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/experiment-registry-latest"),
    )
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args()

    report = build_experiment_registry(args.bundles_root)
    paths = save_experiment_registry(report, args.output_dir)
    candidate = None
    if args.candidate_id:
        try:
            candidate = registry_entry(report, args.candidate_id)
        except (KeyError, ValueError) as exc:
            print(f"candidate_error={exc}")
            return 2

    print(
        f"bundles={report.bundle_count} valid={report.valid_count} "
        f"invalid={report.invalid_count} groups={report.compatibility_group_count} "
        f"accepted={report.accepted_count} regressions={report.regression_count} "
        f"json={paths['json']}"
    )
    if candidate is not None:
        print(
            f"candidate={candidate.experiment_id} status={candidate.status} "
            f"baseline={candidate.baseline_experiment_id or '-'} "
            f"regressions={candidate.regression_count}"
        )
        if not candidate.valid:
            return 2
        if args.fail_on_regression and candidate.status == "regression":
            return 1
    if args.fail_on_invalid and report.invalid_count:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
