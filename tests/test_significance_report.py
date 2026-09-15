import csv
from pathlib import Path
from xml.etree import ElementTree

import pytest

from deepscout.config import get_settings
from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.models import BenchmarkCase, BenchmarkCorpus
from deepscout.evaluation.repeated import run_repeated_ablation
from deepscout.evaluation.significance import build_significance_report
from deepscout.evaluation.significance_report import save_significance_report


def _profile_name(settings, options) -> str:
    if settings.max_replans == 0:
        return "no-replan"
    if not options.citation_feedback_enabled:
        return "no-citation-feedback"
    if not options.evidence_dedup_enabled:
        return "no-evidence-dedup"
    if settings.max_searches == 12:
        return "low-budget"
    if settings.max_concurrency == 1:
        return "serial-research"
    return "full"


class SignificanceSyntheticGraph:
    def __init__(self, profile: str, repetition: int, settings, options):
        self.profile = profile
        self.repetition = repetition
        self.settings = settings
        self.options = options

    async def astream(self, state, stream_mode):
        assert stream_mode == ["updates", "values"]
        case_number = int(state["query"].rsplit("-", 1)[-1])
        base_coverage = 0.90 + 0.01 * (case_number - 1)
        coverage_penalty = {
            "full": 0.00,
            "no-replan": 0.03,
            "no-citation-feedback": 0.02,
            "no-evidence-dedup": 0.01,
            "low-budget": 0.12 - 0.01 * self.repetition,
            "serial-research": 0.00,
        }[self.profile]
        coverage = max(0.0, min(1.0, base_coverage - coverage_penalty))
        searches = 12 if self.profile == "low-budget" else 20 + case_number
        evidence = [{"source_host": "a.example", "relevance_score": 0.9}]
        if not self.options.evidence_dedup_enabled:
            evidence.append({"source_host": "a.example", "relevance_score": 0.9})
        yield "updates", {"planner": {"plan": "hidden"}}
        yield "updates", {"researcher": {"task_results": "hidden"}}
        yield (
            "values",
            {
                **state,
                "task_results": [
                    {
                        "status": "completed",
                        "search_calls": searches,
                        "model_tokens": 1000 * self.repetition,
                        "worker_seconds": 0.1 * self.repetition,
                    }
                ],
                "evidence_store": evidence,
                "citation_report": {
                    "coverage_score": coverage,
                    "unsupported_claims": [],
                },
                "replan_count": 0 if self.settings.max_replans == 0 else 1,
                "final_report": "fixture",
            },
        )


def _corpus() -> BenchmarkCorpus:
    return BenchmarkCorpus(
        name="significance-fixture",
        version="1.0",
        cases=[
            BenchmarkCase(case_id="case-1", query="case-1", category="fixture"),
            BenchmarkCase(case_id="case-2", query="case-2", category="fixture"),
        ],
    )


@pytest.mark.asyncio
async def test_significance_report_uses_case_units_and_writes_outputs(tmp_path: Path):
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    profile_calls: dict[str, int] = {}

    def graph_factory(*, options):
        settings = get_settings()
        profile = _profile_name(settings, options)
        profile_calls[profile] = profile_calls.get(profile, 0) + 1
        return SignificanceSyntheticGraph(
            profile,
            profile_calls[profile],
            settings,
            options,
        )

    repeated = await run_repeated_ablation(
        _corpus(),
        matrix,
        repetitions=3,
        bootstrap_resamples=100,
        graph_factory=graph_factory,
    )
    significance = build_significance_report(repeated, permutation_resamples=500)
    assert significance.minimum_nonzero_pairs_for_holm == 8

    global_low_budget = next(
        item
        for item in significance.comparisons
        if item.scope == "profile_across_cases"
        and item.profile == "low-budget"
        and item.metric == "quality_proxy_score"
    )
    assert global_low_budget.paired_count == 2
    assert global_low_budget.minimum_attainable_p == pytest.approx(0.5)
    assert global_low_budget.correction_family_size == 5
    assert global_low_budget.minimum_reportable_holm_p == 1.0
    assert global_low_budget.holm_adjusted_p >= global_low_budget.permutation_p_value

    case_low_budget = next(
        item
        for item in significance.comparisons
        if item.scope == "profile_case"
        and item.profile == "low-budget"
        and item.case_id == "case-1"
        and item.metric == "quality_proxy_score"
    )
    assert case_low_budget.paired_count == 3
    assert case_low_budget.minimum_attainable_p == pytest.approx(0.25)

    paths = save_significance_report(significance, tmp_path)
    assert paths["json"].exists()
    assert paths["csv"].exists()
    assert paths["markdown"].exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Global profile comparisons" in markdown
    assert "Resolution limits" in markdown
    assert "Cliff's delta" in markdown

    with paths["csv"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {"permutation_p_value", "holm_adjusted_p", "bh_adjusted_p"}.issubset(rows[0])

    ElementTree.parse(paths["effect_svg"])
    ElementTree.parse(paths["holm_p_svg"])


def test_significance_validation_rejects_bad_alpha():
    from deepscout.evaluation.repeated import RepeatedExperimentReport

    empty = RepeatedExperimentReport(
        matrix_name="m",
        matrix_version="1",
        corpus_name="c",
        corpus_version="1",
        baseline_profile="full",
        repetitions=1,
        order_strategy="fixed",
        bootstrap_resamples=1,
        confidence_level=0.95,
        bootstrap_seed=1,
        generated_at="2026-09-15T00:00:00+00:00",
        runs=[],
        profile_case_statistics=[],
        profile_statistics=[],
        profile_case_delta_statistics=[],
        profile_delta_statistics=[],
    )
    with pytest.raises(ValueError, match="alpha"):
        build_significance_report(empty, alpha=1.0)
