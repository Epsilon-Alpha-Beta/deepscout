"""重复 Ablation 分片结果的发现、校验与确定性合并。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from deepscout.evaluation.ablation import AblationMatrix
from deepscout.evaluation.models import BenchmarkCorpus
from deepscout.evaluation.repeated import (
    OrderStrategy,
    RepeatedExperimentReport,
    RepeatedRunRecord,
    build_repeated_report,
)


class RepeatedShardMetadata(BaseModel):
    """一个 producer shard 的目标 repetition 与 case 范围。"""

    repetition: int = Field(ge=1)
    case_shard: int = Field(ge=0)
    case_ids: list[str] = Field(min_length=1)
    repeated_path: str = "run/repeated.json"


class LoadedRepeatedShard(BaseModel):
    """已解析的 shard metadata 与 repeated report。"""

    directory: str
    metadata: RepeatedShardMetadata
    report: RepeatedExperimentReport


def _resolve_inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"shard repeated_path 越出 shard 目录: {relative}") from exc
    return target


def load_repeated_shards(root: str | Path) -> list[LoadedRepeatedShard]:
    """递归发现 shard.json，并加载对应 repeated report。"""

    base = Path(root)
    shards: list[LoadedRepeatedShard] = []
    for metadata_path in sorted(base.rglob("shard.json")):
        directory = metadata_path.parent
        metadata = RepeatedShardMetadata.model_validate_json(
            metadata_path.read_text(encoding="utf-8")
        )
        repeated_path = _resolve_inside(directory, metadata.repeated_path)
        if not repeated_path.is_file():
            raise ValueError(f"shard repeated report 不存在: {repeated_path}")
        report = RepeatedExperimentReport.model_validate_json(
            repeated_path.read_text(encoding="utf-8")
        )
        shards.append(
            LoadedRepeatedShard(
                directory=str(directory),
                metadata=metadata,
                report=report,
            )
        )
    if not shards:
        raise ValueError(f"未发现 shard.json: {base}")
    return sorted(
        shards,
        key=lambda item: (item.metadata.repetition, item.metadata.case_shard),
    )


def _report_identity(report: RepeatedExperimentReport) -> tuple[object, ...]:
    return (
        report.corpus_name,
        report.corpus_version,
        report.matrix_name,
        report.matrix_version,
        report.baseline_profile,
    )


def _canonical_identity(corpus: BenchmarkCorpus, matrix: AblationMatrix) -> tuple[object, ...]:
    return (
        corpus.name,
        corpus.version,
        matrix.name,
        matrix.version,
        matrix.baseline_profile,
    )


def _ordered_profiles(
    matrix: AblationMatrix,
    repetition: int,
    strategy: OrderStrategy,
) -> list[str]:
    names = [profile.name for profile in matrix.profiles]
    if strategy == "fixed" or len(names) <= 1:
        return names
    offset = (repetition - 1) % len(names)
    return names[offset:] + names[:offset]


def _validate_shard_config(shards: list[LoadedRepeatedShard]) -> tuple[int, float, int]:
    first = shards[0].report
    expected = (
        first.bootstrap_resamples,
        first.confidence_level,
        first.bootstrap_seed,
    )
    for shard in shards:
        report = shard.report
        current = (
            report.bootstrap_resamples,
            report.confidence_level,
            report.bootstrap_seed,
        )
        if current != expected:
            raise ValueError("shard bootstrap 配置不一致。")
        if report.repetitions != 1:
            raise ValueError("producer shard 必须使用 repetitions=1。")
        if report.order_strategy != "fixed":
            raise ValueError("producer shard 必须使用 order_strategy=fixed。")
    return expected


def merge_repeated_shards(
    corpus: BenchmarkCorpus,
    matrix: AblationMatrix,
    shards: list[LoadedRepeatedShard],
    *,
    repetitions: int,
    order_strategy: OrderStrategy = "rotate",
) -> RepeatedExperimentReport:
    """把 case/repetition shards 合并为完整、无重复、顺序确定的 repeated report。"""

    if repetitions < 1:
        raise ValueError("repetitions 必须 >= 1。")
    if not shards:
        raise ValueError("至少需要一个 repeated shard。")

    canonical_identity = _canonical_identity(corpus, matrix)
    canonical_cases = {case.case_id: case for case in corpus.cases}
    profile_names = {profile.name for profile in matrix.profiles}
    index: dict[tuple[int, str, str], RepeatedRunRecord] = {}
    seen_shards: set[tuple[int, int]] = set()

    for shard in shards:
        meta = shard.metadata
        report = shard.report
        shard_key = (meta.repetition, meta.case_shard)
        if shard_key in seen_shards:
            raise ValueError(
                f"重复 shard metadata: repetition={meta.repetition}, case_shard={meta.case_shard}"
            )
        seen_shards.add(shard_key)
        if not 1 <= meta.repetition <= repetitions:
            raise ValueError(f"shard repetition 超出范围: {meta.repetition}")
        if len(meta.case_ids) != len(set(meta.case_ids)):
            raise ValueError(
                f"shard case_ids 重复: repetition={meta.repetition}, case_shard={meta.case_shard}"
            )
        if _report_identity(report) != canonical_identity:
            raise ValueError(f"shard identity 与 canonical corpus/matrix 不一致: {shard.directory}")

        actual_case_ids = {record.result.case.case_id for record in report.runs}
        if actual_case_ids != set(meta.case_ids):
            raise ValueError(f"shard metadata case_ids 与 repeated runs 不一致: {shard.directory}")
        expected_profile_order = {
            profile: order
            for order, profile in enumerate(
                _ordered_profiles(matrix, meta.repetition, order_strategy)
            )
        }

        for record in report.runs:
            if record.repetition != 1:
                raise ValueError(f"shard source repetition 必须为 1: {shard.directory}")
            case_id = record.result.case.case_id
            if case_id not in canonical_cases:
                raise ValueError(f"shard 包含未知 case: {case_id}")
            if record.result.case != canonical_cases[case_id]:
                raise ValueError(f"shard case 内容与 canonical corpus 不一致: {case_id}")
            if record.profile not in profile_names:
                raise ValueError(f"shard 包含未知 profile: {record.profile}")
            if record.profile_order != expected_profile_order[record.profile]:
                raise ValueError(
                    "shard profile rotation 不一致: "
                    f"repetition={meta.repetition}, profile={record.profile}, "
                    f"expected={expected_profile_order[record.profile]}, "
                    f"actual={record.profile_order}"
                )
            key = (meta.repetition, record.profile, case_id)
            if key in index:
                raise ValueError(
                    "重复 repeated unit: "
                    f"repetition={meta.repetition}, profile={record.profile}, case={case_id}"
                )
            index[key] = record

    expected_keys = {
        (repetition, profile.name, case.case_id)
        for repetition in range(1, repetitions + 1)
        for profile in matrix.profiles
        for case in corpus.cases
    }
    missing = sorted(expected_keys.difference(index))
    extra = sorted(set(index).difference(expected_keys))
    if missing or extra:
        preview = ", ".join(str(item) for item in missing[:3])
        raise ValueError(
            f"repeated shard coverage 不完整: missing={len(missing)} extra={len(extra)}"
            + (f" first_missing={preview}" if preview else "")
        )

    bootstrap_resamples, confidence_level, bootstrap_seed = _validate_shard_config(shards)
    merged_records: list[RepeatedRunRecord] = []
    execution_order = 0
    for repetition in range(1, repetitions + 1):
        for profile_order, profile in enumerate(
            _ordered_profiles(matrix, repetition, order_strategy)
        ):
            for case in corpus.cases:
                source = index[(repetition, profile, case.case_id)]
                merged_records.append(
                    source.model_copy(
                        update={
                            "repetition": repetition,
                            "execution_order": execution_order,
                            "profile_order": profile_order,
                        }
                    )
                )
                execution_order += 1

    return build_repeated_report(
        corpus,
        matrix,
        merged_records,
        repetitions=repetitions,
        order_strategy=order_strategy,
        bootstrap_resamples=bootstrap_resamples,
        confidence_level=confidence_level,
        bootstrap_seed=bootstrap_seed,
    )
