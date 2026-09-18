from datetime import UTC, datetime, timedelta

from deepscout.evaluation.human_review import (
    AdjudicationDecision,
    CriterionRating,
    HumanGoldReview,
    calculate_inter_rater_agreement,
    evaluate_adjudication,
    evaluate_human_review,
)
from deepscout.evaluation.runner import load_corpus
from deepscout.evaluation.source_compliance import score_source_policy
from deepscout.evidence.manager import consolidate_evidence
from deepscout.models.evidence import Evidence, ManagedEvidence
from deepscout.models.result import TaskResult


def _case(case_id: str = "framework-comparison"):
    corpus = load_corpus("benchmarks/corpora/core.json")
    return next(case for case in corpus.cases if case.case_id == case_id)


def _managed(**kwargs):
    defaults = dict(
        evidence_id="ev_1",
        title="Source",
        url="https://docs.langchain.com/test",
        canonical_url="https://docs.langchain.com/test",
        source_host="docs.langchain.com",
        content="body",
        content_hash="hash",
        source_type="web",
        source_class="official_docs",
    )
    defaults.update(kwargs)
    return ManagedEvidence(**defaults)


def test_evidence_metadata_survives_consolidation():
    published = datetime(2026, 9, 1, tzinfo=UTC)
    retrieved = datetime(2026, 9, 18, tzinfo=UTC)
    evidence = Evidence(
        title="Docs",
        url="https://docs.langchain.com/test",
        content="same body",
        source_class="official_docs",
        published_at=published,
        retrieved_at=retrieved,
    )
    result = TaskResult(task_id="t1", status="completed", summary="ok", evidence=[evidence])
    managed = consolidate_evidence([result], max_items=10)[0]
    assert managed.source_class == "official_docs"
    assert managed.published_at == published
    assert managed.retrieved_at == retrieved


def test_source_policy_reports_unverifiable_freshness():
    case = _case()
    now = datetime(2026, 9, 18, tzinfo=UTC)
    report = score_source_policy(case, [_managed(published_at=None)], evaluated_at=now)
    freshness = next(check for check in report.checks if check.name == "minimum_recent_sources")
    assert freshness.status == "unverifiable"
    assert report.passed is False


def test_source_policy_passes_with_primary_recent_evidence():
    case = _case()
    now = datetime(2026, 9, 18, tzinfo=UTC)
    evidence = [
        _managed(
            evidence_id=f"ev_{index}",
            published_at=now - timedelta(days=30 * index),
        )
        for index in range(1, 4)
    ]
    report = score_source_policy(case, evidence, evaluated_at=now)
    assert report.primary_source_count >= case.source_policy.min_primary_sources
    assert report.passed is True


def _ratings(case, scores=(4, 4, 4, 4)):
    return [
        CriterionRating(criterion_id=item.criterion_id, score=score)
        for item, score in zip(case.gold_rubric.criteria, scores, strict=True)
    ]


def test_critical_error_blocks_human_review_pass():
    case = _case("distributed-rate-limit")
    review = HumanGoldReview(
        blind_item_id="blind_a",
        case_id=case.case_id,
        reviewer_id="r1",
        ratings=_ratings(case),
        covered_required_points=case.gold_rubric.required_points,
        triggered_critical_errors=[case.gold_rubric.critical_errors[0]],
    )
    evaluated = evaluate_human_review(case, review)
    assert evaluated.weighted_score == 1.0
    assert evaluated.critical_error_triggered is True
    assert evaluated.passed is False


def test_inter_rater_agreement_and_adjudication():
    case = _case("distributed-rate-limit")
    first = HumanGoldReview(
        blind_item_id="blind_a",
        case_id=case.case_id,
        reviewer_id="r1",
        ratings=_ratings(case, (4, 4, 4, 4)),
        covered_required_points=case.gold_rubric.required_points,
    )
    second = HumanGoldReview(
        blind_item_id="blind_a",
        case_id=case.case_id,
        reviewer_id="r2",
        ratings=_ratings(case, (2, 2, 2, 2)),
        covered_required_points=case.gold_rubric.required_points[:2],
    )
    evaluated = [evaluate_human_review(case, first), evaluate_human_review(case, second)]
    agreement = calculate_inter_rater_agreement(evaluated, score_gap_for_adjudication=0.2)
    assert agreement.paired_items == 1
    assert agreement.disagreements_requiring_adjudication == ["blind_a"]

    decision = AdjudicationDecision(
        blind_item_id="blind_a",
        case_id=case.case_id,
        adjudicator_id="a1",
        ratings=_ratings(case, (3, 3, 3, 3)),
        covered_required_points=case.gold_rubric.required_points,
        rationale="Re-read evidence and resolved the disagreement.",
    )
    final = evaluate_adjudication(case, decision)
    assert final.weighted_score == 0.75
    assert final.passed is True


def test_review_audit_requires_adjudication_then_resolves(tmp_path):
    from deepscout.evaluation.review_audit import build_human_review_audit
    from deepscout.evaluation.runtime_quality_report import save_human_review_audit

    case = _case("distributed-rate-limit")
    first = HumanGoldReview(
        blind_item_id="blind_b",
        case_id=case.case_id,
        reviewer_id="r1",
        ratings=_ratings(case, (4, 4, 4, 4)),
        covered_required_points=case.gold_rubric.required_points,
    )
    second = HumanGoldReview(
        blind_item_id="blind_b",
        case_id=case.case_id,
        reviewer_id="r2",
        ratings=_ratings(case, (1, 2, 1, 2)),
        covered_required_points=case.gold_rubric.required_points[:1],
    )
    corpus = load_corpus("benchmarks/corpora/core.json")
    unresolved = build_human_review_audit(corpus, [first, second])
    assert unresolved.unresolved_item_count == 1

    decision = AdjudicationDecision(
        blind_item_id="blind_b",
        case_id=case.case_id,
        adjudicator_id="a1",
        ratings=_ratings(case, (3, 3, 3, 3)),
        covered_required_points=case.gold_rubric.required_points,
        rationale="Resolved after evidence re-check.",
    )
    resolved = build_human_review_audit(corpus, [first, second], adjudications=[decision])
    assert resolved.unresolved_item_count == 0
    paths = save_human_review_audit(resolved, tmp_path)
    assert paths["json"].exists() and paths["markdown"].exists() and paths["csv"].exists()


def test_source_compliance_report_outputs_files(tmp_path):
    from deepscout.evaluation.runtime_quality_report import save_source_compliance_report

    case = _case()
    now = datetime(2026, 9, 18, tzinfo=UTC)
    evidence = [
        _managed(evidence_id=f"ev_{i}", published_at=now - timedelta(days=10 * i))
        for i in range(1, 4)
    ]
    report = score_source_policy(case, evidence, evaluated_at=now)
    paths = save_source_compliance_report(report, tmp_path)
    assert paths["json"].exists()
    assert "Source Policy Compliance" in paths["markdown"].read_text(encoding="utf-8")


def test_evidence_manager_fills_system_metadata_when_model_omits_it():
    evidence = Evidence(
        title="Docs",
        url="https://docs.langchain.com/oss/python/langgraph/overview",
        content="body",
    )
    result = TaskResult(task_id="t1", status="completed", summary="ok", evidence=[evidence])
    managed = consolidate_evidence([result], max_items=10)[0]
    assert managed.source_class == "official_docs"
    assert managed.retrieved_at is not None
    assert managed.published_at is None


def test_human_review_audit_rejects_empty_or_premature_adjudication():
    import pytest

    from deepscout.evaluation.review_audit import build_human_review_audit

    corpus = load_corpus("benchmarks/corpora/core.json")
    case = _case("distributed-rate-limit")
    with pytest.raises(ValueError, match="空评审集"):
        build_human_review_audit(corpus, [])

    single = HumanGoldReview(
        blind_item_id="blind_single",
        case_id=case.case_id,
        reviewer_id="r1",
        ratings=_ratings(case),
        covered_required_points=case.gold_rubric.required_points,
    )
    decision = AdjudicationDecision(
        blind_item_id="blind_single",
        case_id=case.case_id,
        adjudicator_id="a1",
        ratings=_ratings(case),
        covered_required_points=case.gold_rubric.required_points,
        rationale="Premature adjudication should be rejected.",
    )
    with pytest.raises(ValueError, match="两个 primary reviews"):
        build_human_review_audit(corpus, [single], adjudications=[decision])
