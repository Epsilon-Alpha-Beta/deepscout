"""运行 DeepScout 重复 Ablation 实验并生成统计报告。"""

import argparse
import asyncio
from pathlib import Path

from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.models import BenchmarkPricing
from deepscout.evaluation.repeated import run_repeated_ablation
from deepscout.evaluation.repeated_report import save_repeated_report
from deepscout.evaluation.runner import load_corpus


async def _run(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    matrix = load_ablation_matrix(args.matrix)
    cases = corpus.cases[: args.limit] if args.limit is not None else corpus.cases
    planned_runs = len(cases) * len(matrix.profiles) * args.repetitions
    if args.validate_only:
        print(
            f"corpus={corpus.name} cases={len(cases)} matrix={matrix.name} "
            f"profiles={len(matrix.profiles)} repetitions={args.repetitions} "
            f"planned_runs={planned_runs} status=valid"
        )
        return 0

    pricing = BenchmarkPricing(
        research_token_usd_per_million=args.research_token_usd_per_million,
        search_usd_per_1000_calls=args.search_usd_per_1000_calls,
    )
    report = await run_repeated_ablation(
        corpus,
        matrix,
        repetitions=args.repetitions,
        order_strategy=args.order_strategy,
        bootstrap_resamples=args.bootstrap_resamples,
        confidence_level=args.confidence_level,
        bootstrap_seed=args.bootstrap_seed,
        limit=args.limit,
        pricing=pricing,
    )
    paths = save_repeated_report(report, args.output_dir)
    failed_runs = sum(record.result.status != "completed" for record in report.runs)
    print(
        f"runs={len(report.runs)} failed_runs={failed_runs} "
        f"json={paths['json']} markdown={paths['markdown']} "
        f"statistics={paths['statistics_csv']} deltas={paths['deltas_csv']}"
    )
    return 1 if failed_runs else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 DeepScout 重复 Ablation 统计实验。")
    parser.add_argument("--corpus", default="benchmarks/corpora/core.json")
    parser.add_argument("--matrix", default="benchmarks/ablations/core.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/repeated-ablation-latest"),
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--order-strategy", choices=("fixed", "rotate"), default="rotate")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--bootstrap-seed", type=int, default=20260915)
    parser.add_argument("--research-token-usd-per-million", type=float, default=None)
    parser.add_argument("--search-usd-per-1000-calls", type=float, default=None)
    parser.add_argument("--validate-only", action="store_true")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
