"""Benchmark 质量审计报告输出。"""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

from deepscout.evaluation.models import BenchmarkCorpus
from deepscout.evaluation.quality import BenchmarkQualityReport


def render_quality_markdown(report: BenchmarkQualityReport) -> str:
    snap = report.snapshot
    lines = [
        f"# Benchmark Quality Audit — {report.corpus_name} {report.corpus_version}",
        "",
        f"- Status: **{'PASS' if report.passed else 'FAIL'}**",
        f"- Cases: {snap.case_count}",
        f"- Topic groups: {snap.topic_group_count}",
        f"- Source policy coverage: {snap.source_policy_case_count}/{snap.case_count}",
        f"- Gold rubric coverage: {snap.rubric_case_count}/{snap.case_count}",
        f"- Freshness-required cases: {snap.freshness_case_count}/{snap.case_count}",
        f"- Errors: {report.error_count}",
        f"- Warnings: {report.warning_count}",
        "",
        "## Topic balance",
        "",
        "| Topic group | Cases | Share |",
        "| --- | ---: | ---: |",
    ]
    for topic, count in snap.topic_counts.items():
        lines.append(f"| {topic} | {count} | {count / snap.case_count:.1%} |")
    lines.extend(
        [
            "",
            "## Difficulty balance",
            "",
            "| Difficulty | Cases | Share |",
            "| --- | ---: | ---: |",
        ]
    )
    for difficulty, count in snap.difficulty_counts.items():
        lines.append(f"| {difficulty} | {count} | {count / snap.case_count:.1%} |")
    lines.extend(["", "## Issues", ""])
    if not report.issues:
        lines.append("No quality-control issues detected.")
    else:
        lines.extend(
            [
                "| Severity | Code | Case | Message |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in report.issues:
            lines.append(
                f"| {item.severity} | {item.code} | {item.case_id or '-'} | {item.message} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "此审计只验证 Benchmark 设计资产的静态质量门槛；"
            "不等同于真实 Provider 输出的事实正确率。",
            "人工 gold rubric 在真实运行后仍需由独立评审者按 Case 评分。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_cases_csv(corpus: BenchmarkCorpus, path: Path) -> None:
    fields = [
        "case_id",
        "category",
        "topic_group",
        "difficulty",
        "preferred_domains",
        "min_primary_sources",
        "freshness_required",
        "max_age_days",
        "required_points",
        "critical_errors",
        "rubric_pass_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in corpus.cases:
            source = case.source_policy
            rubric = case.gold_rubric
            writer.writerow(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "topic_group": case.topic_group,
                    "difficulty": case.difficulty,
                    "preferred_domains": ";".join(source.preferred_domains) if source else "",
                    "min_primary_sources": source.min_primary_sources if source else "",
                    "freshness_required": source.freshness_required if source else "",
                    "max_age_days": source.max_age_days if source else "",
                    "required_points": " | ".join(rubric.required_points) if rubric else "",
                    "critical_errors": " | ".join(rubric.critical_errors) if rubric else "",
                    "rubric_pass_score": rubric.pass_score if rubric else "",
                }
            )


def _bar_svg(title: str, counts: dict[str, int]) -> str:
    width = 960
    row_h = 38
    height = 80 + max(1, len(counts)) * row_h
    left, right = 250, 60
    max_count = max(counts.values(), default=1)
    plot_w = width - left - right
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="sans-serif" font-size="22" '
        f'font-weight="600">{escape(title)}</text>',
    ]
    for idx, (label, count) in enumerate(counts.items()):
        y = 58 + idx * row_h
        extent = count / max_count * plot_w
        parts.extend(
            [
                f'<text x="{left - 12}" y="{y + 15}" text-anchor="end" '
                f'font-family="sans-serif" font-size="12">{escape(label)}</text>',
                f'<rect x="{left}" y="{y}" width="{extent:.1f}" height="18" '
                'fill="#64748b" rx="2"/>',
                f'<text x="{left + extent + 8:.1f}" y="{y + 14}" '
                f'font-family="sans-serif" font-size="11">{count}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def save_quality_report(
    corpus: BenchmarkCorpus,
    report: BenchmarkQualityReport,
    output_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(output_dir)
    charts = directory / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "quality.json",
        "markdown": directory / "quality.md",
        "cases_csv": directory / "cases.csv",
        "topic_chart": charts / "topic_balance.svg",
        "difficulty_chart": charts / "difficulty_balance.svg",
    }
    paths["json"].write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_quality_markdown(report), encoding="utf-8")
    write_cases_csv(corpus, paths["cases_csv"])
    paths["topic_chart"].write_text(
        _bar_svg("Benchmark topic balance", report.snapshot.topic_counts), encoding="utf-8"
    )
    paths["difficulty_chart"].write_text(
        _bar_svg("Benchmark difficulty balance", report.snapshot.difficulty_counts),
        encoding="utf-8",
    )
    return paths
