"""Promotion / Retention 审计报告。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from deepscout.evaluation.experiment_lifecycle import (
    PromotionDecision,
    RetentionApplyReport,
    RetentionPlan,
)


def render_promotion_markdown(decision: PromotionDecision) -> str:
    lines = [
        "# DeepScout Promotion Decision",
        "",
        f"- Experiment: `{decision.experiment_id}`",
        f"- Compatibility group: `{decision.compatibility_key or 'n/a'}`",
        f"- Registry status: **{decision.registry_status}**",
        f"- Eligible: **{decision.eligible}**",
        f"- Action: **{decision.action}**",
        f"- Overridden: **{decision.overridden}**",
        f"- Actor: `{decision.actor}`",
        f"- Decided at: `{decision.decided_at}`",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in decision.blockers)
    if not decision.blockers:
        lines.append("- none")
    lines.extend(["", "## Reasons", ""])
    lines.extend(f"- {item}" for item in decision.reasons)
    return "\n".join(lines).rstrip() + "\n"


def render_retention_markdown(plan: RetentionPlan) -> str:
    lines = [
        "# DeepScout Retention Plan",
        "",
        f"- Bundles root: `{plan.bundles_root}`",
        f"- Keep / Delete: **{plan.keep_count} / {plan.delete_count}**",
        f"- Milestones: {', '.join(plan.milestone_ids) or 'none'}",
        f"- Promoted: {', '.join(plan.promoted_ids) or 'none'}",
        "",
        "| Experiment | Registry status | Action | Reasons |",
        "| --- | --- | --- | --- |",
    ]
    for item in plan.actions:
        lines.append(
            f"| {item.experiment_id} | {item.registry_status} | **{item.action}** | "
            f"{'; '.join(item.reasons)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_promotion_report(decision: PromotionDecision, output_dir: str | Path) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "promotion_decision.json",
        "markdown": directory / "promotion_decision.md",
    }
    paths["json"].write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_promotion_markdown(decision), encoding="utf-8")
    return paths


def save_retention_report(
    plan: RetentionPlan,
    output_dir: str | Path,
    *,
    apply_report: RetentionApplyReport | None = None,
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "retention_plan.json",
        "markdown": directory / "retention_plan.md",
        "csv": directory / "retention_plan.csv",
    }
    paths["json"].write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(render_retention_markdown(plan), encoding="utf-8")
    fields = ["experiment_id", "bundle_path", "registry_status", "action", "reasons"]
    with paths["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in plan.actions:
            row = item.model_dump()
            row["reasons"] = " | ".join(item.reasons)
            writer.writerow(row)
    if apply_report is not None:
        path = directory / "retention_apply.json"
        path.write_text(apply_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        paths["apply_json"] = path
    return paths
