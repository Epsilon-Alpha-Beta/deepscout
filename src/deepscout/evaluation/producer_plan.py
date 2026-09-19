"""Benchmark Producer 的执行计划、恢复兼容性与预算护栏。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.config import Settings
from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.experiment_bundle import sha256_file
from deepscout.evaluation.runner import load_corpus

ProducerProtocol = Literal["smoke", "official"]
LineageMode = Literal["continue", "new"]


class ProducerPlan(BaseModel):
    schema_version: int = 1
    protocol: ProducerProtocol
    model: str = Field(min_length=1)
    git_sha: str = Field(min_length=1)
    corpus_path: str
    matrix_path: str
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    matrix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_name: str
    corpus_version: str
    matrix_name: str
    matrix_version: str
    baseline_profile: str
    profiles: list[str]
    case_count: int = Field(ge=1)
    repetitions: int = Field(ge=1)
    case_shards: int = Field(ge=1)
    cases_per_shard: int = Field(ge=1)
    runs_per_shard: int = Field(ge=1)
    total_shards: int = Field(ge=1)
    total_runs: int = Field(ge=1)
    max_parallel: int = Field(ge=1)
    per_shard_search_call_upper_bound: int = Field(ge=1)
    per_shard_research_token_upper_bound: int = Field(ge=1)
    total_search_call_upper_bound: int = Field(ge=1)
    total_research_token_upper_bound: int = Field(ge=1)
    lineage_mode: LineageMode | None = None
    history_run_id: str | None = None
    experiment_id: str = Field(min_length=1)
    workflow_run_id: str = Field(min_length=1)
    workflow_run_attempt: int = Field(ge=1)
    compatibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProducerShardPlan(BaseModel):
    repetition: int = Field(ge=1)
    case_shard: int = Field(ge=0)
    artifact_name: str = Field(min_length=1)
    reuse: bool


class ProducerShardProvenance(BaseModel):
    repetition: int = Field(ge=1)
    case_shard: int = Field(ge=0)
    execution: Literal["reused", "executed"]
    source_run_id: str | None = None
    current_run_id: str = Field(min_length=1)
    current_run_attempt: int = Field(ge=1)
    git_sha: str = Field(min_length=1)
    producer_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProducerProvenanceSummary(BaseModel):
    total_shards: int = Field(ge=1)
    reused_shards: int = Field(ge=0)
    executed_shards: int = Field(ge=0)
    reused_run_units: int = Field(ge=0)
    executed_run_units: int = Field(ge=0)


class ProducerResumePlan(BaseModel):
    schema_version: int = 1
    current_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    resume_run_id: str | None = None
    max_new_shards: int = Field(ge=0)
    max_new_search_calls: int | None = Field(default=None, ge=0)
    max_new_research_tokens: int | None = Field(default=None, ge=0)
    total_shards: int = Field(ge=1)
    reused_shards: int = Field(ge=0)
    new_shards: int = Field(ge=0)
    reused_run_units: int = Field(ge=0)
    new_run_units: int = Field(ge=0)
    reused_search_call_upper_bound: int = Field(ge=0)
    new_search_call_upper_bound: int = Field(ge=0)
    reused_research_token_upper_bound: int = Field(ge=0)
    new_research_token_upper_bound: int = Field(ge=0)
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    shards: list[ProducerShardPlan]


class ProducerDispatchApproval(BaseModel):
    schema_version: int = 1
    producer_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    resume_run_id: str | None = None
    max_new_shards: int = Field(ge=0)
    max_new_search_calls: int | None = Field(default=None, ge=0)
    max_new_research_tokens: int | None = Field(default=None, ge=0)
    reused_shards: int = Field(ge=0)
    new_shards: int = Field(ge=0)
    new_run_units: int = Field(ge=0)
    new_search_call_upper_bound: int = Field(ge=0)
    new_research_token_upper_bound: int = Field(ge=0)
    shard_decisions: list[ProducerShardPlan]
    approval_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _compatibility_payload(plan: ProducerPlan) -> dict[str, object]:
    return {
        "schema_version": plan.schema_version,
        "protocol": plan.protocol,
        "model": plan.model,
        "git_sha": plan.git_sha,
        "corpus_sha256": plan.corpus_sha256,
        "matrix_sha256": plan.matrix_sha256,
        "corpus_name": plan.corpus_name,
        "corpus_version": plan.corpus_version,
        "matrix_name": plan.matrix_name,
        "matrix_version": plan.matrix_version,
        "baseline_profile": plan.baseline_profile,
        "profiles": plan.profiles,
        "case_count": plan.case_count,
        "repetitions": plan.repetitions,
        "case_shards": plan.case_shards,
        "cases_per_shard": plan.cases_per_shard,
        "runs_per_shard": plan.runs_per_shard,
        "total_shards": plan.total_shards,
        "total_runs": plan.total_runs,
        "max_parallel": plan.max_parallel,
        "per_shard_search_call_upper_bound": plan.per_shard_search_call_upper_bound,
        "per_shard_research_token_upper_bound": plan.per_shard_research_token_upper_bound,
        "total_search_call_upper_bound": plan.total_search_call_upper_bound,
        "total_research_token_upper_bound": plan.total_research_token_upper_bound,
        "lineage_mode": plan.lineage_mode,
        "history_run_id": plan.history_run_id,
    }


def build_producer_plan(
    *,
    corpus_path: str | Path,
    matrix_path: str | Path,
    protocol: ProducerProtocol,
    model: str,
    git_sha: str,
    lineage_mode: LineageMode | None,
    history_run_id: str | None,
    experiment_id: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
    max_parallel: int = 2,
) -> ProducerPlan:
    corpus_file = Path(corpus_path)
    matrix_file = Path(matrix_path)
    corpus = load_corpus(corpus_file)
    matrix = load_ablation_matrix(matrix_file)
    profile_count = len(matrix.profiles)

    if protocol == "official":
        if len(corpus.cases) != 20 or profile_count != 6:
            raise ValueError("official producer 固定要求 20 cases 与 6 profiles。")
        repetitions = 5
        case_shards = 4
        cases_per_shard = 5
        lineage = lineage_mode
        history = history_run_id
        if lineage not in {"continue", "new"}:
            raise ValueError("official producer 必须声明 lineage_mode。")
        if lineage == "continue" and not history:
            raise ValueError("official/continue 必须提供 history_run_id。")
        if lineage == "new" and history:
            raise ValueError("official/new 禁止提供 history_run_id。")
    else:
        repetitions = 1
        case_shards = 1
        cases_per_shard = 1
        lineage = None
        history = None

    default_searches = int(Settings.model_fields["max_searches"].default)
    default_tokens = int(Settings.model_fields["max_research_tokens"].default)
    per_case_searches = 0
    per_case_tokens = 0
    for profile in matrix.profiles:
        overrides = profile.settings.as_overrides()
        per_case_searches += int(overrides.get("max_searches", default_searches))
        per_case_tokens += int(overrides.get("max_research_tokens", default_tokens))

    runs_per_shard = cases_per_shard * profile_count
    total_shards = repetitions * case_shards
    total_runs = total_shards * runs_per_shard
    per_shard_searches = cases_per_shard * per_case_searches
    per_shard_tokens = cases_per_shard * per_case_tokens
    total_searches = total_shards * per_shard_searches
    total_tokens = total_shards * per_shard_tokens
    plan = ProducerPlan(
        protocol=protocol,
        model=model,
        git_sha=git_sha,
        corpus_path=str(corpus_file),
        matrix_path=str(matrix_file),
        corpus_sha256=sha256_file(corpus_file),
        matrix_sha256=sha256_file(matrix_file),
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        matrix_name=matrix.name,
        matrix_version=matrix.version,
        baseline_profile=matrix.baseline_profile,
        profiles=[profile.name for profile in matrix.profiles],
        case_count=len(corpus.cases) if protocol == "official" else 1,
        repetitions=repetitions,
        case_shards=case_shards,
        cases_per_shard=cases_per_shard,
        runs_per_shard=runs_per_shard,
        total_shards=total_shards,
        total_runs=total_runs,
        max_parallel=max_parallel,
        per_shard_search_call_upper_bound=per_shard_searches,
        per_shard_research_token_upper_bound=per_shard_tokens,
        total_search_call_upper_bound=total_searches,
        total_research_token_upper_bound=total_tokens,
        lineage_mode=lineage,
        history_run_id=history,
        experiment_id=experiment_id,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        compatibility_fingerprint="0" * 64,
    )
    return plan.model_copy(
        update={"compatibility_fingerprint": _fingerprint(_compatibility_payload(plan))}
    )


def validate_producer_plan_integrity(plan: ProducerPlan) -> None:
    expected = _fingerprint(_compatibility_payload(plan))
    if plan.compatibility_fingerprint != expected:
        raise ValueError("producer plan compatibility fingerprint 与内容不一致。")


def expected_official_shards(plan: ProducerPlan) -> list[tuple[int, int, str]]:
    if plan.protocol != "official":
        raise ValueError("只有 official plan 有可恢复 shard。")
    return [
        (
            repetition,
            case_shard,
            f"deepscout-benchmark-shard-r{repetition}-c{case_shard}",
        )
        for repetition in range(1, plan.repetitions + 1)
        for case_shard in range(plan.case_shards)
    ]


def plan_producer_resume(
    current: ProducerPlan,
    *,
    previous: ProducerPlan | None,
    available_artifacts: set[str] | None,
    resume_run_id: str | None,
    max_new_shards: int,
    max_new_search_calls: int | None = None,
    max_new_research_tokens: int | None = None,
) -> ProducerResumePlan:
    validate_producer_plan_integrity(current)
    if current.protocol != "official":
        raise ValueError("resume planning 仅适用于 official protocol。")
    if max_new_shards < 0 or max_new_shards > current.total_shards:
        raise ValueError(f"max_new_shards 必须位于 [0, {current.total_shards}]。")
    if max_new_search_calls is not None and max_new_search_calls < 0:
        raise ValueError("max_new_search_calls 必须 >= 0。")
    if max_new_research_tokens is not None and max_new_research_tokens < 0:
        raise ValueError("max_new_research_tokens 必须 >= 0。")
    if bool(resume_run_id) != bool(previous):
        raise ValueError("resume_run_id 与 previous plan 必须同时存在或同时缺失。")

    blockers: list[str] = []
    reusable: set[str] = set()
    if previous is not None:
        try:
            validate_producer_plan_integrity(previous)
        except ValueError as exc:
            blockers.append(str(exc))
        if previous.protocol != "official":
            blockers.append("resume source 不是 official producer plan")
        if previous.compatibility_fingerprint != current.compatibility_fingerprint:
            blockers.append("resume source producer plan fingerprint mismatch")
        if not available_artifacts:
            blockers.append("resume source 没有可用 artifact")
        else:
            reusable = set(available_artifacts)
            if "deepscout-experiment-bundles" in reusable:
                blockers.append("resume source 已存在 finalized experiment lineage artifact")

    shards = [
        ProducerShardPlan(
            repetition=repetition,
            case_shard=case_shard,
            artifact_name=artifact_name,
            reuse=previous is not None and artifact_name in reusable,
        )
        for repetition, case_shard, artifact_name in expected_official_shards(current)
    ]
    reused_shards = sum(shard.reuse for shard in shards)
    new_shards = len(shards) - reused_shards
    if new_shards > max_new_shards:
        blockers.append(f"new shard budget exceeded: required={new_shards} max={max_new_shards}")

    reused_searches = reused_shards * current.per_shard_search_call_upper_bound
    new_searches = new_shards * current.per_shard_search_call_upper_bound
    reused_tokens = reused_shards * current.per_shard_research_token_upper_bound
    new_tokens = new_shards * current.per_shard_research_token_upper_bound
    if max_new_search_calls is not None and new_searches > max_new_search_calls:
        blockers.append(
            f"search-call budget exceeded: required={new_searches} max={max_new_search_calls}"
        )
    if max_new_research_tokens is not None and new_tokens > max_new_research_tokens:
        blockers.append(
            f"research-token budget exceeded: required={new_tokens} max={max_new_research_tokens}"
        )

    return ProducerResumePlan(
        current_fingerprint=current.compatibility_fingerprint,
        resume_run_id=resume_run_id,
        max_new_shards=max_new_shards,
        max_new_search_calls=max_new_search_calls,
        max_new_research_tokens=max_new_research_tokens,
        total_shards=len(shards),
        reused_shards=reused_shards,
        new_shards=new_shards,
        reused_run_units=reused_shards * current.runs_per_shard,
        new_run_units=new_shards * current.runs_per_shard,
        reused_search_call_upper_bound=reused_searches,
        new_search_call_upper_bound=new_searches,
        reused_research_token_upper_bound=reused_tokens,
        new_research_token_upper_bound=new_tokens,
        passed=not blockers,
        blockers=blockers,
        shards=shards,
    )


def _dispatch_approval_payload(
    current: ProducerPlan,
    resume: ProducerResumePlan,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "producer_fingerprint": current.compatibility_fingerprint,
        "resume_run_id": resume.resume_run_id,
        "max_new_shards": resume.max_new_shards,
        "max_new_search_calls": resume.max_new_search_calls,
        "max_new_research_tokens": resume.max_new_research_tokens,
        "reused_shards": resume.reused_shards,
        "new_shards": resume.new_shards,
        "new_run_units": resume.new_run_units,
        "new_search_call_upper_bound": resume.new_search_call_upper_bound,
        "new_research_token_upper_bound": resume.new_research_token_upper_bound,
        "shard_decisions": [
            shard.model_dump(mode="json")
            for shard in sorted(
                resume.shards,
                key=lambda item: (item.repetition, item.case_shard),
            )
        ],
    }


def build_dispatch_approval(
    current: ProducerPlan,
    resume: ProducerResumePlan,
) -> ProducerDispatchApproval:
    validate_producer_plan_integrity(current)
    if current.protocol != "official":
        raise ValueError("dispatch approval 仅适用于 official protocol。")
    if not resume.passed:
        raise ValueError("resume plan 未通过，不能生成 dispatch approval。")
    if resume.current_fingerprint != current.compatibility_fingerprint:
        raise ValueError("resume plan 与 producer plan fingerprint 不一致。")
    payload = _dispatch_approval_payload(current, resume)
    return ProducerDispatchApproval(
        producer_fingerprint=current.compatibility_fingerprint,
        resume_run_id=resume.resume_run_id,
        max_new_shards=resume.max_new_shards,
        max_new_search_calls=resume.max_new_search_calls,
        max_new_research_tokens=resume.max_new_research_tokens,
        reused_shards=resume.reused_shards,
        new_shards=resume.new_shards,
        new_run_units=resume.new_run_units,
        new_search_call_upper_bound=resume.new_search_call_upper_bound,
        new_research_token_upper_bound=resume.new_research_token_upper_bound,
        shard_decisions=resume.shards,
        approval_digest=_fingerprint(payload),
    )


def validate_dispatch_approval(
    current: ProducerPlan,
    resume: ProducerResumePlan,
    *,
    expected_digest: str,
) -> ProducerDispatchApproval:
    approval = build_dispatch_approval(current, resume)
    if approval.approval_digest != expected_digest:
        raise ValueError(
            "dispatch approval digest mismatch: "
            f"expected={expected_digest} actual={approval.approval_digest}"
        )
    return approval


def validate_history_artifact_inventory(payload: dict[str, object]) -> set[str]:
    names = artifact_names_from_api_response(payload)
    if "deepscout-experiment-bundles" not in names:
        raise ValueError("history run 缺少可用 deepscout-experiment-bundles artifact。")
    return names


def shard_resume_decision(
    plan: ProducerResumePlan,
    *,
    repetition: int,
    case_shard: int,
) -> ProducerShardPlan:
    matches = [
        shard
        for shard in plan.shards
        if shard.repetition == repetition and shard.case_shard == case_shard
    ]
    if len(matches) != 1:
        raise ValueError(
            f"resume plan 缺少唯一 shard: repetition={repetition}, case_shard={case_shard}"
        )
    return matches[0]


def artifact_names_from_api_response(payload: dict[str, object]) -> set[str]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("GitHub artifact API 响应缺少 artifacts list。")
    total = payload.get("total_count", len(artifacts))
    if not isinstance(total, int):
        raise ValueError("GitHub artifact API total_count 非整数。")
    if total > len(artifacts):
        raise ValueError(
            f"artifact API 响应被分页截断: total_count={total} returned={len(artifacts)}"
        )
    names: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("GitHub artifact API 包含无效 artifact 记录。")
        if item.get("expired") is True:
            continue
        names.add(item["name"])
    return names


def validate_shard_provenance_set(
    root: str | Path,
    *,
    current: ProducerPlan,
    resume: ProducerResumePlan,
) -> ProducerProvenanceSummary:
    validate_producer_plan_integrity(current)
    if not resume.passed:
        raise ValueError("resume plan 未通过，不能验证 shard provenance。")
    if resume.current_fingerprint != current.compatibility_fingerprint:
        raise ValueError("resume plan 与 current producer plan fingerprint 不一致。")

    records: dict[tuple[int, int], ProducerShardProvenance] = {}
    for path in sorted(Path(root).rglob("provenance.json")):
        record = ProducerShardProvenance.model_validate_json(path.read_text(encoding="utf-8"))
        key = (record.repetition, record.case_shard)
        if key in records:
            raise ValueError(f"重复 shard provenance: {key}")
        records[key] = record

    if len(records) != current.total_shards:
        raise ValueError(
            f"shard provenance 数量不完整: expected={current.total_shards} actual={len(records)}"
        )

    reused = 0
    for shard in resume.shards:
        key = (shard.repetition, shard.case_shard)
        record = records.get(key)
        if record is None:
            raise ValueError(f"缺失 shard provenance: {key}")
        expected_execution = "reused" if shard.reuse else "executed"
        if record.execution != expected_execution:
            raise ValueError(
                f"shard provenance execution mismatch: {key} "
                f"expected={expected_execution} actual={record.execution}"
            )
        if record.current_run_id != current.workflow_run_id:
            raise ValueError(f"shard provenance current_run_id mismatch: {key}")
        if record.current_run_attempt != current.workflow_run_attempt:
            raise ValueError(f"shard provenance current_run_attempt mismatch: {key}")
        if record.git_sha != current.git_sha:
            raise ValueError(f"shard provenance git_sha mismatch: {key}")
        if record.producer_fingerprint != current.compatibility_fingerprint:
            raise ValueError(f"shard provenance fingerprint mismatch: {key}")
        expected_source = resume.resume_run_id if shard.reuse else None
        if record.source_run_id != expected_source:
            raise ValueError(
                f"shard provenance source_run_id mismatch: {key} "
                f"expected={expected_source!r} actual={record.source_run_id!r}"
            )
        reused += int(shard.reuse)

    executed = current.total_shards - reused
    if reused != resume.reused_shards or executed != resume.new_shards:
        raise ValueError("shard provenance 汇总与 resume plan 计数不一致。")
    return ProducerProvenanceSummary(
        total_shards=current.total_shards,
        reused_shards=reused,
        executed_shards=executed,
        reused_run_units=reused * current.runs_per_shard,
        executed_run_units=executed * current.runs_per_shard,
    )
