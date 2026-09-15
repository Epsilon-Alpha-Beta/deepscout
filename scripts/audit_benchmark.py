"""静态审计 DeepScout Benchmark Case 质量控制元数据与 Corpus balance。"""

import argparse
from pathlib import Path

from deepscout.evaluation.quality import BenchmarkQualityPolicy, audit_benchmark_corpus
from deepscout.evaluation.quality_report import save_quality_report
from deepscout.evaluation.runner import load_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description="审计 Benchmark Case 质量控制层。")
    parser.add_argument("--corpus", default="benchmarks/corpora/core.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/quality-audit-latest"),
    )
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败。")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    report = audit_benchmark_corpus(corpus, BenchmarkQualityPolicy())
    print(
        f"corpus={corpus.name} version={corpus.version} cases={len(corpus.cases)} "
        f"topics={report.snapshot.topic_group_count} "
        f"freshness={report.snapshot.freshness_case_count} "
        f"errors={report.error_count} warnings={report.warning_count} "
        f"status={'valid' if report.passed else 'invalid'}"
    )
    if args.validate_only:
        raise SystemExit(1 if (not report.passed or (args.strict and report.warning_count)) else 0)

    paths = save_quality_report(corpus, report, args.output_dir)
    print(f"json={paths['json']} markdown={paths['markdown']} cases={paths['cases_csv']}")
    raise SystemExit(1 if (not report.passed or (args.strict and report.warning_count)) else 0)


if __name__ == "__main__":
    main()
