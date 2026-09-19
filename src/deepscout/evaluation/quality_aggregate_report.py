"""运行后质量聚合 JSON/CSV/Markdown/SVG 报告。"""
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

from deepscout.evaluation.quality_aggregate import (
    QualityDeltaStatistics,
    QualityScopeStatistics,
    RuntimeQualityAggregateReport,
)
from deepscout.evaluation.significance_report import (
    render_significance_markdown,
    write_significance_csv,
)

PROFILE_CHARTS = (
    ("source_policy_pass", "Source policy compliance"),
    ("human_gold_score", "Human gold score"),
)
DELTA_CHARTS = (("human_gold_score", "Human gold paired delta"),)


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _ci_text(scope: QualityScopeStatistics, metric: str) -> str:
    stats = scope.metrics.get(metric)
    if stats is None:
        return "n/a"
    return f"{stats.mean:.3f} [{stats.ci_low:.3f}, {stats.ci_high:.3f}]"


def _delta_ci_text(scope: QualityDeltaStatistics, metric: str) -> str:
    stats = scope.metrics.get(metric)
    if stats is None:
        return "n/a"
    return f"{stats.mean:.3f} [{stats.ci_low:.3f}, {stats.ci_high:.3f}]"


def render_runtime_quality_markdown(report: RuntimeQualityAggregateReport) -> str:
    lines = [
        f"# DeepScout Runtime Quality Aggregate — {report.matrix_name} {report.matrix_version}",
        "",
        f"- Corpus: {report.corpus_name} {report.corpus_version}",
        f"- Baseline: {report.baseline_profile}",
        f"- Repetitions: {report.repetitions}",
        f"- CI: {report.confidence_level:.1%} percentile bootstrap mean",
        "",
        "原始 Research run 保持不可变；来源合规和人工盲评通过 sidecar 按 ",
        "(profile, repetition, case_id) 绑定。",
        "",
        "## Profile quality",
        "",
        "| Profile | Source obs | Source evaluable | Compliance | Human coverage | Gold pass | Gold mean [CI] | Pass agreement | κ | Weighted κ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for scope in report.profile_statistics:
        agreement = scope.reviewer_agreement
        lines.append(
            f"| {scope.profile} | {_fmt_rate(scope.source_observation_coverage)} | "
            f"{_fmt_rate(scope.source_evaluable_rate)} | {_fmt_rate(scope.source_compliance_rate)} | "
            f"{_fmt_rate(scope.human_review_coverage)} | {_fmt_rate(scope.human_gold_pass_rate)} | "
            f"{_ci_text(scope, 'human_gold_score')} | "
            f"{_fmt_rate(agreement.pass_agreement_rate)} | "
            f"{agreement.cohen_kappa if agreement.cohen_kappa is not None else 'n/a'} | "
            f"{agreement.weighted_kappa if agreement.weighted_kappa is not None else 'n/a'} |"
        )

    lines.extend(
        [
            "",
            "## Human gold paired delta vs baseline",
            "",
            "只使用 profile 与 baseline 在同一 (repetition, case) 上都存在 resolved final gold score 的配对单元。",
            "",
            "| Profile | N | Gold Δ mean [CI] |",
            "| --- | ---: | --- |",
        ]
    )
    for scope in report.profile_delta_statistics:
        stats = scope.metrics.get("human_gold_score")
        lines.append(
            f"| {scope.profile} | {stats.count if stats else 0} | "
            f"{_delta_ci_text(scope, 'human_gold_score')} |"
        )

    lines.extend(
        [
            "",
            "## Missingness semantics",
            "",
            "- source_observation_coverage 以 completed runs 为分母。",
            "- freshness metadata 不足时 source policy 是 unverifiable，不会填成失败或通过。",
            "- human_review_coverage 只计算 resolved final outcomes；未评审/待仲裁不填 0。",
            "- reviewer κ/weighted κ 只基于确实存在两份 primary reviews 的 blind items。",
            "- human gold significance 只使用 resolved paired scores，不对缺失值做插补。",
            "",
            "## Charts",
            "",
        ]
    )
    for metric, label in PROFILE_CHARTS:
        lines.append(f"- [{label}](charts/{metric}.svg)")
    for metric, label in DELTA_CHARTS:
        lines.append(f"- [{label}](charts/delta_{metric}.svg)")
    if report.human_gold_significance is not None:
        lines.append("- [Human gold significance](human_gold_significance.md)")
    return "\n".join(lines).rstrip() + "\n"


def write_quality_observations_csv(report: RuntimeQualityAggregateReport, path: Path) -> None:
    fieldnames = [
        "repetition",
        "run_status",
        "profile",
        "case_id",
        "source_policy_observed",
        "source_policy_evaluable",
        "source_policy_passed",
        "freshness_metadata_coverage",
        "blind_item_id",
        "human_review_resolved",
        "human_gold_score",
        "human_gold_passed",
        "reviewer_pass_agreement",
        "reviewer_score_gap",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in report.observations:
            writer.writerow(item.model_dump())


def write_quality_statistics_csv(scopes: list[QualityScopeStatistics], path: Path) -> None:
    fieldnames = [
        "scope",
        "profile",
        "case_id",
        "completed_run_count",
        "source_observation_count",
        "source_evaluable_count",
        "source_unverifiable_count",
        "source_observation_coverage",
        "source_evaluable_rate",
        "source_compliance_rate",
        "human_assignment_count",
        "human_resolved_count",
        "human_review_coverage",
        "human_gold_pass_rate",
        "reviewer_paired_items",
        "reviewer_pass_agreement_rate",
        "reviewer_cohen_kappa",
        "reviewer_weighted_kappa",
        "reviewer_mean_score_gap",
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
        for scope in scopes:
            agreement = scope.reviewer_agreement
            metrics = scope.metrics or {"": None}
            for metric, stats in metrics.items():
                row = {
                    "scope": scope.scope,
                    "profile": scope.profile,
                    "case_id": scope.case_id or "",
                    "completed_run_count": scope.completed_run_count,
                    "source_observation_count": scope.source_observation_count,
                    "source_evaluable_count": scope.source_evaluable_count,
                    "source_unverifiable_count": scope.source_unverifiable_count,
                    "source_observation_coverage": scope.source_observation_coverage,
                    "source_evaluable_rate": scope.source_evaluable_rate,
                    "source_compliance_rate": scope.source_compliance_rate,
                    "human_assignment_count": scope.human_assignment_count,
                    "human_resolved_count": scope.human_resolved_count,
                    "human_review_coverage": scope.human_review_coverage,
                    "human_gold_pass_rate": scope.human_gold_pass_rate,
                    "reviewer_paired_items": agreement.paired_items,
                    "reviewer_pass_agreement_rate": agreement.pass_agreement_rate,
                    "reviewer_cohen_kappa": agreement.cohen_kappa,
                    "reviewer_weighted_kappa": agreement.weighted_kappa,
                    "reviewer_mean_score_gap": agreement.mean_absolute_score_gap,
                    "metric": metric,
                }
                if stats is not None:
                    row.update(stats.model_dump())
                writer.writerow(row)


def write_quality_deltas_csv(scopes: list[QualityDeltaStatistics], path: Path) -> None:
    fieldnames = [
        "scope",
        "profile",
        "baseline",
        "case_id",
        "paired_units",
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
        for scope in scopes:
            for metric, stats in scope.metrics.items():
                writer.writerow(
                    {
                        "scope": scope.scope,
                        "profile": scope.profile,
                        "baseline": scope.baseline,
                        "case_id": scope.case_id or "",
                        "paired_units": scope.paired_units,
                        "metric": metric,
                        **stats.model_dump(),
                    }
                )


def _profile_svg(scopes: list[QualityScopeStatistics], metric: str, label: str) -> str:
    rows = [(scope.profile, scope.metrics.get(metric)) for scope in scopes]
    rows = [(profile, stats) for profile, stats in rows if stats is not None]
    width = 920
    left = 190
    right = 60
    row_height = 52
    height = 100 + max(1, len(rows)) * row_height
    plot_width = width - left - right
    max_value = max((stats.ci_high for _, stats in rows), default=1.0)
    max_value = max(max_value, 1e-9)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="sans-serif" font-size="22">{escape(label)}</text>',
    ]
    for index, (profile, stats) in enumerate(rows):
        y = 70 + index * row_height
        mean_x = left + stats.mean / max_value * plot_width
        low_x = left + stats.ci_low / max_value * plot_width
        high_x = left + stats.ci_high / max_value * plot_width
        parts.extend(
            [
                f'<text x="{left - 10}" y="{y + 17}" text-anchor="end" font-family="sans-serif" font-size="13">{escape(profile)}</text>',
                f'<rect x="{left}" y="{y}" width="{max(1.0, mean_x - left):.2f}" height="22" fill="#64748b" rx="3"/>',
                f'<line x1="{low_x:.2f}" y1="{y + 11}" x2="{high_x:.2f}" y2="{y + 11}" stroke="#111827" stroke-width="2"/>',
                f'<text x="{min(width - 50, mean_x + 8):.2f}" y="{y + 17}" font-family="sans-serif" font-size="12">{stats.mean:.3f}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _delta_svg(scopes: list[QualityDeltaStatistics], metric: str, label: str) -> str:
    rows = [(scope.profile, scope.metrics.get(metric)) for scope in scopes]
    rows = [(profile, stats) for profile, stats in rows if stats is not None]
    width = 920
    left = 190
    right = 60
    row_height = 52
    height = 100 + max(1, len(rows)) * row_height
    plot_width = width - left - right
    bound = max(
        [abs(value) for _, stats in rows for value in (stats.ci_low, stats.ci_high, stats.mean)]
        or [1.0]
    )
    bound = max(bound, 1e-9)
    zero_x = left + plot_width / 2
    scale = plot_width / (2 * bound)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="sans-serif" font-size="22">{escape(label)}</text>',
        f'<line x1="{zero_x:.2f}" y1="55" x2="{zero_x:.2f}" y2="{height - 20}" stroke="#94a3b8"/>',
    ]
    for index, (profile, stats) in enumerate(rows):
        y = 70 + index * row_height
        mean_x = zero_x + stats.mean * scale
        low_x = zero_x + stats.ci_low * scale
        high_x = zero_x + stats.ci_high * scale
        parts.extend(
            [
                f'<text x="{left - 10}" y="{y + 17}" text-anchor="end" font-family="sans-serif" font-size="13">{escape(profile)}</text>',
                f'<line x1="{low_x:.2f}" y1="{y + 11}" x2="{high_x:.2f}" y2="{y + 11}" stroke="#111827" stroke-width="2"/>',
                f'<circle cx="{mean_x:.2f}" cy="{y + 11}" r="5" fill="#475569"/>',
                f'<text x="{min(width - 50, max(left, mean_x + 8)):.2f}" y="{y + 17}" font-family="sans-serif" font-size="12">{stats.mean:+.3f}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def save_runtime_quality_aggregate(
    report: RuntimeQualityAggregateReport, output_dir: str | Path
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    charts = directory / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "quality_aggregate.json",
        "markdown": directory / "quality_aggregate.md",
        "observations_csv": directory / "quality_observations.csv",
        "statistics_csv": directory / "quality_statistics.csv",
        "deltas_csv": directory / "human_gold_deltas.csv",
    }
    paths["json"].write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(render_runtime_quality_markdown(report), encoding="utf-8")
    write_quality_observations_csv(report, paths["observations_csv"])
    write_quality_statistics_csv(
        [*report.profile_statistics, *report.profile_case_statistics],
        paths["statistics_csv"],
    )
    write_quality_deltas_csv(
        [*report.profile_delta_statistics, *report.profile_case_delta_statistics],
        paths["deltas_csv"],
    )

    for metric, label in PROFILE_CHARTS:
        path = charts / f"{metric}.svg"
        path.write_text(_profile_svg(report.profile_statistics, metric, label), encoding="utf-8")
        paths[f"chart_{metric}"] = path
    for metric, label in DELTA_CHARTS:
        path = charts / f"delta_{metric}.svg"
        path.write_text(
            _delta_svg(report.profile_delta_statistics, metric, label), encoding="utf-8"
        )
        paths[f"chart_delta_{metric}"] = path

    if report.human_gold_significance is not None:
        significance = report.human_gold_significance
        sig_json = directory / "human_gold_significance.json"
        sig_csv = directory / "human_gold_significance.csv"
        sig_md = directory / "human_gold_significance.md"
        sig_json.write_text(significance.model_dump_json(indent=2) + "\n", encoding="utf-8")
        write_significance_csv(significance, sig_csv)
        sig_md.write_text(render_significance_markdown(significance), encoding="utf-8")
        paths["significance_json"] = sig_json
        paths["significance_csv"] = sig_csv
        paths["significance_markdown"] = sig_md
    return paths
