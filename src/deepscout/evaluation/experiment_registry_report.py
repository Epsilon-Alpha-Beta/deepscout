"""Experiment Registry 的 JSON/CSV/Markdown/SVG dashboard。"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from html import escape
from pathlib import Path

from deepscout.evaluation.experiment_registry import (
    ExperimentRegistryEntry,
    ExperimentRegistryReport,
    ExperimentTrendPoint,
)

DASHBOARD_METRICS = (
    "quality_proxy_score",
    "wall_seconds",
    "human_gold_score",
    "source_compliance_rate",
)


def render_experiment_registry_markdown(report: ExperimentRegistryReport) -> str:
    lines = [
        "# DeepScout Experiment Registry",
        "",
        f"- Bundles: **{report.bundle_count}**",
        f"- Valid / Invalid: **{report.valid_count} / {report.invalid_count}**",
        f"- Compatibility groups: **{report.compatibility_group_count}**",
        f"- Lineage roots / Accepted / Regression: **{report.baseline_count} / "
        f"{report.accepted_count} / {report.regression_count}**",
        "",
        "## History",
        "",
        "| Time | Experiment | Group | Git | Provider / Model | Status | Baseline | "
        "Regressions | Improvements |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for item in report.entries:
        provider_model = f"{item.provider or 'n/a'} / {item.model or 'n/a'}"
        lines.append(
            f"| {item.created_at or 'n/a'} | {item.experiment_id} | "
            f"{item.compatibility_key or 'n/a'} | {(item.git_sha or 'n/a')[:12]} | "
            f"{provider_model} | **{item.status}** | "
            f"{item.baseline_experiment_id or '-'} | {item.regression_count} | "
            f"{item.improvement_count} |"
        )
    groups: dict[str, list[ExperimentRegistryEntry]] = defaultdict(list)
    for item in report.entries:
        if item.compatibility_key:
            groups[item.compatibility_key].append(item)
    lines.extend(["", "## Baseline lineage", ""])
    for key, entries in sorted(groups.items()):
        first = entries[0]
        lines.append(
            f"### {key} — {first.corpus_name} {first.corpus_version} / "
            f"{first.matrix_name} {first.matrix_version}"
        )
        lines.append("")
        for item in entries:
            if item.status == "baseline":
                relation = "lineage root"
            else:
                relation = f"vs {item.baseline_experiment_id}"
            lines.append(
                f"- {item.experiment_id}: **{item.status}**, {relation}, "
                f"regressions={item.regression_count}, improvements={item.improvement_count}"
            )
        lines.append("")
    if report.invalid_count:
        lines.extend(["## Invalid bundles", ""])
        for item in report.entries:
            if item.status == "invalid":
                lines.append(f"- {item.bundle_path}: {'; '.join(item.errors) or 'invalid'}")
        lines.append("")
    lines.extend(
        [
            "## Dashboard artifacts",
            "",
            "- history_metrics.csv: long-form metric history",
            "- registry_entries.csv: bundle index and gate status",
            "- lineage.csv: candidate to last-known-good baseline edges",
            "- charts/: baseline-profile metric trends by compatibility group",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_entries(entries: list[ExperimentRegistryEntry], path: Path) -> None:
    fields = [
        "experiment_id",
        "bundle_path",
        "compatibility_key",
        "created_at",
        "project_version",
        "git_sha",
        "git_dirty",
        "provider",
        "model",
        "corpus_name",
        "corpus_version",
        "matrix_name",
        "matrix_version",
        "baseline_profile",
        "repetitions",
        "valid",
        "status",
        "baseline_experiment_id",
        "regression_count",
        "improvement_count",
        "warnings",
        "errors",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in entries:
            row = item.model_dump()
            row["warnings"] = " | ".join(item.warnings)
            row["errors"] = " | ".join(item.errors)
            writer.writerow(row)


def _write_trends(points: list[ExperimentTrendPoint], path: Path) -> None:
    fields = [
        "experiment_id",
        "created_at",
        "compatibility_key",
        "profile",
        "source",
        "metric",
        "mean",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for point in points:
            writer.writerow(point.model_dump())


def _write_lineage(entries: list[ExperimentRegistryEntry], path: Path) -> None:
    fields = [
        "compatibility_key",
        "experiment_id",
        "status",
        "baseline_experiment_id",
        "regression_count",
        "improvement_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in entries:
            if item.valid:
                writer.writerow({field: getattr(item, field) for field in fields})


def _trend_svg(points: list[ExperimentTrendPoint], title: str) -> str:
    width, height = 920, 360
    left, right, top, bottom = 90, 40, 55, 80
    if not points:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            f'<text x="24" y="40" font-family="sans-serif">{escape(title)} — no data</text>'
            "</svg>\n"
        )
    ordered = sorted(points, key=lambda item: (item.created_at, item.experiment_id))
    values = [item.mean for item in ordered]
    low, high = min(values), max(values)
    if abs(high - low) < 1e-12:
        low -= 0.5
        high += 0.5
    plot_w, plot_h = width - left - right, height - top - bottom
    x_step = plot_w / max(1, len(ordered) - 1)

    def y(value: float) -> float:
        return top + (high - value) / (high - low) * plot_h

    coords = [(left + idx * x_step, y(item.mean)) for idx, item in enumerate(ordered)]
    path_d = " ".join(
        ("M" if idx == 0 else "L") + f" {x:.2f} {yy:.2f}" for idx, (x, yy) in enumerate(coords)
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="32" font-family="sans-serif" font-size="20">{escape(title)}</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{width - right}" '
        f'y2="{top + plot_h}" stroke="black"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="black"/>',
        f'<path d="{path_d}" fill="none" stroke="black" stroke-width="2"/>',
    ]
    for (x, yy), item in zip(coords, ordered, strict=True):
        parts.append(f'<circle cx="{x:.2f}" cy="{yy:.2f}" r="4" fill="black"/>')
        parts.append(
            f'<text x="{x:.2f}" y="{top + plot_h + 22}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="10">{escape(item.experiment_id[:14])}</text>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{yy - 9:.2f}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="10">{item.mean:.3g}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def save_experiment_registry(
    report: ExperimentRegistryReport, output_dir: str | Path
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    charts_dir = directory / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "registry.json",
        "markdown": directory / "registry.md",
        "entries_csv": directory / "registry_entries.csv",
        "history_csv": directory / "history_metrics.csv",
        "lineage_csv": directory / "lineage.csv",
    }
    paths["json"].write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(render_experiment_registry_markdown(report), encoding="utf-8")
    _write_entries(report.entries, paths["entries_csv"])
    _write_trends(report.trend_points, paths["history_csv"])
    _write_lineage(report.entries, paths["lineage_csv"])

    group_baselines = {
        item.compatibility_key: item.baseline_profile
        for item in report.entries
        if item.valid and item.compatibility_key and item.baseline_profile
    }
    for key, baseline_profile in sorted(group_baselines.items()):
        for metric in DASHBOARD_METRICS:
            points = [
                point
                for point in report.trend_points
                if point.compatibility_key == key
                and point.profile == baseline_profile
                and point.metric == metric
            ]
            if not points:
                continue
            path = charts_dir / f"{key}_{metric}.svg"
            path.write_text(
                _trend_svg(points, f"{key} / {baseline_profile} / {metric}"),
                encoding="utf-8",
            )
            paths[f"chart_{key}_{metric}"] = path
    return paths
