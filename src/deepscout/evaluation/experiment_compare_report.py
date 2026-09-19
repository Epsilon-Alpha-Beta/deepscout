"""Experiment Bundle comparison 的 JSON/CSV/Markdown 报告。"""

from __future__ import annotations

import csv
from pathlib import Path

from deepscout.evaluation.experiment_compare import ExperimentComparisonReport


def render_experiment_comparison_markdown(report: ExperimentComparisonReport) -> str:
    lines = [
        "# DeepScout Experiment Regression Comparison",
        "",
        f"- Baseline: `{report.baseline_experiment_id}`",
        f"- Candidate: `{report.candidate_experiment_id}`",
        f"- Comparable: **{report.comparable}**",
        f"- Regressions: **{report.regression_count}**",
        f"- Improvements: **{report.improvement_count}**",
    ]
    if report.incompatibilities:
        lines.extend(["", "## Incompatibilities", ""])
        lines.extend(f"- {item}" for item in report.incompatibilities)
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in report.warnings)
    if report.comparisons:
        lines.extend(
            [
                "",
                "## Metric comparison",
                "",
                "| Source | Profile | Metric | Direction | Before | After | "
                "Delta | Threshold | Status |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for item in report.comparisons:
            lines.append(
                f"| {item.source} | {item.profile} | {item.metric} | {item.direction} | "
                f"{item.before:.6g} | {item.after:.6g} | {item.delta:+.6g} | "
                f"{item.effective_threshold:.6g} | **{item.status}** |"
            )
    return "\n".join(lines).rstrip() + "\n"


def save_experiment_comparison(
    report: ExperimentComparisonReport, output_dir: str | Path
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "comparison.json",
        "markdown": directory / "comparison.md",
        "csv": directory / "comparisons.csv",
    }
    paths["json"].write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_experiment_comparison_markdown(report), encoding="utf-8")
    fields = [
        "source",
        "profile",
        "metric",
        "direction",
        "before",
        "after",
        "delta",
        "relative_change",
        "absolute_threshold",
        "relative_threshold",
        "effective_threshold",
        "status",
    ]
    with paths["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in report.comparisons:
            writer.writerow(row.model_dump())
    return paths
