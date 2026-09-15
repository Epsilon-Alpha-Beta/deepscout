"""运行 DeepScout Phase 4 消融实验矩阵。"""

import argparse
import asyncio
from pathlib import Path

from deepscout.evaluation.ablation import load_ablation_matrix, run_ablation_matrix
from deepscout.evaluation.ablation_report import save_ablation_report
from deepscout.evaluation.models import BenchmarkPricing
from deepscout.evaluation.runner import load_corpus


async def _run(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    matrix = load_ablation_matrix(args.matrix)
    if args.validate_only:
        print(
            f"corpus={corpus.name} cases={len(corpus.cases)} "
            f"matrix={matrix.name} profiles={len(matrix.profiles)} "
            f"baseline={matrix.baseline_profile} status=valid"
        )
        return 0

    pricing = BenchmarkPricing(
        research_token_usd_per_million=args.research_token_usd_per_million,
        search_usd_per_1000_calls=args.search_usd_per_1000_calls,
    )
    report = await run_ablation_matrix(
        corpus,
        matrix,
        limit=args.limit,
        pricing=pricing,
    )
    json_path, md_path = save_ablation_report(report, args.output_dir)
    failed_runs = sum(
        result.status != "completed"
        for profile in report.profiles
        for result in profile.benchmark.results
    )
    print(
        f"profiles={len(report.profiles)} failed_runs={failed_runs} "
        f"json={json_path} markdown={md_path}"
    )
    return 0 if failed_runs == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 DeepScout Ablation Matrix。")
    parser.add_argument("--corpus", default="benchmarks/corpora/core.json")
    parser.add_argument("--matrix", default="benchmarks/ablations/core.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/ablation-latest"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--research-token-usd-per-million", type=float, default=None)
    parser.add_argument("--search-usd-per-1000-calls", type=float, default=None)
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
