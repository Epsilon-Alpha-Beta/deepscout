"""运行 DeepScout Phase 4 benchmark corpus。"""

import argparse
import asyncio
from pathlib import Path

from deepscout.evaluation.models import BenchmarkPricing
from deepscout.evaluation.report import build_report, save_report
from deepscout.evaluation.runner import load_corpus, run_corpus
from deepscout.graph.builder import build_graph


async def _run(args: argparse.Namespace) -> int:
    corpus = load_corpus(args.corpus)
    if args.validate_only:
        print(
            f"corpus={corpus.name} version={corpus.version} cases={len(corpus.cases)} status=valid"
        )
        return 0

    pricing = BenchmarkPricing(
        research_token_usd_per_million=args.research_token_usd_per_million,
        search_usd_per_1000_calls=args.search_usd_per_1000_calls,
    )
    results = await run_corpus(
        build_graph(),
        corpus,
        limit=args.limit,
        pricing=pricing,
    )
    report = build_report(corpus, results)
    json_path, md_path = save_report(report, args.output_dir)
    print(
        f"cases={report.summary.total_cases} passed={report.summary.passed_cases} "
        f"json={json_path} markdown={md_path}"
    )
    return 0 if report.summary.passed_cases == report.summary.total_cases else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 DeepScout Benchmark Corpus。")
    parser.add_argument(
        "--corpus",
        default="benchmarks/corpora/core.json",
        help="Benchmark corpus JSON 路径。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/latest"),
        help="JSON/Markdown 报告输出目录。",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--research-token-usd-per-million", type=float, default=None)
    parser.add_argument("--search-usd-per-1000-calls", type=float, default=None)
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
