"""Release readiness gate 的 JSON/Markdown 审计报告。"""

from __future__ import annotations

import json
from pathlib import Path

from deepscout.evaluation.experiment_lifecycle_report import (
    save_promotion_report,
    save_retention_report,
)
from deepscout.evaluation.release_gate import ReleaseGateReport


def render_release_gate_markdown(report: ReleaseGateReport) -> str:
    lines = [
        "# DeepScout Release Readiness Gate",
        "",
        f"- Experiment: {report.experiment_id}",
        f"- Compatibility group: {report.compatibility_key or 'n/a'}",
        f"- Status: **{report.status}**",
        f"- Registry invalid bundles: **{report.registry_invalid_count}**",
        f"- Promotion action: **{report.promotion.action}**",
        f"- Retention keep / delete preview: **{report.retention.keep_count} / "
        f"{report.retention.delete_count}**",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in report.blockers)
    if not report.blockers:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in report.warnings)
    if not report.warnings:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety boundary",
            "",
            "- Gate never applies retention deletions.",
            "- Gate never performs manual promotion override.",
            "- A blocked result exits non-zero in the CLI.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_release_gate_report(report: ReleaseGateReport, output_dir: str | Path) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "release_gate.json",
        "markdown": directory / "release_gate.md",
    }
    paths["json"].write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(render_release_gate_markdown(report), encoding="utf-8")
    promotion_paths = save_promotion_report(report.promotion, directory)
    retention_paths = save_retention_report(report.retention, directory)
    paths["promotion_json"] = promotion_paths["json"]
    paths["promotion_markdown"] = promotion_paths["markdown"]
    paths["retention_json"] = retention_paths["json"]
    paths["retention_markdown"] = retention_paths["markdown"]
    paths["retention_csv"] = retention_paths["csv"]
    return paths
