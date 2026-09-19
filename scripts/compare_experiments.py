"""比较两个 DeepScout Experiment Bundle。"""

from __future__ import annotations

import argparse
from pathlib import Path

from deepscout.evaluation.experiment_compare import compare_experiment_bundles
from deepscout.evaluation.experiment_compare_report import save_experiment_comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("benchmark-results/experiment-comparison-latest")
    )
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()
    report = compare_experiment_bundles(args.baseline, args.candidate)
    paths = save_experiment_comparison(report, args.output_dir)
    print(
        f"comparable={str(report.comparable).lower()} regressions={report.regression_count} "
        f"improvements={report.improvement_count} json={paths['json']}"
    )
    if not report.comparable:
        return 2
    if args.fail_on_regression and report.regression_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
