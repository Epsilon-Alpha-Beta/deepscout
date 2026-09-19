import json
import shutil
from pathlib import Path

import pytest

from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.models import BenchmarkMetrics, BenchmarkRunResult
from deepscout.evaluation.repeated import RepeatedRunRecord, build_repeated_report
from deepscout.evaluation.repeated_merge import (
    load_repeated_shards,
    merge_repeated_shards,
    validate_repeated_shard,
)
from deepscout.evaluation.runner import load_corpus


def _metrics(seed: int) -> BenchmarkMetrics:
    return BenchmarkMetrics(
        wall_seconds=1.0 + seed / 1000,
        node_visits={},
        total_node_events=1,
        replan_count=0,
        task_count=1,
        completed_tasks=1,
        failed_tasks=0,
        task_success_rate=1.0,
        evidence_count=2,
        unique_source_hosts=2,
        source_diversity_ratio=1.0,
        citation_coverage=1.0,
        unsupported_claims=0,
        search_calls=2,
        research_tokens=1000,
        worker_seconds=0.5,
        final_report_chars=100,
        quality_proxy_score=0.9,
    )


def _write_shard(
    root: Path,
    *,
    repetition: int,
    case_shard: int,
    case_ids: list[str],
) -> Path:
    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    cases = [case for case in corpus.cases if case.case_id in case_ids]
    offset = (repetition - 1) % len(matrix.profiles)
    profiles = matrix.profiles[offset:] + matrix.profiles[:offset]
    records: list[RepeatedRunRecord] = []
    execution_order = 0
    for profile_order, profile in enumerate(profiles):
        for case in cases:
            result = BenchmarkRunResult(
                case=case,
                status="completed",
                passed=True,
                metrics=_metrics(execution_order),
            )
            records.append(
                RepeatedRunRecord(
                    repetition=1,
                    execution_order=execution_order,
                    profile_order=profile_order,
                    profile=profile.name,
                    result=result,
                )
            )
            execution_order += 1

    report = build_repeated_report(
        corpus,
        matrix,
        records,
        repetitions=1,
        order_strategy="fixed",
        bootstrap_resamples=100,
        confidence_level=0.95,
        bootstrap_seed=7,
    )

    directory = root / f"rep-{repetition}-case-{case_shard}"
    run_dir = directory / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "repeated.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (directory / "shard.json").write_text(
        json.dumps(
            {
                "repetition": repetition,
                "case_shard": case_shard,
                "case_ids": case_ids,
                "repeated_path": "run/repeated.json",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return directory


def _complete_shards(root: Path, repetitions: int = 2) -> None:
    corpus = load_corpus("benchmarks/corpora/core.json")
    ids = [case.case_id for case in corpus.cases]
    chunks = [ids[index : index + 5] for index in range(0, len(ids), 5)]
    assert len(chunks) == 4
    for repetition in range(1, repetitions + 1):
        for case_shard, case_ids in enumerate(chunks):
            _write_shard(
                root,
                repetition=repetition,
                case_shard=case_shard,
                case_ids=case_ids,
            )


def test_merge_repeated_shards_reconstructs_complete_rotated_experiment(tmp_path: Path):
    _complete_shards(tmp_path, repetitions=2)
    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")

    shards = load_repeated_shards(tmp_path)
    merged = merge_repeated_shards(
        corpus,
        matrix,
        shards,
        repetitions=2,
        order_strategy="rotate",
    )

    assert len(shards) == 8
    assert len(merged.runs) == 2 * len(corpus.cases) * len(matrix.profiles)
    assert merged.repetitions == 2
    assert merged.order_strategy == "rotate"
    assert {record.repetition for record in merged.runs} == {1, 2}
    assert [record.execution_order for record in merged.runs] == list(range(len(merged.runs)))

    first_rep2 = next(record for record in merged.runs if record.repetition == 2)
    assert first_rep2.profile == matrix.profiles[1].name
    assert first_rep2.profile_order == 0
    assert len(merged.profile_statistics) == len(matrix.profiles)


def test_merge_repeated_shards_rejects_duplicate_shard_metadata(tmp_path: Path):
    _complete_shards(tmp_path, repetitions=1)
    source = tmp_path / "rep-1-case-0"
    duplicate = tmp_path / "duplicate"
    shutil.copytree(source, duplicate)

    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    with pytest.raises(ValueError, match="重复 shard metadata"):
        merge_repeated_shards(
            corpus,
            matrix,
            load_repeated_shards(tmp_path),
            repetitions=1,
        )


def test_merge_repeated_shards_rejects_missing_coverage(tmp_path: Path):
    _complete_shards(tmp_path, repetitions=1)
    shutil.rmtree(tmp_path / "rep-1-case-3")

    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    with pytest.raises(ValueError, match="coverage 不完整"):
        merge_repeated_shards(
            corpus,
            matrix,
            load_repeated_shards(tmp_path),
            repetitions=1,
        )


def test_load_repeated_shards_rejects_path_escape(tmp_path: Path):
    directory = tmp_path / "bad"
    directory.mkdir()
    (tmp_path / "outside.json").write_text("{}\n")
    (directory / "shard.json").write_text(
        json.dumps(
            {
                "repetition": 1,
                "case_shard": 0,
                "case_ids": ["x"],
                "repeated_path": "../outside.json",
            }
        )
        + "\n"
    )

    with pytest.raises(ValueError, match="越出 shard 目录"):
        load_repeated_shards(tmp_path)


def test_merge_repeated_shards_rejects_wrong_profile_rotation(tmp_path: Path):
    _complete_shards(tmp_path, repetitions=1)
    repeated_path = tmp_path / "rep-1-case-0" / "run" / "repeated.json"
    payload = json.loads(repeated_path.read_text())
    payload["runs"][0]["profile_order"] = 1
    repeated_path.write_text(json.dumps(payload) + "\n")

    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    with pytest.raises(ValueError, match="profile rotation 不一致"):
        merge_repeated_shards(
            corpus,
            matrix,
            load_repeated_shards(tmp_path),
            repetitions=1,
        )


def test_validate_repeated_shard_accepts_exact_partition_and_rotation(tmp_path: Path):
    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    case_ids = [case.case_id for case in corpus.cases[5:10]]
    shard_dir = _write_shard(
        tmp_path,
        repetition=2,
        case_shard=1,
        case_ids=case_ids,
    )
    shard = load_repeated_shards(shard_dir)[0]

    validate_repeated_shard(
        corpus,
        matrix,
        shard,
        target_repetition=2,
        target_case_shard=1,
        order_strategy="rotate",
    )


def test_validate_repeated_shard_rejects_wrong_target_coordinate(tmp_path: Path):
    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    case_ids = [case.case_id for case in corpus.cases[:5]]
    shard_dir = _write_shard(
        tmp_path,
        repetition=1,
        case_shard=0,
        case_ids=case_ids,
    )
    shard = load_repeated_shards(shard_dir)[0]

    with pytest.raises(ValueError, match="coordinate mismatch"):
        validate_repeated_shard(
            corpus,
            matrix,
            shard,
            target_repetition=1,
            target_case_shard=1,
        )
