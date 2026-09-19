from pathlib import Path

from deepscout.evaluation.experiment_bundle import load_bundle_manifest
from deepscout.evaluation.experiment_registry import build_experiment_registry
from deepscout.evaluation.release_gate import (
    ReleaseGatePolicy,
    evaluate_release_gate,
)
from deepscout.evaluation.release_gate_report import save_release_gate_report
from tests.test_experiment_lifecycle import _history


def test_release_gate_passes_accepted_candidate_and_protects_it(tmp_path: Path):
    _, registry = _history(tmp_path)
    report = evaluate_release_gate(registry, "b3", actor="ci")

    assert report.passed is True
    assert report.status == "passed"
    assert report.promotion.action == "promote"
    assert "b3" in report.retention.promoted_ids
    action = next(item for item in report.retention.actions if item.experiment_id == "b3")
    assert action.action == "keep"
    assert any("promoted" in reason for reason in action.reasons)


def test_release_gate_blocks_regression_candidate(tmp_path: Path):
    _, registry = _history(tmp_path)
    report = evaluate_release_gate(registry, "b2")

    assert report.passed is False
    assert report.status == "blocked"
    assert report.promotion.action == "hold"
    assert any("not promotable" in blocker for blocker in report.blockers)


def test_release_gate_blocks_invalid_registry_by_default(tmp_path: Path):
    bundles, _ = _history(tmp_path)
    manifest = load_bundle_manifest(bundles["b7"])
    repeated = next(item for item in manifest.artifacts if item.role == "repeated")
    (bundles["b7"] / repeated.path).write_text("tampered\n", encoding="utf-8")
    registry = build_experiment_registry(tmp_path)

    strict = evaluate_release_gate(registry, "b3")
    assert strict.passed is False
    assert strict.registry_invalid_count == 1
    assert any("invalid bundle" in blocker for blocker in strict.blockers)

    relaxed = evaluate_release_gate(
        registry,
        "b3",
        policy=ReleaseGatePolicy(require_zero_invalid_registry=False),
    )
    assert relaxed.passed is True
    assert any("invalid bundle" in warning for warning in relaxed.warnings)


def test_release_gate_report_writes_unified_audit_artifacts(tmp_path: Path):
    bundles_root = tmp_path / "bundles"
    bundles_root.mkdir()
    _, registry = _history(bundles_root)
    report = evaluate_release_gate(registry, "b3", milestone_ids=["b2"])
    paths = save_release_gate_report(report, tmp_path / "gate")

    for path in paths.values():
        assert path.exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Release Readiness Gate" in markdown
    assert "never applies retention deletions" in markdown
