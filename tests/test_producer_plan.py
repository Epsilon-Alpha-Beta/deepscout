from pathlib import Path

import pytest

from deepscout.evaluation.producer_plan import (
    artifact_names_from_api_response,
    build_producer_plan,
    expected_official_shards,
    plan_producer_resume,
    shard_resume_decision,
    validate_shard_provenance_set,
)


def _plan(
    *,
    model: str = "anthropic:claude-sonnet-4-6",
    git_sha: str = "a" * 40,
    experiment_id: str = "exp-a",
    workflow_run_id: str = "100",
):
    return build_producer_plan(
        corpus_path="benchmarks/corpora/core.json",
        matrix_path="benchmarks/ablations/core.json",
        protocol="official",
        model=model,
        git_sha=git_sha,
        lineage_mode="continue",
        history_run_id="42",
        experiment_id=experiment_id,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=1,
        max_parallel=2,
    )


def test_official_plan_has_fixed_600_run_topology():
    plan = _plan()
    assert plan.case_count == 20
    assert plan.repetitions == 5
    assert plan.case_shards == 4
    assert plan.cases_per_shard == 5
    assert plan.runs_per_shard == 30
    assert plan.total_shards == 20
    assert plan.total_runs == 600
    assert plan.per_shard_search_call_upper_bound == 1060
    assert plan.per_shard_research_token_upper_bound == 5_250_000
    assert plan.total_search_call_upper_bound == 21_200
    assert plan.total_research_token_upper_bound == 105_000_000
    assert len(expected_official_shards(plan)) == 20


def test_resume_fingerprint_ignores_run_identity_but_binds_model_and_git():
    first = _plan(experiment_id="exp-1", workflow_run_id="100")
    retry = _plan(experiment_id="exp-2", workflow_run_id="200")
    changed_model = _plan(model="openai:gpt-5", experiment_id="exp-3", workflow_run_id="300")
    changed_git = _plan(git_sha="b" * 40, experiment_id="exp-4", workflow_run_id="400")

    assert first.compatibility_fingerprint == retry.compatibility_fingerprint
    assert first.compatibility_fingerprint != changed_model.compatibility_fingerprint
    assert first.compatibility_fingerprint != changed_git.compatibility_fingerprint


def test_resume_budget_counts_reused_and_new_shards():
    current = _plan(experiment_id="current", workflow_run_id="200")
    previous = _plan(experiment_id="previous", workflow_run_id="100")
    all_names = [name for _, _, name in expected_official_shards(current)]
    available = set(all_names[:17])

    resume = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=available,
        resume_run_id="100",
        max_new_shards=3,
        max_new_search_calls=3180,
        max_new_research_tokens=15_750_000,
    )
    assert resume.passed is True
    assert resume.reused_shards == 17
    assert resume.new_shards == 3
    assert resume.reused_run_units == 510
    assert resume.new_run_units == 90
    assert resume.new_search_call_upper_bound == 3180
    assert resume.new_research_token_upper_bound == 15_750_000

    blocked = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=available,
        resume_run_id="100",
        max_new_shards=2,
        max_new_search_calls=3179,
        max_new_research_tokens=15_749_999,
    )
    assert blocked.passed is False
    assert any("new shard budget exceeded" in blocker for blocker in blocked.blockers)
    assert any("search-call budget exceeded" in blocker for blocker in blocked.blockers)
    assert any("research-token budget exceeded" in blocker for blocker in blocked.blockers)


def test_resume_rejects_incompatible_plan_even_when_all_shards_exist():
    current = _plan()
    previous = _plan(model="openai:gpt-5")
    names = {name for _, _, name in expected_official_shards(current)}

    resume = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=names,
        resume_run_id="100",
        max_new_shards=20,
    )
    assert resume.passed is False
    assert any("fingerprint mismatch" in blocker for blocker in resume.blockers)


def test_new_official_run_can_enforce_zero_or_full_new_shard_budget():
    current = _plan()
    blocked = plan_producer_resume(
        current,
        previous=None,
        available_artifacts=None,
        resume_run_id=None,
        max_new_shards=0,
    )
    assert blocked.new_shards == 20
    assert blocked.new_run_units == 600
    assert blocked.passed is False

    allowed = plan_producer_resume(
        current,
        previous=None,
        available_artifacts=None,
        resume_run_id=None,
        max_new_shards=20,
    )
    assert allowed.passed is True
    assert allowed.new_shards == 20


def test_shard_decision_and_artifact_api_parser():
    current = _plan()
    previous = _plan(experiment_id="previous", workflow_run_id="100")
    artifact = "deepscout-benchmark-shard-r2-c3"
    payload = {
        "total_count": 2,
        "artifacts": [
            {"name": artifact},
            {"name": "deepscout-producer-plan"},
        ],
    }

    names = artifact_names_from_api_response(payload)
    resume = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=names,
        resume_run_id="100",
        max_new_shards=19,
    )
    decision = shard_resume_decision(resume, repetition=2, case_shard=3)
    assert decision.reuse is True
    assert decision.artifact_name == artifact

    with pytest.raises(ValueError, match="分页截断"):
        artifact_names_from_api_response({"total_count": 101, "artifacts": [{"name": "only-one"}]})


def test_smoke_plan_is_six_runs_without_lineage():
    plan = build_producer_plan(
        corpus_path=Path("benchmarks/corpora/core.json"),
        matrix_path=Path("benchmarks/ablations/core.json"),
        protocol="smoke",
        model="anthropic:claude-sonnet-4-6",
        git_sha="a" * 40,
        lineage_mode=None,
        history_run_id=None,
        experiment_id="smoke",
        workflow_run_id="1",
        workflow_run_attempt=1,
    )
    assert plan.total_runs == 6
    assert plan.total_shards == 1
    assert plan.total_search_call_upper_bound == 212
    assert plan.total_research_token_upper_bound == 1_050_000
    assert plan.lineage_mode is None
    assert plan.history_run_id is None


def test_provenance_summary_matches_resume_plan_and_detects_tampering(tmp_path: Path):
    current = _plan(experiment_id="current", workflow_run_id="200")
    previous = _plan(experiment_id="previous", workflow_run_id="100")
    names = [name for _, _, name in expected_official_shards(current)]
    resume = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=set(names[:17]),
        resume_run_id="100",
        max_new_shards=3,
    )
    for shard in resume.shards:
        directory = tmp_path / shard.artifact_name
        directory.mkdir()
        payload = {
            "repetition": shard.repetition,
            "case_shard": shard.case_shard,
            "execution": "reused" if shard.reuse else "executed",
            "source_run_id": "100" if shard.reuse else None,
            "current_run_id": "200",
            "current_run_attempt": 1,
            "git_sha": current.git_sha,
            "producer_fingerprint": current.compatibility_fingerprint,
        }
        (directory / "provenance.json").write_text(__import__("json").dumps(payload) + "\n")

    summary = validate_shard_provenance_set(
        tmp_path,
        current=current,
        resume=resume,
    )
    assert summary.reused_shards == 17
    assert summary.executed_shards == 3
    assert summary.reused_run_units == 510
    assert summary.executed_run_units == 90

    target = tmp_path / names[0] / "provenance.json"
    payload = __import__("json").loads(target.read_text())
    payload["source_run_id"] = "999"
    target.write_text(__import__("json").dumps(payload) + "\n")
    with pytest.raises(ValueError, match="source_run_id mismatch"):
        validate_shard_provenance_set(tmp_path, current=current, resume=resume)


def test_resume_rejects_finalized_source_run_and_ignores_expired_artifacts():
    current = _plan(experiment_id="current", workflow_run_id="200")
    previous = _plan(experiment_id="previous", workflow_run_id="100")
    shard_name = expected_official_shards(current)[0][2]
    names = artifact_names_from_api_response(
        {
            "total_count": 3,
            "artifacts": [
                {"name": shard_name, "expired": False},
                {"name": "deepscout-experiment-bundles", "expired": False},
                {"name": "expired-shard", "expired": True},
            ],
        }
    )
    assert "expired-shard" not in names

    resume = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=names,
        resume_run_id="100",
        max_new_shards=20,
    )
    assert resume.passed is False
    assert any("finalized experiment lineage" in blocker for blocker in resume.blockers)
