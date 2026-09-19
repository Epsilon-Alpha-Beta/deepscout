"""可复现 Experiment Bundle：资产复制、哈希校验与实验身份记录。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from deepscout import __version__
from deepscout.evaluation.quality_aggregate import RuntimeQualityAggregateReport
from deepscout.evaluation.repeated import RepeatedExperimentReport


class ExperimentArtifact(BaseModel):
    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class ExperimentIdentity(BaseModel):
    corpus_name: str
    corpus_version: str
    matrix_name: str
    matrix_version: str
    baseline_profile: str
    profiles: list[str]
    repetitions: int = Field(ge=1)


class ExperimentBundleManifest(BaseModel):
    schema_version: str = "1.0"
    experiment_id: str
    created_at: str
    project_version: str
    git_sha: str
    git_dirty: bool
    provider: str | None = None
    model: str | None = None
    identity: ExperimentIdentity
    config: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ExperimentArtifact]


class BundleValidationReport(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    checked_artifacts: int = Field(ge=0)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_metadata(repo_root: Path) -> tuple[str, bool]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=repo_root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            "无法从 repo_root 读取 Git metadata；请显式提供 git_sha/git_dirty。"
        ) from exc
    if not sha:
        raise ValueError("Git SHA 为空；请显式提供 git_sha/git_dirty。")
    return sha, dirty


def _artifact_record(role: str, relative_path: Path, absolute_path: Path) -> ExperimentArtifact:
    return ExperimentArtifact(
        role=role,
        path=relative_path.as_posix(),
        sha256=sha256_file(absolute_path),
        size_bytes=absolute_path.stat().st_size,
    )


def _load_repeated(path: Path) -> RepeatedExperimentReport:
    return RepeatedExperimentReport.model_validate_json(path.read_text(encoding="utf-8"))


def _profile_set(report: RepeatedExperimentReport) -> list[str]:
    return sorted({record.profile for record in report.runs})


def _json_identity_check(role: str, path: Path, identity: ExperimentIdentity) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if role == "corpus":
        if payload.get("name") != identity.corpus_name:
            errors.append("corpus name mismatch")
        if payload.get("version") != identity.corpus_version:
            errors.append("corpus version mismatch")
    elif role == "matrix":
        if payload.get("name") != identity.matrix_name:
            errors.append("matrix name mismatch")
        if payload.get("version") != identity.matrix_version:
            errors.append("matrix version mismatch")
        if payload.get("baseline_profile") != identity.baseline_profile:
            errors.append("matrix baseline mismatch")
        profiles = sorted(item.get("name") for item in payload.get("profiles", []))
        if profiles != identity.profiles:
            errors.append("matrix profile set mismatch")
    return errors


def create_experiment_bundle(
    *,
    repeated_path: str | Path,
    output_dir: str | Path,
    corpus_path: str | Path | None = None,
    matrix_path: str | Path | None = None,
    quality_aggregate_path: str | Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    experiment_id: str | None = None,
    config: dict[str, Any] | None = None,
    extra_artifacts: dict[str, str | Path] | None = None,
    repo_root: str | Path = ".",
    git_sha: str | None = None,
    git_dirty: bool | None = None,
) -> ExperimentBundleManifest:
    output = Path(output_dir)
    artifacts_dir = output / "artifacts"
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"输出目录必须为空: {output}")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    repeated_source = Path(repeated_path).resolve()
    repeated = _load_repeated(repeated_source)
    if git_sha is None:
        resolved_sha, resolved_dirty = _git_metadata(Path(repo_root).resolve())
    else:
        resolved_sha = git_sha
        resolved_dirty = bool(git_dirty)
    identity = ExperimentIdentity(
        corpus_name=repeated.corpus_name,
        corpus_version=repeated.corpus_version,
        matrix_name=repeated.matrix_name,
        matrix_version=repeated.matrix_version,
        baseline_profile=repeated.baseline_profile,
        profiles=_profile_set(repeated),
        repetitions=repeated.repetitions,
    )
    sources: list[tuple[str, Path]] = [("repeated", repeated_source)]
    for role, value in (
        ("corpus", corpus_path),
        ("matrix", matrix_path),
        ("quality_aggregate", quality_aggregate_path),
    ):
        if value is not None:
            sources.append((role, Path(value).resolve()))
    for role, value in sorted((extra_artifacts or {}).items()):
        sources.append((role, Path(value).resolve()))

    roles: set[str] = set()
    records: list[ExperimentArtifact] = []
    for role, source in sources:
        if role in roles:
            raise ValueError(f"artifact role 重复: {role}")
        roles.add(role)
        if not source.is_file():
            raise ValueError(f"artifact 不存在或不是文件: {source}")
        if role in {"corpus", "matrix"}:
            identity_errors = _json_identity_check(role, source, identity)
            if identity_errors:
                raise ValueError(f"{role} 与 repeated identity 不一致: {identity_errors}")
        suffix = "".join(source.suffixes) or ".bin"
        target = artifacts_dir / f"{role}{suffix}"
        shutil.copy2(source, target)
        records.append(_artifact_record(role, target.relative_to(output), target))

    if quality_aggregate_path is not None:
        quality = RuntimeQualityAggregateReport.model_validate_json(
            Path(quality_aggregate_path).read_text(encoding="utf-8")
        )
        fields = (
            quality.corpus_name,
            quality.corpus_version,
            quality.matrix_name,
            quality.matrix_version,
            quality.baseline_profile,
            quality.repetitions,
        )
        expected = (
            identity.corpus_name,
            identity.corpus_version,
            identity.matrix_name,
            identity.matrix_version,
            identity.baseline_profile,
            identity.repetitions,
        )
        if fields != expected:
            raise ValueError("quality aggregate 与 repeated experiment identity 不一致。")

    manifest = ExperimentBundleManifest(
        experiment_id=experiment_id
        or f"exp-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{resolved_sha[:8]}",
        created_at=datetime.now(UTC).isoformat(),
        project_version=__version__,
        git_sha=resolved_sha,
        git_dirty=resolved_dirty,
        provider=provider,
        model=model,
        identity=identity,
        config={
            "order_strategy": repeated.order_strategy,
            "bootstrap_resamples": repeated.bootstrap_resamples,
            "confidence_level": repeated.confidence_level,
            "bootstrap_seed": repeated.bootstrap_seed,
            **(config or {}),
        },
        artifacts=records,
    )
    (output / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def load_bundle_manifest(bundle_dir: str | Path) -> ExperimentBundleManifest:
    path = Path(bundle_dir) / "manifest.json"
    return ExperimentBundleManifest.model_validate_json(path.read_text(encoding="utf-8"))


def artifact_path(bundle_dir: str | Path, manifest: ExperimentBundleManifest, role: str) -> Path:
    record = next((item for item in manifest.artifacts if item.role == role), None)
    if record is None:
        raise KeyError(f"bundle 不包含 artifact role: {role}")
    return Path(bundle_dir) / record.path


def validate_experiment_bundle(bundle_dir: str | Path) -> BundleValidationReport:
    root = Path(bundle_dir)
    errors: list[str] = []
    try:
        manifest = load_bundle_manifest(root)
    except Exception as exc:
        return BundleValidationReport(
            valid=False, errors=[f"manifest: {type(exc).__name__}: {exc}"], checked_artifacts=0
        )
    roles: set[str] = set()
    checked = 0
    for artifact in manifest.artifacts:
        if artifact.role in roles:
            errors.append(f"duplicate role: {artifact.role}")
        roles.add(artifact.role)
        path = (root / artifact.path).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            errors.append(f"artifact 越出 bundle 目录: {artifact.path}")
            continue
        if not path.is_file():
            errors.append(f"artifact 缺失: {artifact.path}")
            continue
        checked += 1
        if path.stat().st_size != artifact.size_bytes:
            errors.append(f"size mismatch: {artifact.role}")
        if sha256_file(path) != artifact.sha256:
            errors.append(f"sha256 mismatch: {artifact.role}")
    for role in ("corpus", "matrix"):
        if role in roles:
            try:
                errors.extend(
                    f"{role}: {item}"
                    for item in _json_identity_check(
                        role, artifact_path(root, manifest, role), manifest.identity
                    )
                )
            except Exception as exc:
                errors.append(f"{role} parse: {type(exc).__name__}: {exc}")

    if "repeated" not in roles:
        errors.append("缺少 required artifact: repeated")
    else:
        try:
            repeated = _load_repeated(artifact_path(root, manifest, "repeated"))
            current = ExperimentIdentity(
                corpus_name=repeated.corpus_name,
                corpus_version=repeated.corpus_version,
                matrix_name=repeated.matrix_name,
                matrix_version=repeated.matrix_version,
                baseline_profile=repeated.baseline_profile,
                profiles=_profile_set(repeated),
                repetitions=repeated.repetitions,
            )
            if current != manifest.identity:
                errors.append("manifest identity 与 repeated artifact 不一致")
        except Exception as exc:
            errors.append(f"repeated parse: {type(exc).__name__}: {exc}")
    return BundleValidationReport(valid=not errors, errors=errors, checked_artifacts=checked)
