from pathlib import Path

import pytest

from deepscout.evaluation.models import BenchmarkCase, BenchmarkCorpus
from deepscout.evaluation.report import build_report, render_markdown, save_report
from deepscout.evaluation.runner import load_corpus, run_case


class FakeGraph:
    async def astream(self, state, stream_mode):
        assert stream_mode == ["updates", "values"]
        yield "updates", {"analyze_query": {"analysis": "hidden"}}
        yield "updates", {"planner": {"plan": "hidden"}}
        yield "updates", {"researcher": {"task_results": "hidden"}}
        yield (
            "values",
            {
                **state,
                "task_results": [
                    {
                        "status": "completed",
                        "search_calls": 1,
                        "model_tokens": 100,
                        "worker_seconds": 0.2,
                    }
                ],
                "evidence_store": [{"source_host": "example.com", "relevance_score": 0.9}],
                "citation_report": {"coverage_score": 1.0, "unsupported_claims": []},
                "final_report": "LangGraph benchmark fixture",
            },
        )


class ErrorGraph:
    async def astream(self, state, stream_mode):
        if False:
            yield None
        raise RuntimeError("provider unavailable")


def _corpus() -> BenchmarkCorpus:
    return BenchmarkCorpus(
        name="fixture",
        version="1.0",
        cases=[
            BenchmarkCase(
                case_id="case-1",
                query="fixture query",
                category="fixture",
                expected_keywords=["LangGraph"],
            )
        ],
    )


@pytest.mark.asyncio
async def test_runner_records_trajectory_without_payload_content(tmp_path: Path):
    case = _corpus().cases[0]
    result = await run_case(FakeGraph(), case)
    assert result.status == "completed"
    assert result.passed is True
    assert [event.node for event in result.trajectory] == [
        "analyze_query",
        "planner",
        "researcher",
    ]
    assert result.trajectory[0].output_keys == ["analysis"]
    assert "hidden" not in result.model_dump_json()

    report = build_report(_corpus(), [result])
    assert report.summary.pass_rate == 1.0
    assert "case-1" in render_markdown(report)
    json_path, md_path = save_report(report, tmp_path)
    assert json_path.exists()
    assert md_path.exists()


@pytest.mark.asyncio
async def test_runner_turns_exception_into_benchmark_result():
    result = await run_case(ErrorGraph(), _corpus().cases[0])
    assert result.status == "error"
    assert result.passed is False
    assert result.error == "RuntimeError: provider unavailable"


def test_corpus_rejects_duplicate_case_ids():
    with pytest.raises(ValueError, match="case_id"):
        BenchmarkCorpus(
            name="duplicates",
            version="1.0",
            cases=[
                BenchmarkCase(case_id="same", query="q1", category="fixture"),
                BenchmarkCase(case_id="same", query="q2", category="fixture"),
            ],
        )


def test_core_benchmark_corpus_is_valid():
    corpus = load_corpus(Path("benchmarks/corpora/core.json"))
    assert corpus.name == "deepscout-core-research"
    assert corpus.version == "1.3.0"
    assert len(corpus.cases) == 20
    assert len({case.category for case in corpus.cases}) >= 12
