import csv
from pathlib import Path
from xml.etree import ElementTree

import pytest

from deepscout.config import get_settings
from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.models import BenchmarkCase, BenchmarkCorpus
from deepscout.evaluation.repeated import run_repeated_ablation
from deepscout.evaluation.repeated_report import save_repeated_report


class RepeatedSyntheticGraph:
    def __init__(self, profile: str, repetition: int, settings, options):
        self.profile = profile
        self.repetition = repetition
        self.settings = settings
        self.options = options

    async def astream(self, state, stream_mode):
        assert stream_mode == ["updates", "values"]
        if self.profile == "no-citation-feedback" and self.repetition == 2:
            raise RuntimeError("synthetic provider failure")

        yield "updates", {"planner": {"plan": "hidden"}}
        searches = min(self.settings.max_searches, 20 + self.repetition)
        evidence = [{"source_host": "a.example", "relevance_score": 0.9}]
        if not self.options.evidence_dedup_enabled:
            evidence.append({"source_host": "a.example", "relevance_score": 0.9})
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
                    "coverage_score": 0.9,
                    "unsupported_claims": [],
                },
                "replan_count": 0 if self.settings.max_replans == 0 else 1,
                "final_report": "fixture",
            },
        )


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


def _corpus() -> BenchmarkCorpus:
    return BenchmarkCorpus(
        name="repeated-fixture",
        version="1.0",
        cases=[BenchmarkCase(case_id="case-1", query="q", category="fixture")],
    )


@pytest.mark.asyncio
async def test_repeated_ablation_statistics_pairing_and_rotation(tmp_path: Path):
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    profile_calls: dict[str, int] = {}

    def graph_factory(*, options):
        settings = get_settings()
        profile = _profile_name(settings, options)
        profile_calls[profile] = profile_calls.get(profile, 0) + 1
        return RepeatedSyntheticGraph(profile, profile_calls[profile], settings, options)

    report = await run_repeated_ablation(
        _corpus(),
        matrix,
        repetitions=3,
        bootstrap_resamples=200,
        bootstrap_seed=17,
        graph_factory=graph_factory,
    )
    assert len(report.runs) == 18
    first_by_repetition = {
        repetition: next(
            record.profile
            for record in report.runs
            if record.repetition == repetition and record.profile_order == 0
        )
        for repetition in (1, 2, 3)
    }
    assert first_by_repetition == {
        1: "full",
        2: "no-replan",
        3: "no-citation-feedback",
    }

    profile_stats = {scope.profile: scope for scope in report.profile_statistics}
    assert profile_stats["full"].metrics["search_calls"].mean == 22.0
    assert profile_stats["full"].metrics["search_calls"].std == 1.0
    assert profile_stats["no-citation-feedback"].attempted_units == 3
    assert profile_stats["no-citation-feedback"].completed_units == 2
    assert profile_stats["no-citation-feedback"].error_units == 1
    assert profile_stats["no-citation-feedback"].metrics["search_calls"].count == 2

    deltas = {scope.profile: scope for scope in report.profile_delta_statistics}
    assert deltas["no-replan"].metrics["replan_count"].mean == -1.0
    assert deltas["low-budget"].metrics["search_calls"].mean == pytest.approx(-10.0)
    assert deltas["no-evidence-dedup"].metrics["source_diversity_ratio"].mean == -0.5
    assert deltas["no-citation-feedback"].metrics["search_calls"].count == 2

    paths = save_repeated_report(report, tmp_path)
    assert paths["json"].exists()
    assert paths["runs_csv"].exists()
    assert paths["statistics_csv"].exists()
    assert paths["deltas_csv"].exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Paired delta vs baseline" in markdown
    assert "Full profile distributions" in markdown

    with paths["runs_csv"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    failed = next(row for row in rows if row["status"] == "error")
    assert failed["error_type"] == "RuntimeError"
    assert failed["quality_proxy_score"] == ""
    assert failed["search_calls"] == ""

    with paths["statistics_csv"].open(encoding="utf-8", newline="") as handle:
        stats_rows = list(csv.DictReader(handle))
    assert {"mean", "std", "median", "p50", "p95", "ci_low", "ci_high"}.issubset(stats_rows[0])

    for key, path in paths.items():
        if key.startswith("chart_"):
            ElementTree.parse(path)


def test_repeated_validate_inputs_reject_invalid_repetitions():
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    with pytest.raises(ValueError, match="repetitions"):
        # coroutine raises before the first await when executed
        import asyncio

        asyncio.run(run_repeated_ablation(_corpus(), matrix, repetitions=0))
