from pathlib import Path

import pytest

from deepscout.config import get_settings
from deepscout.evaluation.ablation import (
    AblationMatrix,
    AblationProfile,
    load_ablation_matrix,
    run_ablation_matrix,
)
from deepscout.evaluation.ablation_report import render_ablation_markdown, save_ablation_report
from deepscout.evaluation.models import BenchmarkCase, BenchmarkCorpus


class ProfileGraph:
    def __init__(self, options, settings):
        self.options = options
        self.settings = settings

    async def astream(self, state, stream_mode):
        assert stream_mode == ["updates", "values"]
        yield "updates", {"planner": {"plan": "hidden"}}
        yield "updates", {"researcher": {"task_results": "hidden"}}
        searches = min(self.settings.max_searches, 20)
        tokens = min(self.settings.max_research_tokens, 100_000)
        evidence = [{"source_host": "a.example", "relevance_score": 0.9}]
        if not self.options.evidence_dedup_enabled:
            evidence.append({"source_host": "a.example", "relevance_score": 0.9})
        yield (
            "values",
            {
                **state,
                "task_results": [
                    {
                        "status": "completed",
                        "search_calls": searches,
                        "model_tokens": tokens,
                        "worker_seconds": 0.1,
                    }
                ],
                "evidence_store": evidence,
                "citation_report": {"coverage_score": 0.9, "unsupported_claims": []},
                "replan_count": 0 if self.settings.max_replans == 0 else 1,
                "final_report": "fixture",
            },
        )


def _corpus() -> BenchmarkCorpus:
    return BenchmarkCorpus(
        name="fixture",
        version="1.0",
        cases=[BenchmarkCase(case_id="case-1", query="q", category="fixture")],
    )


@pytest.mark.asyncio
async def test_ablation_matrix_applies_settings_and_graph_options(tmp_path: Path):
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    created: list[tuple[str, int, int, bool, bool]] = []

    def graph_factory(*, options):
        settings = get_settings()
        created.append(
            (
                matrix.profiles[len(created)].name,
                settings.max_concurrency,
                settings.max_replans,
                options.citation_feedback_enabled,
                options.evidence_dedup_enabled,
            )
        )
        return ProfileGraph(options, settings)

    original_concurrency = get_settings().max_concurrency
    report = await run_ablation_matrix(_corpus(), matrix, graph_factory=graph_factory)
    assert len(report.profiles) == 6
    assert get_settings().max_concurrency == original_concurrency

    created_by_name = {item[0]: item[1:] for item in created}
    assert created_by_name["no-replan"][1] == 0
    assert created_by_name["serial-research"][0] == 1
    assert created_by_name["no-citation-feedback"][2] is False
    assert created_by_name["no-evidence-dedup"][3] is False

    comparisons = {item.profile: item for item in report.comparisons}
    assert comparisons["full"].delta_quality_proxy_score == 0.0
    assert comparisons["no-replan"].replans_per_case == 0.0
    assert comparisons["no-replan"].delta_replans_per_case == -1.0
    assert comparisons["no-evidence-dedup"].evidence_count_per_case == 2.0
    assert comparisons["no-evidence-dedup"].delta_source_diversity_ratio == -0.5
    assert comparisons["low-budget"].search_calls_per_case == 12.0
    assert comparisons["low-budget"].delta_search_calls_per_case == -8.0
    assert comparisons["low-budget"].research_tokens_per_case == 50_000.0

    markdown = render_ablation_markdown(report)
    assert "no-citation-feedback" in markdown
    assert "Resource deltas" in markdown
    json_path, md_path = save_ablation_report(report, tmp_path)
    assert json_path.exists()
    assert md_path.exists()
    assert (tmp_path / "profiles" / "full" / "report.json").exists()


def test_core_ablation_matrix_is_valid():
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    assert matrix.baseline_profile == "full"
    assert [profile.name for profile in matrix.profiles] == [
        "full",
        "no-replan",
        "no-citation-feedback",
        "no-evidence-dedup",
        "low-budget",
        "serial-research",
    ]


def test_ablation_matrix_rejects_invalid_profile_topology():
    profile = AblationProfile(name="full")
    with pytest.raises(ValueError, match="唯一"):
        AblationMatrix(
            name="bad",
            version="1",
            baseline_profile="full",
            profiles=[profile, profile],
        )
    with pytest.raises(ValueError, match="baseline_profile"):
        AblationMatrix(
            name="bad",
            version="1",
            baseline_profile="missing",
            profiles=[AblationProfile(name="full"), AblationProfile(name="other")],
        )
