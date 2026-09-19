"""显著性检验 JSON/CSV/Markdown/SVG 报告。"""
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import math
from html import escape
from pathlib import Path

from deepscout.evaluation.significance import (
    SignificanceComparison,
    SignificanceReport,
)

GLOBAL_SCOPE = "profile_across_cases"
CHART_METRICS = (
    ("quality_proxy_score", "Quality proxy"),
    ("citation_coverage", "Citation coverage"),
    ("search_calls", "Search calls"),
    ("wall_seconds", "Wall seconds"),
)


def _rows(report: SignificanceReport):
    for item in report.comparisons:
        yield item.model_dump(mode="json")


def write_significance_csv(report: SignificanceReport, path: Path) -> None:
    fieldnames = list(next(iter(_rows(report)), {}).keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_rows(report))


def _effect_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_significance_markdown(report: SignificanceReport) -> str:
    global_rows = [item for item in report.comparisons if item.scope == GLOBAL_SCOPE]
    lines = [
        "# DeepScout Significance Analysis",
        "",
        f"- Matrix: {report.matrix_name} {report.matrix_version}",
        f"- Corpus: {report.corpus_name} {report.corpus_version}",
        f"- Repetitions: {report.repetitions}",
        f"- Baseline: {report.baseline_profile}",
        f"- Alpha: {report.alpha:.3f}",
        f"- Primary test: {report.primary_test}",
        f"- Secondary test: {report.secondary_test}",
        f"- Multiple correction: {report.multiple_correction}",
        f"- Correction family: {report.correction_family}",
        f"- Minimum non-zero paired units for theoretical Holm reachability: "
        f"{report.minimum_nonzero_pairs_for_holm}",
        "",
        "全局比较以 case 为统计单元：先对每个 case 的 repetitions 求配对均值差，"
        "再跨 case 做显著性检验，避免把 case×repetition 全部当成独立样本。",
        "",
        "## Global profile comparisons",
        "",
        "| Profile | Metric | N | Mean Δ | Perm p | Holm p | BH p | Wilcoxon p | Cohen dz | Rank-biserial | Cliff δ |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in global_rows:
        lines.append(
            "| "
            f"{item.profile} | {item.metric} | {item.paired_count} | {item.mean_delta:.4f} | "
            f"{item.permutation_p_value:.4f} | {item.holm_adjusted_p:.4f} | "
            f"{item.bh_adjusted_p:.4f} | {item.wilcoxon_p_value:.4f} | "
            f"{_effect_text(item.cohen_dz)} | {item.matched_rank_biserial:.3f} | "
            f"{_effect_text(item.cliffs_delta)} |"
        )

    impossible = [
        item
        for item in global_rows
        if item.minimum_attainable_p > report.alpha or item.minimum_reportable_holm_p > report.alpha
    ]
    lines.extend(["", "## Resolution limits", ""])
    if impossible:
        lines.append(
            "以下 exact sign-flip 比较受样本数限制，其理论最小双侧 p 值仍高于 alpha；"
            "不能把‘未显著’解释为‘没有效应’："
        )
        lines.append("")
        lines.append("| Profile | Metric | Non-zero pairs | Min raw p | Family | Min Holm p |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for item in impossible:
            lines.append(
                f"| {item.profile} | {item.metric} | {item.nonzero_pairs} | "
                f"{item.minimum_attainable_p:.4f} | {item.minimum_reportable_p:.4f} | "
                f"{item.correction_family_size} | {item.minimum_reportable_holm_p:.4f} |"
            )
    else:
        lines.append("当前全局比较不存在由 exact p-value 分辨率单独导致的 alpha 不可达项。")
    lines.extend(
        [
            "",
            "## Interpretation notes",
            "",
            "- Holm-adjusted permutation p-value 是主要确认性结果；BH-adjusted p-value 作为 FDR 视角补充。",
            "- Wilcoxon signed-rank 是次要稳健性检查。",
            "- Cohen's dz 与 matched rank-biserial 使用配对差值；Cliff's delta 明确忽略配对结构，仅作补充。",
            "- `profile_case` 行用于固定 Case 的 repetition-level 分析；样本很小时 p-value 分辨率会很粗。",
            "- p-value 不代表效应大小，实际判断应同时查看 paired delta CI 与效应量。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _global_chart_rows(report: SignificanceReport) -> list[SignificanceComparison]:
    metrics = {metric for metric, _ in CHART_METRICS}
    return [
        item for item in report.comparisons if item.scope == GLOBAL_SCOPE and item.metric in metrics
    ]


def _signed_effect_svg(report: SignificanceReport) -> str:
    rows = [item for item in _global_chart_rows(report) if item.cohen_dz is not None]
    width = 1000
    row_height = 34
    height = 90 + row_height * max(1, len(rows))
    left = 300
    right = 70
    half = (width - left - right) / 2
    max_abs = max((abs(item.cohen_dz or 0.0) for item in rows), default=1.0) or 1.0
    center = left + half
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="32" font-family="sans-serif" font-size="22" font-weight="600">Global paired effect sizes — Cohen dz</text>',
        f'<line x1="{center:.1f}" y1="58" x2="{center:.1f}" y2="{height - 20}" stroke="#111827"/>',
    ]
    labels = dict(CHART_METRICS)
    for index, item in enumerate(rows):
        y = 65 + index * row_height
        value = item.cohen_dz or 0.0
        extent = abs(value) / max_abs * half
        x = center if value >= 0 else center - extent
        label = f"{item.profile} / {labels.get(item.metric, item.metric)}"
        parts.extend(
            [
                f'<text x="{left - 12}" y="{y + 15}" text-anchor="end" font-family="sans-serif" font-size="12">{escape(label)}</text>',
                f'<rect x="{x:.1f}" y="{y}" width="{extent:.1f}" height="18" fill="#64748b" rx="2"/>',
                f'<text x="{center + (8 if value >= 0 else -8):.1f}" y="{y + 14}" '
                f'text-anchor="{"start" if value >= 0 else "end"}" font-family="sans-serif" font-size="11">{value:.3f}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _holm_p_svg(report: SignificanceReport) -> str:
    rows = _global_chart_rows(report)
    width = 1000
    row_height = 34
    height = 90 + row_height * max(1, len(rows))
    left = 300
    right = 70
    plot_width = width - left - right
    alpha_score = -math.log10(report.alpha)
    max_score = max(
        [alpha_score * 1.25] + [-math.log10(max(item.holm_adjusted_p, 1e-12)) for item in rows]
    )
    threshold_x = left + alpha_score / max_score * plot_width
    labels = dict(CHART_METRICS)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="24" y="32" font-family="sans-serif" font-size="22" font-weight="600">Global Holm-adjusted significance</text>',
        f'<line x1="{threshold_x:.1f}" y1="58" x2="{threshold_x:.1f}" y2="{height - 20}" stroke="#b91c1c" stroke-dasharray="5 4"/>',
    ]
    for index, item in enumerate(rows):
        y = 65 + index * row_height
        score = -math.log10(max(item.holm_adjusted_p, 1e-12))
        extent = score / max_score * plot_width
        label = f"{item.profile} / {labels.get(item.metric, item.metric)}"
        parts.extend(
            [
                f'<text x="{left - 12}" y="{y + 15}" text-anchor="end" font-family="sans-serif" font-size="12">{escape(label)}</text>',
                f'<rect x="{left}" y="{y}" width="{extent:.1f}" height="18" fill="#64748b" rx="2"/>',
                f'<text x="{min(width - 12, left + extent + 8):.1f}" y="{y + 14}" font-family="sans-serif" font-size="11">p={item.holm_adjusted_p:.3g}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def save_significance_report(
    report: SignificanceReport,
    output_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    charts = directory / "charts"
    charts.mkdir(parents=True, exist_ok=True)

    json_path = directory / "significance.json"
    csv_path = directory / "significance.csv"
    md_path = directory / "significance.md"
    effect_path = charts / "significance_effect_sizes.svg"
    pvalue_path = charts / "significance_holm_p.svg"

    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_significance_csv(report, csv_path)
    md_path.write_text(render_significance_markdown(report), encoding="utf-8")
    effect_path.write_text(_signed_effect_svg(report), encoding="utf-8")
    pvalue_path.write_text(_holm_p_svg(report), encoding="utf-8")
    return {
        "json": json_path,
        "csv": csv_path,
        "markdown": md_path,
        "effect_svg": effect_path,
        "holm_p_svg": pvalue_path,
    }
