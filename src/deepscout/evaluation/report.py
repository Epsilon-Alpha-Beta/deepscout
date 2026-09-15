"""Benchmark 聚合报告与 Markdown 渲染。"""

import json
from datetime import UTC, datetime
from pathlib import Path

from deepscout.evaluation.models import (
    BenchmarkCorpus,
    BenchmarkReport,
    BenchmarkRunResult,
    BenchmarkSummary,
)


def build_report(corpus: BenchmarkCorpus, results: list[BenchmarkRunResult]) -> BenchmarkReport:
    total = len(results)
    completed = sum(result.status == "completed" for result in results)
    passed = sum(result.passed for result in results)
    quality = sum(result.metrics.quality_proxy_score for result in results)
    citation = sum(result.metrics.citation_coverage for result in results)
    diversity = sum(result.metrics.source_diversity_ratio for result in results)
    known_costs = [
        result.metrics.estimated_tracked_cost_usd
        for result in results
        if result.metrics.estimated_tracked_cost_usd is not None
    ]
    total_cost = sum(known_costs) if len(known_costs) == total and total else None
    summary = BenchmarkSummary(
        total_cases=total,
        completed_cases=completed,
        passed_cases=passed,
        pass_rate=passed / total if total else 0.0,
        average_quality_proxy_score=quality / total if total else 0.0,
        average_citation_coverage=citation / total if total else 0.0,
        average_source_diversity_ratio=diversity / total if total else 0.0,
        total_replans=sum(result.metrics.replan_count for result in results),
        total_evidence_count=sum(result.metrics.evidence_count for result in results),
        total_search_calls=sum(result.metrics.search_calls for result in results),
        total_research_tokens=sum(result.metrics.research_tokens for result in results),
        total_worker_seconds=sum(result.metrics.worker_seconds for result in results),
        total_wall_seconds=sum(result.metrics.wall_seconds for result in results),
        estimated_tracked_cost_usd=total_cost,
    )
    return BenchmarkReport(
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        generated_at=datetime.now(UTC).isoformat(),
        summary=summary,
        results=results,
    )


def render_markdown(report: BenchmarkReport) -> str:
    summary = report.summary
    lines = [
        f"# DeepScout Benchmark — {report.corpus_name} {report.corpus_version}",
        "",
        f"- Cases: {summary.total_cases}",
        f"- Completed: {summary.completed_cases}",
        f"- Passed expectations: {summary.passed_cases}/{summary.total_cases}",
        f"- Pass rate: {summary.pass_rate:.1%}",
        f"- Avg quality proxy: {summary.average_quality_proxy_score:.3f}",
        f"- Avg citation coverage: {summary.average_citation_coverage:.3f}",
        f"- Avg source diversity: {summary.average_source_diversity_ratio:.3f}",
        f"- Replans: {summary.total_replans}",
        f"- Evidence items: {summary.total_evidence_count}",
        f"- Search calls: {summary.total_search_calls}",
        f"- Research tokens: {summary.total_research_tokens}",
        f"- Worker seconds: {summary.total_worker_seconds:.3f}",
        f"- Wall seconds: {summary.total_wall_seconds:.3f}",
        "",
        "| Case | Status | Pass | Quality | Citation | Searches | Tokens | Wall(s) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in report.results:
        metrics = result.metrics
        lines.append(
            "| "
            f"{result.case.case_id} | {result.status} | {'yes' if result.passed else 'no'} | "
            f"{metrics.quality_proxy_score:.3f} | {metrics.citation_coverage:.3f} | "
            f"{metrics.search_calls} | {metrics.research_tokens} | {metrics.wall_seconds:.3f} |"
        )
    return "\n".join(lines) + "\n"


def save_report(report: BenchmarkReport, output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    md_path = directory / "report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
