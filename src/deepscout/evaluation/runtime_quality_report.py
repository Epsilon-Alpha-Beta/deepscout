"""运行后来源合规与人工评审报告。"""

from __future__ import annotations

import csv
from pathlib import Path

from deepscout.evaluation.review_audit import HumanReviewAuditReport
from deepscout.evaluation.source_compliance import SourcePolicyComplianceReport


def render_source_compliance_markdown(report: SourcePolicyComplianceReport) -> str:
    lines = [
        "# Source Policy Compliance",
        "",
        f"- Case: {report.case_id}",
        f"- Passed: **{report.passed}**",
        f"- Evidence: {report.evidence_count}",
        f"- Primary sources: {report.primary_source_count}",
        f"- Preferred-domain evidence: {report.preferred_domain_count}",
        f"- Recent sources: {report.recent_source_count}",
        f"- Freshness evaluable: {report.freshness_evaluable_count}",
        f"- Freshness unknown: {report.freshness_unknown_count}",
        "",
        "| Check | Status | Actual | Expected | Detail |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in report.checks:
        lines.append(
            f"| {item.name} | {item.status} | {item.actual} | {item.expected} | {item.detail} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_source_compliance_report(
    report: SourcePolicyComplianceReport, output_dir: str | Path
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "source_compliance.json",
        "markdown": directory / "source_compliance.md",
    }
    paths["json"].write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_source_compliance_markdown(report), encoding="utf-8")
    return paths


def render_human_review_markdown(report: HumanReviewAuditReport) -> str:
    agreement = report.agreement
    lines = [
        "# Human Gold Review Audit",
        "",
        f"- Corpus: {report.corpus_name} {report.corpus_version}",
        f"- Reviews: {report.review_count}",
        f"- Paired items: {report.paired_item_count}",
        f"- Resolved: {report.resolved_item_count}",
        f"- Unresolved: {report.unresolved_item_count}",
        f"- Pass agreement: {agreement.pass_agreement_rate}",
        f"- Cohen kappa: {agreement.cohen_kappa}",
        f"- Quadratic weighted kappa: {agreement.weighted_kappa}",
        f"- Mean absolute score gap: {agreement.mean_absolute_score_gap}",
    ]
    lines.extend(
        [
            "",
            "| Blind item | Case | Reviewers | Needs adjudication | "
            "Adjudicated | Resolved | Final score | Final pass |",
            "| --- | --- | ---: | --- | --- | --- | ---: | --- |",
        ]
    )
    for item in report.item_outcomes:
        score = "" if item.final_score is None else str(item.final_score)
        passed = "" if item.final_passed is None else str(item.final_passed)
        lines.append(
            f"| {item.blind_item_id} | {item.case_id} | {item.reviewer_count} | "
            f"{item.requires_adjudication} | {item.adjudicated} | {item.resolved} | "
            f"{score} | {passed} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_human_review_audit(
    report: HumanReviewAuditReport, output_dir: str | Path
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / "human_review_audit.json",
        "markdown": directory / "human_review_audit.md",
        "csv": directory / "human_review_outcomes.csv",
    }
    paths["json"].write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths["markdown"].write_text(render_human_review_markdown(report), encoding="utf-8")
    with paths["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "blind_item_id",
                "case_id",
                "reviewer_count",
                "requires_adjudication",
                "adjudicated",
                "resolved",
                "final_score",
                "final_passed",
            ],
        )
        writer.writeheader()
        for item in report.item_outcomes:
            writer.writerow(item.model_dump())
    return paths
