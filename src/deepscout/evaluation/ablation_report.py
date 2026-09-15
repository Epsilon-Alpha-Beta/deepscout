"""Ablation 对比报告序列化与 Markdown 渲染。"""

import json
from pathlib import Path

from deepscout.evaluation.ablation import AblationReport
from deepscout.evaluation.report import save_report


def _signed(value: float, digits: int = 3) -> str:
    return f"{value:+.{digits}f}"


def _cost(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.6f}"


def render_ablation_markdown(report: AblationReport) -> str:
    lines = [
        f"# DeepScout Ablation — {report.matrix_name} {report.matrix_version}",
        "",
        f"- Corpus: {report.corpus_name} {report.corpus_version}",
        f"- Baseline: {report.baseline_profile}",
        f"- Profiles: {len(report.profiles)}",
        "",
        "## Quality deltas",
        "",
        (
            "| Profile | Pass | ΔPass | Quality | ΔQuality | Citation | ΔCitation | "
            "Diversity | ΔDiversity |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report.comparisons:
        lines.append(
            "| "
            f"{item.profile} | {item.pass_rate:.1%} | {_signed(item.delta_pass_rate)} | "
            f"{item.average_quality_proxy_score:.3f} | {_signed(item.delta_quality_proxy_score)} | "
            f"{item.average_citation_coverage:.3f} | {_signed(item.delta_citation_coverage)} | "
            f"{item.average_source_diversity_ratio:.3f} | "
            f"{_signed(item.delta_source_diversity_ratio)} |"
        )

    lines.extend(
        [
            "",
            "## Resource deltas",
            "",
            (
                "| Profile | Replans/case | ΔReplans | Evidence/case | ΔEvidence | "
                "Searches/case | ΔSearches | Tokens/case | ΔTokens | Wall/case(s) | "
                "ΔWall | Tracked cost/case |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in report.comparisons:
        lines.append(
            "| "
            f"{item.profile} | {item.replans_per_case:.2f} | "
            f"{_signed(item.delta_replans_per_case)} | "
            f"{item.evidence_count_per_case:.2f} | {_signed(item.delta_evidence_count_per_case)} | "
            f"{item.search_calls_per_case:.2f} | {_signed(item.delta_search_calls_per_case)} | "
            f"{item.research_tokens_per_case:.1f} | "
            f"{_signed(item.delta_research_tokens_per_case, 1)} | "
            f"{item.wall_seconds_per_case:.3f} | {_signed(item.delta_wall_seconds_per_case)} | "
            f"{_cost(item.tracked_cost_per_case_usd)} |"
        )

    lines.extend(["", "## Profiles", ""])
    for profile_report in report.profiles:
        profile = profile_report.profile
        settings = profile.settings.model_dump(exclude_none=True)
        graph = profile.graph.model_dump()
        lines.extend(
            [
                f"### {profile.name}",
                "",
                profile.description or "无额外说明。",
                "",
                "- Settings overrides: "
                f"`{json.dumps(settings, ensure_ascii=False, sort_keys=True)}`",
                f"- Graph options: `{json.dumps(graph, ensure_ascii=False, sort_keys=True)}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def save_ablation_report(
    report: AblationReport,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "ablation.json"
    md_path = directory / "ablation.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_ablation_markdown(report), encoding="utf-8")

    for item in report.profiles:
        save_report(item.benchmark, directory / "profiles" / item.profile.name)
    return json_path, md_path
