"""重复实验 JSON/CSV/Markdown/SVG 报告生成。"""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from deepscout.evaluation.repeated import (
    RepeatedExperimentReport,
    RepeatedScopeStatistics,
)

CHART_METRICS = (
    ("quality_proxy_score", "Quality proxy"),
    ("citation_coverage", "Citation coverage"),
    ("search_calls", "Search calls"),
    ("research_tokens", "Research tokens"),
    ("wall_seconds", "Wall seconds"),
)

DELTA_CHART_METRICS = (
    ("quality_proxy_score", "Quality proxy paired delta"),
    ("search_calls", "Search calls paired delta"),
    ("wall_seconds", "Wall seconds paired delta"),
)


def _ci_text(scope: RepeatedScopeStatistics, metric: str) -> str:
    stats = scope.metrics.get(metric)
    if stats is None:
        return "n/a"
    return f"{stats.mean:.3f} [{stats.ci_low:.3f}, {stats.ci_high:.3f}]"


def _stats_rows(scopes: list[RepeatedScopeStatistics]):
    for scope in scopes:
        for metric, stats in scope.metrics.items():
            yield {
                "scope": scope.scope,
                "profile": scope.profile,
                "baseline": scope.baseline or "",
                "case_id": scope.case_id or "",
                "attempted_units": scope.attempted_units,
                "completed_units": scope.completed_units,
                "error_units": scope.error_units,
                "interrupted_units": scope.interrupted_units,
                "completion_rate": scope.completion_rate,
                "overall_pass_rate": scope.overall_pass_rate,
                "metric": metric,
                **stats.model_dump(),
            }


def write_runs_csv(report: RepeatedExperimentReport, path: Path) -> None:
    fieldnames = [
        "repetition",
        "execution_order",
        "profile_order",
        "profile",
        "case_id",
        "status",
        "passed",
        "error_type",
        "quality_proxy_score",
        "citation_coverage",
        "source_diversity_ratio",
        "replan_count",
        "evidence_count",
        "search_calls",
        "research_tokens",
        "worker_seconds",
        "wall_seconds",
        "estimated_tracked_cost_usd",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in report.runs:
            result = record.result
            metrics = result.metrics
            completed = result.status == "completed"
            error_type = result.error.split(":", 1)[0] if result.error else ""
            writer.writerow(
                {
                    "repetition": record.repetition,
                    "execution_order": record.execution_order,
                    "profile_order": record.profile_order,
                    "profile": record.profile,
                    "case_id": result.case.case_id,
                    "status": result.status,
                    "passed": result.passed,
                    "error_type": error_type,
                    "quality_proxy_score": metrics.quality_proxy_score if completed else "",
                    "citation_coverage": metrics.citation_coverage if completed else "",
                    "source_diversity_ratio": metrics.source_diversity_ratio if completed else "",
                    "replan_count": metrics.replan_count if completed else "",
                    "evidence_count": metrics.evidence_count if completed else "",
                    "search_calls": metrics.search_calls if completed else "",
                    "research_tokens": metrics.research_tokens if completed else "",
                    "worker_seconds": metrics.worker_seconds if completed else "",
                    "wall_seconds": metrics.wall_seconds if completed else "",
                    "estimated_tracked_cost_usd": (
                        metrics.estimated_tracked_cost_usd if completed else ""
                    ),
                }
            )


def write_statistics_csv(
    scopes: list[RepeatedScopeStatistics],
    path: Path,
) -> None:
    fieldnames = [
        "scope",
        "profile",
        "baseline",
        "case_id",
        "attempted_units",
        "completed_units",
        "error_units",
        "interrupted_units",
        "completion_rate",
        "overall_pass_rate",
        "metric",
        "count",
        "mean",
        "std",
        "median",
        "p50",
        "p95",
        "ci_low",
        "ci_high",
        "confidence_level",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_stats_rows(scopes))


def render_repeated_markdown(report: RepeatedExperimentReport) -> str:
    lines = [
        f"# DeepScout Repeated Ablation — {report.matrix_name} {report.matrix_version}",
        "",
        f"- Corpus: {report.corpus_name} {report.corpus_version}",
        f"- Baseline: {report.baseline_profile}",
        f"- Repetitions: {report.repetitions}",
        f"- Profile order: {report.order_strategy}",
        f"- CI: {report.confidence_level:.1%} {report.ci_method}",
        f"- Bootstrap resamples: {report.bootstrap_resamples}",
        f"- Bootstrap seed: {report.bootstrap_seed}",
        "",
        "数值统计仅使用 completed runs；error/interrupted 仍保留在原始 run 与完成率中，"
        "不会静默丢弃。",
        "",
        "## Profile statistics",
        "",
        "| Profile | Completion | Pass | Quality mean [CI] | Citation mean [CI] | "
        "Searches mean [CI] | Wall mean [CI] |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for scope in report.profile_statistics:
        completion = scope.completion_rate if scope.completion_rate is not None else 0.0
        pass_rate = scope.overall_pass_rate if scope.overall_pass_rate is not None else 0.0
        lines.append(
            "| "
            f"{scope.profile} | {completion:.1%} | {pass_rate:.1%} | "
            f"{_ci_text(scope, 'quality_proxy_score')} | "
            f"{_ci_text(scope, 'citation_coverage')} | "
            f"{_ci_text(scope, 'search_calls')} | "
            f"{_ci_text(scope, 'wall_seconds')} |"
        )

    lines.extend(
        [
            "",
            "## Full profile distributions",
            "",
            "| Profile | Metric | N | Mean | Std | Median | P50 | P95 | CI |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for scope in report.profile_statistics:
        for metric, stats in scope.metrics.items():
            lines.append(
                "| "
                f"{scope.profile} | {metric} | {stats.count} | {stats.mean:.4f} | "
                f"{stats.std:.4f} | {stats.median:.4f} | {stats.p50:.4f} | "
                f"{stats.p95:.4f} | [{stats.ci_low:.4f}, {stats.ci_high:.4f}] |"
            )

    lines.extend(
        [
            "",
            "## Paired delta vs baseline",
            "",
            "Delta 以同一 `(repetition, case)` 的 profile − baseline 计算，再对配对差值做统计。",
            "",
            "| Profile | Quality Δ mean [CI] | Citation Δ mean [CI] | "
            "Searches Δ mean [CI] | Tokens Δ mean [CI] | Wall Δ mean [CI] |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for scope in report.profile_delta_statistics:
        lines.append(
            "| "
            f"{scope.profile} | {_ci_text(scope, 'quality_proxy_score')} | "
            f"{_ci_text(scope, 'citation_coverage')} | "
            f"{_ci_text(scope, 'search_calls')} | "
            f"{_ci_text(scope, 'research_tokens')} | "
            f"{_ci_text(scope, 'wall_seconds')} |"
        )

    lines.extend(
        [
            "",
            "## Distribution fields",
            "",
            "每个统计指标均包含 `count / mean / std / median / p50 / p95 / ci_low / ci_high`。",
            "完整 profile/case 级统计见 `statistics.csv`，配对差分见 `deltas.csv`。",
            "",
            "## Charts",
            "",
        ]
    )
    for metric, label in CHART_METRICS:
        lines.append(f"- [{label}](charts/{metric}.svg)")
    for metric, label in DELTA_CHART_METRICS:
        lines.append(f"- [{label}](charts/delta_{metric}.svg)")
    return "\n".join(lines).rstrip() + "\n"


def _svg_chart(
    scopes: list[RepeatedScopeStatistics],
    metric: str,
    label: str,
) -> str:
    rows = []
    for scope in scopes:
        stats = scope.metrics.get(metric)
        if stats is not None:
            rows.append((scope.profile, stats))
    width = 960
    row_height = 54
    height = 110 + row_height * max(1, len(rows))
    left = 190
    right = 70
    plot_width = width - left - right
    max_value = max((stats.ci_high for _, stats in rows), default=1.0)
    max_value = max(max_value, 1e-12)

    confidence = rows[0][1].confidence_level if rows else 0.95
    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    )
    title = (
        '<text x="24" y="34" font-family="sans-serif" font-size="22" font-weight="600">'
        f"{escape(label)} — mean and {confidence:.0%} CI</text>"
    )
    subtitle = (
        '<text x="24" y="58" font-family="sans-serif" font-size="13" fill="#555">'
        "Repeated completed runs; whiskers show bootstrap CI of the mean.</text>"
    )
    parts = [svg_open, '<rect width="100%" height="100%" fill="white"/>', title, subtitle]
    for index, (profile, stats) in enumerate(rows):
        y = 90 + index * row_height
        mean_x = left + stats.mean / max_value * plot_width
        low_x = left + stats.ci_low / max_value * plot_width
        high_x = left + stats.ci_high / max_value * plot_width
        bar_width = max(1.0, mean_x - left)
        profile_text = (
            f'<text x="{left - 12}" y="{y + 17}" text-anchor="end" '
            f'font-family="sans-serif" font-size="13">{escape(profile)}</text>'
        )
        bar = (
            f'<rect x="{left}" y="{y}" width="{bar_width:.2f}" height="22" fill="#64748b" rx="3"/>'
        )
        whisker = (
            f'<line x1="{low_x:.2f}" y1="{y + 11}" x2="{high_x:.2f}" y2="{y + 11}" '
            'stroke="#111827" stroke-width="2"/>'
        )
        low_tick = (
            f'<line x1="{low_x:.2f}" y1="{y + 5}" x2="{low_x:.2f}" y2="{y + 17}" stroke="#111827"/>'
        )
        high_tick = (
            f'<line x1="{high_x:.2f}" y1="{y + 5}" x2="{high_x:.2f}" y2="{y + 17}" '
            'stroke="#111827"/>'
        )
        mean_text = (
            f'<text x="{min(width - 10, mean_x + 8):.2f}" y="{y + 17}" '
            f'font-family="sans-serif" font-size="12">{stats.mean:.3f}</text>'
        )
        parts.extend([profile_text, bar, whisker, low_tick, high_tick, mean_text])
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def save_repeated_report(
    report: RepeatedExperimentReport,
    output_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    charts_dir = directory / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    json_path = directory / "repeated.json"
    markdown_path = directory / "report.md"
    runs_path = directory / "runs.csv"
    statistics_path = directory / "statistics.csv"
    deltas_path = directory / "deltas.csv"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_repeated_markdown(report), encoding="utf-8")
    write_runs_csv(report, runs_path)
    write_statistics_csv(
        [*report.profile_statistics, *report.profile_case_statistics],
        statistics_path,
    )
    write_statistics_csv(
        [*report.profile_delta_statistics, *report.profile_case_delta_statistics],
        deltas_path,
    )

    paths = {
        "json": json_path,
        "markdown": markdown_path,
        "runs_csv": runs_path,
        "statistics_csv": statistics_path,
        "deltas_csv": deltas_path,
    }
    for metric, label in CHART_METRICS:
        chart_path = charts_dir / f"{metric}.svg"
        chart_path.write_text(
            _svg_chart(report.profile_statistics, metric, label),
            encoding="utf-8",
        )
        paths[f"chart_{metric}"] = chart_path
    for metric, label in DELTA_CHART_METRICS:
        chart_path = charts_dir / f"delta_{metric}.svg"
        chart_path.write_text(
            _svg_delta_chart(report.profile_delta_statistics, metric, label),
            encoding="utf-8",
        )
        paths[f"chart_delta_{metric}"] = chart_path
    return paths


def _svg_delta_chart(
    scopes: list[RepeatedScopeStatistics],
    metric: str,
    label: str,
) -> str:
    rows = []
    for scope in scopes:
        stats = scope.metrics.get(metric)
        if stats is not None:
            rows.append((scope.profile, stats))
    width = 960
    row_height = 54
    height = 110 + row_height * max(1, len(rows))
    left = 190
    right = 70
    plot_width = width - left - right
    low = min([0.0, *(stats.ci_low for _, stats in rows)])
    high = max([0.0, *(stats.ci_high for _, stats in rows)])
    if high == low:
        high = low + 1.0

    def x(value: float) -> float:
        return left + (value - low) / (high - low) * plot_width

    zero_x = x(0.0)
    confidence = rows[0][1].confidence_level if rows else 0.95
    svg_open = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    )
    title = (
        '<text x="24" y="34" font-family="sans-serif" font-size="22" font-weight="600">'
        f"{escape(label)} — mean and {confidence:.0%} CI</text>"
    )
    subtitle = (
        '<text x="24" y="58" font-family="sans-serif" font-size="13" fill="#555">'
        "Paired profile minus baseline; whiskers show bootstrap CI of the mean.</text>"
    )
    parts = [
        svg_open,
        '<rect width="100%" height="100%" fill="white"/>',
        title,
        subtitle,
        (
            f'<line x1="{zero_x:.2f}" y1="76" x2="{zero_x:.2f}" y2="{height - 14}" '
            'stroke="#94a3b8" stroke-width="1"/>'
        ),
    ]
    for index, (profile, stats) in enumerate(rows):
        y = 90 + index * row_height
        mean_x = x(stats.mean)
        low_x = x(stats.ci_low)
        high_x = x(stats.ci_high)
        bar_x = min(zero_x, mean_x)
        bar_width = max(1.0, abs(mean_x - zero_x))
        parts.extend(
            [
                (
                    f'<text x="{left - 12}" y="{y + 17}" text-anchor="end" '
                    f'font-family="sans-serif" font-size="13">{escape(profile)}</text>'
                ),
                (
                    f'<rect x="{bar_x:.2f}" y="{y}" width="{bar_width:.2f}" height="22" '
                    'fill="#64748b" rx="3"/>'
                ),
                (
                    f'<line x1="{low_x:.2f}" y1="{y + 11}" x2="{high_x:.2f}" '
                    f'y2="{y + 11}" stroke="#111827" stroke-width="2"/>'
                ),
                (
                    f'<text x="{mean_x + 8:.2f}" y="{y + 17}" font-family="sans-serif" '
                    f'font-size="12">{stats.mean:+.3f}</text>'
                ),
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
