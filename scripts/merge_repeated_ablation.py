"""合并 GitHub Actions producer 的重复 Ablation shards 并重建统计报告。"""

from __future__ import annotations

import argparse
from pathlib import Path

from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.repeated_merge import load_repeated_shards, merge_repeated_shards
from deepscout.evaluation.repeated_report import save_repeated_report
from deepscout.evaluation.runner import load_corpus
from deepscout.evaluation.significance import build_significance_report
from deepscout.evaluation.significance_report import save_significance_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--corpus", default="benchmarks/corpora/core.json")
    parser.add_argument("--matrix", default="benchmarks/ablations/core.json")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--order-strategy", choices=("fixed", "rotate"), default="rotate")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--exact-permutation-max-pairs", type=int, default=16)
    parser.add_argument("--permutation-resamples", type=int, default=20000)
    parser.add_argument("--permutation-seed", type=int, default=20260915)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    matrix = load_ablation_matrix(args.matrix)
    shards = load_repeated_shards(args.shards_root)
    report = merge_repeated_shards(
        corpus,
        matrix,
        shards,
        repetitions=args.repetitions,
        order_strategy=args.order_strategy,
    )
    paths = save_repeated_report(report, args.output_dir)
    significance = build_significance_report(
        report,
        alpha=args.alpha,
        exact_permutation_max_pairs=args.exact_permutation_max_pairs,
        permutation_resamples=args.permutation_resamples,
        permutation_seed=args.permutation_seed,
    )
    significance_paths = save_significance_report(significance, args.output_dir)

    failed_runs = sum(record.result.status != "completed" for record in report.runs)
    print(
        f"shards={len(shards)} runs={len(report.runs)} failed_runs={failed_runs} "
        f"json={paths['json']} significance={significance_paths['json']}"
    )
    return 1 if failed_runs else 0


if __name__ == "__main__":
    raise SystemExit(main())
