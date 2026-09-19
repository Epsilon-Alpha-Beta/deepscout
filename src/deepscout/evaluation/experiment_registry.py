"""Experiment Registry：多 Bundle 历史、lineage 与 last-known-good baseline。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.evaluation.experiment_bundle import (
    ExperimentBundleManifest,
    artifact_path,
    load_bundle_manifest,
    validate_experiment_bundle,
)
from deepscout.evaluation.experiment_compare import compare_experiment_bundles
from deepscout.evaluation.quality_aggregate import RuntimeQualityAggregateReport
from deepscout.evaluation.repeated import RepeatedExperimentReport

RegistryStatus = Literal["baseline", "accepted", "regression", "invalid"]


class ExperimentRegistryEntry(BaseModel):
    experiment_id: str
    bundle_path: str
    compatibility_key: str | None = None
    created_at: str | None = None
    project_version: str | None = None
    git_sha: str | None = None
    git_dirty: bool | None = None
    provider: str | None = None
    model: str | None = None
    corpus_name: str | None = None
    corpus_version: str | None = None
    matrix_name: str | None = None
    matrix_version: str | None = None
    baseline_profile: str | None = None
    repetitions: int | None = Field(default=None, ge=1)
    valid: bool
    status: RegistryStatus
    baseline_experiment_id: str | None = None
    regression_count: int = Field(ge=0)
    improvement_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ExperimentTrendPoint(BaseModel):
    experiment_id: str
    created_at: str
    compatibility_key: str
    profile: str
    source: Literal["repeated", "quality"]
    metric: str
    mean: float


class ExperimentRegistryReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: str
    bundles_root: str
    bundle_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    compatibility_group_count: int = Field(ge=0)
    baseline_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    regression_count: int = Field(ge=0)
    entries: list[ExperimentRegistryEntry]
    trend_points: list[ExperimentTrendPoint]


def _parse_created_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def compatibility_key(manifest: ExperimentBundleManifest) -> str:
    identity = manifest.identity
    payload = {
        "corpus_name": identity.corpus_name,
        "corpus_version": identity.corpus_version,
        "matrix_name": identity.matrix_name,
        "matrix_version": identity.matrix_version,
        "baseline_profile": identity.baseline_profile,
        "profiles": identity.profiles,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def discover_experiment_bundles(root: str | Path) -> list[Path]:
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"bundles root 不存在或不是目录: {root_path}")
    return sorted({path.parent for path in root_path.rglob("manifest.json")})


def _load_repeated(bundle: Path, manifest: ExperimentBundleManifest) -> RepeatedExperimentReport:
    return RepeatedExperimentReport.model_validate_json(
        artifact_path(bundle, manifest, "repeated").read_text(encoding="utf-8")
    )


def _load_quality(
    bundle: Path, manifest: ExperimentBundleManifest
) -> RuntimeQualityAggregateReport | None:
    if not any(item.role == "quality_aggregate" for item in manifest.artifacts):
        return None
    return RuntimeQualityAggregateReport.model_validate_json(
        artifact_path(bundle, manifest, "quality_aggregate").read_text(encoding="utf-8")
    )


def _trend_points(
    bundle: Path, manifest: ExperimentBundleManifest, key: str
) -> list[ExperimentTrendPoint]:
    points: list[ExperimentTrendPoint] = []
    repeated = _load_repeated(bundle, manifest)
    for scope in repeated.profile_statistics:
        for metric, stats in scope.metrics.items():
            points.append(
                ExperimentTrendPoint(
                    experiment_id=manifest.experiment_id,
                    created_at=manifest.created_at,
                    compatibility_key=key,
                    profile=scope.profile,
                    source="repeated",
                    metric=metric,
                    mean=stats.mean,
                )
            )
    quality = _load_quality(bundle, manifest)
    if quality is None:
        return points
    for scope in quality.profile_statistics:
        for metric, value in (
            ("source_compliance_rate", scope.source_compliance_rate),
            ("human_gold_pass_rate", scope.human_gold_pass_rate),
        ):
            if value is not None:
                points.append(
                    ExperimentTrendPoint(
                        experiment_id=manifest.experiment_id,
                        created_at=manifest.created_at,
                        compatibility_key=key,
                        profile=scope.profile,
                        source="quality",
                        metric=metric,
                        mean=value,
                    )
                )
        for metric, stats in scope.metrics.items():
            points.append(
                ExperimentTrendPoint(
                    experiment_id=manifest.experiment_id,
                    created_at=manifest.created_at,
                    compatibility_key=key,
                    profile=scope.profile,
                    source="quality",
                    metric=metric,
                    mean=stats.mean,
                )
            )
    return points


def build_experiment_registry(root: str | Path) -> ExperimentRegistryReport:
    root_path = Path(root).resolve()
    bundles = discover_experiment_bundles(root_path)
    entries_by_path: dict[Path, ExperimentRegistryEntry] = {}
    manifests: dict[Path, ExperimentBundleManifest] = {}
    parsed_times: dict[Path, datetime] = {}
    groups: dict[str, list[Path]] = defaultdict(list)
    trend_points: list[ExperimentTrendPoint] = []

    for bundle in bundles:
        bundle = bundle.resolve()
        validation = validate_experiment_bundle(bundle)
        try:
            manifest = load_bundle_manifest(bundle)
            manifests[bundle] = manifest
            created = _parse_created_at(manifest.created_at)
            parsed_times[bundle] = created
        except Exception as exc:
            entries_by_path[bundle] = ExperimentRegistryEntry(
                experiment_id=bundle.name,
                bundle_path=bundle.relative_to(root_path).as_posix(),
                valid=False,
                status="invalid",
                regression_count=0,
                improvement_count=0,
                errors=[*validation.errors, f"manifest metadata: {type(exc).__name__}: {exc}"],
            )
            continue
        if not validation.valid:
            entries_by_path[bundle] = ExperimentRegistryEntry(
                experiment_id=manifest.experiment_id,
                bundle_path=bundle.relative_to(root_path).as_posix(),
                created_at=manifest.created_at,
                project_version=manifest.project_version,
                git_sha=manifest.git_sha,
                git_dirty=manifest.git_dirty,
                provider=manifest.provider,
                model=manifest.model,
                corpus_name=manifest.identity.corpus_name,
                corpus_version=manifest.identity.corpus_version,
                matrix_name=manifest.identity.matrix_name,
                matrix_version=manifest.identity.matrix_version,
                baseline_profile=manifest.identity.baseline_profile,
                repetitions=manifest.identity.repetitions,
                valid=False,
                status="invalid",
                regression_count=0,
                improvement_count=0,
                errors=validation.errors,
            )
            continue
        key = compatibility_key(manifest)
        groups[key].append(bundle)

    experiment_paths: dict[str, list[Path]] = defaultdict(list)
    for key_group in groups.values():
        for bundle in key_group:
            experiment_paths[manifests[bundle].experiment_id].append(bundle)
    for experiment_id, duplicate_paths in experiment_paths.items():
        if len(duplicate_paths) <= 1:
            continue
        for bundle in duplicate_paths:
            manifest = manifests[bundle]
            key = compatibility_key(manifest)
            if bundle in groups[key]:
                groups[key].remove(bundle)
            entries_by_path[bundle] = ExperimentRegistryEntry(
                experiment_id=experiment_id,
                bundle_path=bundle.relative_to(root_path).as_posix(),
                compatibility_key=key,
                created_at=manifest.created_at,
                project_version=manifest.project_version,
                git_sha=manifest.git_sha,
                git_dirty=manifest.git_dirty,
                provider=manifest.provider,
                model=manifest.model,
                corpus_name=manifest.identity.corpus_name,
                corpus_version=manifest.identity.corpus_version,
                matrix_name=manifest.identity.matrix_name,
                matrix_version=manifest.identity.matrix_version,
                baseline_profile=manifest.identity.baseline_profile,
                repetitions=manifest.identity.repetitions,
                valid=False,
                status="invalid",
                regression_count=0,
                improvement_count=0,
                errors=[f"experiment_id 重复: {experiment_id}"],
            )
    groups = {key: paths for key, paths in groups.items() if paths}

    for key, group in groups.items():
        ordered = sorted(
            group, key=lambda path: (parsed_times[path], manifests[path].experiment_id, str(path))
        )
        last_accepted: Path | None = None
        for bundle in ordered:
            manifest = manifests[bundle]
            warnings: list[str] = []
            baseline_id: str | None = None
            regressions = 0
            improvements = 0
            if last_accepted is None:
                status: RegistryStatus = "baseline"
                last_accepted = bundle
            else:
                comparison = compare_experiment_bundles(last_accepted, bundle)
                if not comparison.comparable:
                    raise ValueError(
                        "compatibility key 相同但 comparator 返回 incomparable: "
                        + "; ".join(comparison.incompatibilities)
                    )
                baseline_id = manifests[last_accepted].experiment_id
                warnings.extend(comparison.warnings)
                regressions = comparison.regression_count
                improvements = comparison.improvement_count
                if regressions:
                    status = "regression"
                else:
                    status = "accepted"
                    last_accepted = bundle
            entries_by_path[bundle] = ExperimentRegistryEntry(
                experiment_id=manifest.experiment_id,
                bundle_path=bundle.relative_to(root_path).as_posix(),
                compatibility_key=key,
                created_at=manifest.created_at,
                project_version=manifest.project_version,
                git_sha=manifest.git_sha,
                git_dirty=manifest.git_dirty,
                provider=manifest.provider,
                model=manifest.model,
                corpus_name=manifest.identity.corpus_name,
                corpus_version=manifest.identity.corpus_version,
                matrix_name=manifest.identity.matrix_name,
                matrix_version=manifest.identity.matrix_version,
                baseline_profile=manifest.identity.baseline_profile,
                repetitions=manifest.identity.repetitions,
                valid=True,
                status=status,
                baseline_experiment_id=baseline_id,
                regression_count=regressions,
                improvement_count=improvements,
                warnings=warnings,
            )
            trend_points.extend(_trend_points(bundle, manifest, key))

    entries = sorted(
        entries_by_path.values(),
        key=lambda item: (item.created_at or "", item.experiment_id, item.bundle_path),
    )
    return ExperimentRegistryReport(
        generated_at=datetime.now(UTC).isoformat(),
        bundles_root=str(root_path),
        bundle_count=len(bundles),
        valid_count=sum(item.valid for item in entries),
        invalid_count=sum(not item.valid for item in entries),
        compatibility_group_count=len(groups),
        baseline_count=sum(item.status == "baseline" for item in entries),
        accepted_count=sum(item.status == "accepted" for item in entries),
        regression_count=sum(item.status == "regression" for item in entries),
        entries=entries,
        trend_points=sorted(
            trend_points,
            key=lambda item: (
                item.compatibility_key,
                item.created_at,
                item.profile,
                item.source,
                item.metric,
            ),
        ),
    )


def registry_entry(report: ExperimentRegistryReport, experiment_id: str) -> ExperimentRegistryEntry:
    matches = [item for item in report.entries if item.experiment_id == experiment_id]
    if not matches:
        raise KeyError(f"registry 不包含 experiment_id: {experiment_id}")
    if len(matches) > 1:
        raise ValueError(f"experiment_id 在 registry 中不唯一: {experiment_id}")
    return matches[0]
