from pathlib import Path
from xml.etree import ElementTree

import pytest

from deepscout.evaluation.experiment_bundle import load_bundle_manifest
from deepscout.evaluation.experiment_registry import (
    build_experiment_registry,
    registry_entry,
)
from deepscout.evaluation.experiment_registry_report import save_experiment_registry
from tests.test_experiment_bundle import _bundle


def _stamp(
    bundle: Path,
    *,
    created_at: str,
    experiment_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    manifest_path = bundle / "manifest.json"
    manifest = load_bundle_manifest(bundle)
    manifest.created_at = created_at
    if experiment_id is not None:
        manifest.experiment_id = experiment_id
    if provider is not None:
        manifest.provider = provider
    if model is not None:
        manifest.model = model
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def test_registry_keeps_last_known_good_baseline_and_writes_dashboard(tmp_path: Path):
    b1 = _bundle(tmp_path, "b1")
    b2 = _bundle(tmp_path, "b2", quality_shift=-0.10, wall_shift=0.30, gold_shift=-0.10)
    b3 = _bundle(tmp_path, "b3", quality_shift=0.05, wall_shift=-0.10, gold_shift=0.05)
    b4 = _bundle(tmp_path, "b4", quality_shift=0.05, wall_shift=-0.10, gold_shift=0.05)
    _stamp(b1, created_at="2026-09-19T00:00:00+00:00")
    _stamp(b2, created_at="2026-09-19T01:00:00+00:00")
    _stamp(b3, created_at="2026-09-19T02:00:00+00:00")
    _stamp(
        b4,
        created_at="2026-09-19T03:00:00+00:00",
        provider="other-provider",
        model="other-model",
    )

    report = build_experiment_registry(tmp_path)
    entries = {item.experiment_id: item for item in report.entries}

    assert report.bundle_count == 4
    assert report.valid_count == 4
    assert report.invalid_count == 0
    assert report.compatibility_group_count == 1
    assert report.baseline_count == 1
    assert report.accepted_count == 2
    assert report.regression_count == 1

    assert entries["b1"].status == "baseline"
    assert entries["b2"].status == "regression"
    assert entries["b2"].baseline_experiment_id == "b1"
    assert entries["b3"].status == "accepted"
    assert entries["b3"].baseline_experiment_id == "b1"
    assert entries["b4"].status == "accepted"
    assert entries["b4"].baseline_experiment_id == "b3"
    assert any("provider differs" in item for item in entries["b4"].warnings)
    assert any("model differs" in item for item in entries["b4"].warnings)
    assert report.trend_points

    paths = save_experiment_registry(report, tmp_path / "dashboard")
    for key in ("json", "markdown", "entries_csv", "history_csv", "lineage_csv"):
        assert paths[key].exists()
    charts = [path for key, path in paths.items() if key.startswith("chart_")]
    assert charts
    for path in charts:
        ElementTree.parse(path)


def test_registry_excludes_tampered_bundle_from_lineage(tmp_path: Path):
    bad = _bundle(tmp_path, "bad")
    good = _bundle(tmp_path, "good")
    _stamp(bad, created_at="2026-09-19T00:00:00+00:00")
    _stamp(good, created_at="2026-09-19T01:00:00+00:00")

    manifest = load_bundle_manifest(bad)
    repeated = next(item for item in manifest.artifacts if item.role == "repeated")
    (bad / repeated.path).write_text("tampered\n", encoding="utf-8")

    report = build_experiment_registry(tmp_path)
    entries = {item.experiment_id: item for item in report.entries}
    assert report.invalid_count == 1
    assert report.valid_count == 1
    assert entries["bad"].status == "invalid"
    assert entries["good"].status == "baseline"
    assert entries["good"].baseline_experiment_id is None


def test_registry_rejects_duplicate_experiment_ids(tmp_path: Path):
    b1 = _bundle(tmp_path, "left")
    b2 = _bundle(tmp_path, "right")
    _stamp(
        b1,
        created_at="2026-09-19T00:00:00+00:00",
        experiment_id="duplicate",
    )
    _stamp(
        b2,
        created_at="2026-09-19T01:00:00+00:00",
        experiment_id="duplicate",
    )

    report = build_experiment_registry(tmp_path)
    assert report.valid_count == 0
    assert report.invalid_count == 2
    assert report.compatibility_group_count == 0
    assert all(item.status == "invalid" for item in report.entries)
    assert all(
        any("experiment_id 重复" in error for error in item.errors) for item in report.entries
    )
    with pytest.raises(ValueError, match="不唯一"):
        registry_entry(report, "duplicate")
