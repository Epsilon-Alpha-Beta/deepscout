"""双人盲评汇总、分歧识别与 adjudication 结果归档。"""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from pydantic import BaseModel, Field

from deepscout.evaluation.human_review import (
    AdjudicationDecision,
    AgreementReport,
    EvaluatedHumanReview,
    HumanGoldReview,
    calculate_inter_rater_agreement,
    evaluate_adjudication,
    evaluate_human_review,
)
from deepscout.evaluation.models import BenchmarkCorpus


class HumanReviewItemOutcome(BaseModel):
    blind_item_id: str
    case_id: str
    reviewer_count: int = Field(ge=0)
    requires_adjudication: bool
    adjudicated: bool
    resolved: bool
    final_score: float | None = Field(default=None, ge=0.0, le=1.0)
    final_passed: bool | None = None


class HumanReviewAuditReport(BaseModel):
    corpus_name: str
    corpus_version: str
    review_count: int = Field(ge=0)
    paired_item_count: int = Field(ge=0)
    resolved_item_count: int = Field(ge=0)
    unresolved_item_count: int = Field(ge=0)
    agreement: AgreementReport
    evaluated_reviews: list[EvaluatedHumanReview]
    item_outcomes: list[HumanReviewItemOutcome]


def build_human_review_audit(
    corpus: BenchmarkCorpus,
    reviews: list[HumanGoldReview],
    *,
    adjudications: list[AdjudicationDecision] | None = None,
    score_gap_for_adjudication: float = 0.20,
) -> HumanReviewAuditReport:
    if not reviews:
        raise ValueError("至少需要一组人工 review，空评审集不能视为已完成。")
    cases = {case.case_id: case for case in corpus.cases}
    evaluated: list[EvaluatedHumanReview] = []
    for review in reviews:
        case = cases.get(review.case_id)
        if case is None:
            raise ValueError(f"未知 case_id: {review.case_id}")
        evaluated.append(evaluate_human_review(case, review))

    agreement = calculate_inter_rater_agreement(
        evaluated,
        score_gap_for_adjudication=score_gap_for_adjudication,
    )
    adjudication_items = adjudications or []
    adjudication_map = {item.blind_item_id: item for item in adjudication_items}
    if len(adjudication_map) != len(adjudication_items):
        raise ValueError("同一个 blind_item_id 只能有一份 adjudication decision。")
    grouped: dict[str, list[EvaluatedHumanReview]] = defaultdict(list)
    for item in evaluated:
        grouped[item.blind_item_id].append(item)

    unknown_adjudications = set(adjudication_map) - set(grouped)
    if unknown_adjudications:
        raise ValueError(
            "adjudication 存在没有 primary review 的 blind_item_id: "
            + ", ".join(sorted(unknown_adjudications))
        )

    outcomes: list[HumanReviewItemOutcome] = []
    requiring = set(agreement.disagreements_requiring_adjudication)

    for blind_item_id, items in sorted(grouped.items()):
        case_ids = {item.case_id for item in items}
        if len(case_ids) != 1:
            raise ValueError(f"{blind_item_id} 的 review 指向多个 case。")
        case_id = next(iter(case_ids))
        if len(items) > 2:
            raise ValueError(f"{blind_item_id} 超过两个 primary reviewers。")

        requires = blind_item_id in requiring or len(items) != 2
        decision = adjudication_map.get(blind_item_id)
        if decision is not None and len(items) != 2:
            raise ValueError(f"{blind_item_id} 必须先完成两个 primary reviews 才能 adjudicate。")
        if decision is not None:
            if decision.case_id != case_id:
                raise ValueError(f"{blind_item_id} adjudication 的 case_id 不一致。")
            final = evaluate_adjudication(cases[case_id], decision)
            outcomes.append(
                HumanReviewItemOutcome(
                    blind_item_id=blind_item_id,
                    case_id=case_id,
                    reviewer_count=len(items),
                    requires_adjudication=requires,
                    adjudicated=True,
                    resolved=True,
                    final_score=final.weighted_score,
                    final_passed=final.passed,
                )
            )
            continue

        if not requires:
            outcomes.append(
                HumanReviewItemOutcome(
                    blind_item_id=blind_item_id,
                    case_id=case_id,
                    reviewer_count=2,
                    requires_adjudication=False,
                    adjudicated=False,
                    resolved=True,
                    final_score=round(fmean(item.weighted_score for item in items), 12),
                    final_passed=all(item.passed for item in items),
                )
            )
        else:
            outcomes.append(
                HumanReviewItemOutcome(
                    blind_item_id=blind_item_id,
                    case_id=case_id,
                    reviewer_count=len(items),
                    requires_adjudication=True,
                    adjudicated=False,
                    resolved=False,
                )
            )

    resolved = sum(item.resolved for item in outcomes)
    return HumanReviewAuditReport(
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        review_count=len(reviews),
        paired_item_count=agreement.paired_items,
        resolved_item_count=resolved,
        unresolved_item_count=len(outcomes) - resolved,
        agreement=agreement,
        evaluated_reviews=evaluated,
        item_outcomes=outcomes,
    )
