"""人工 Gold Rubric 双盲评审、agreement 与 adjudication。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from deepscout.evaluation.models import BenchmarkCase, BenchmarkGoldRubric


class HumanReviewPacket(BaseModel):
    blind_item_id: str
    case_id: str
    response_text: str
    rubric: BenchmarkGoldRubric


class CriterionRating(BaseModel):
    criterion_id: str
    score: int = Field(ge=0, le=4)
    notes: str = ""


class HumanGoldReview(BaseModel):
    blind_item_id: str
    case_id: str
    reviewer_id: str
    ratings: list[CriterionRating]
    covered_required_points: list[str] = Field(default_factory=list)
    triggered_critical_errors: list[str] = Field(default_factory=list)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvaluatedHumanReview(BaseModel):
    blind_item_id: str
    case_id: str
    reviewer_id: str
    weighted_score: float = Field(ge=0.0, le=1.0)
    required_point_coverage: float = Field(ge=0.0, le=1.0)
    critical_error_triggered: bool
    passed: bool
    ratings: list[CriterionRating]


class AgreementReport(BaseModel):
    paired_items: int = Field(ge=0)
    pass_agreement_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    cohen_kappa: float | None = Field(default=None, ge=-1.0, le=1.0)
    weighted_kappa: float | None = Field(default=None, ge=-1.0, le=1.0)
    mean_absolute_score_gap: float | None = Field(default=None, ge=0.0)
    disagreements_requiring_adjudication: list[str] = Field(default_factory=list)


class AdjudicationDecision(BaseModel):
    blind_item_id: str
    case_id: str
    adjudicator_id: str
    ratings: list[CriterionRating]
    covered_required_points: list[str] = Field(default_factory=list)
    triggered_critical_errors: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def build_blind_packet(
    case: BenchmarkCase,
    response_text: str,
    *,
    blind_item_id: str | None = None,
) -> HumanReviewPacket:
    if case.gold_rubric is None:
        raise ValueError(f"Case {case.case_id} 没有 gold_rubric。")
    return HumanReviewPacket(
        blind_item_id=blind_item_id or f"blind_{uuid4().hex}",
        case_id=case.case_id,
        response_text=response_text,
        rubric=case.gold_rubric,
    )


def evaluate_human_review(case: BenchmarkCase, review: HumanGoldReview) -> EvaluatedHumanReview:
    rubric = case.gold_rubric
    if rubric is None:
        raise ValueError(f"Case {case.case_id} 没有 gold_rubric。")
    if review.case_id != case.case_id:
        raise ValueError("review.case_id 与 Benchmark Case 不一致。")

    expected_ids = [item.criterion_id for item in rubric.criteria]
    rating_map = {item.criterion_id: item for item in review.ratings}
    if set(rating_map) != set(expected_ids) or len(rating_map) != len(review.ratings):
        raise ValueError("ratings 必须且只能覆盖 rubric 的全部 criterion_id。")

    required = set(rubric.required_points)
    if not set(review.covered_required_points) <= required:
        raise ValueError("covered_required_points 包含 rubric 外条目。")
    critical = set(rubric.critical_errors)
    if not set(review.triggered_critical_errors) <= critical:
        raise ValueError("triggered_critical_errors 包含 rubric 外条目。")

    weighted = round(
        sum(rating_map[item.criterion_id].score / 4.0 * item.weight for item in rubric.criteria),
        12,
    )
    coverage = len(set(review.covered_required_points)) / len(required) if required else 1.0
    critical_triggered = bool(review.triggered_critical_errors)
    return EvaluatedHumanReview(
        blind_item_id=review.blind_item_id,
        case_id=case.case_id,
        reviewer_id=review.reviewer_id,
        weighted_score=weighted,
        required_point_coverage=coverage,
        critical_error_triggered=critical_triggered,
        passed=weighted >= rubric.pass_score and not critical_triggered,
        ratings=review.ratings,
    )


def _cohen_kappa(left: list[int], right: list[int], categories: list[int]) -> float | None:
    if not left or len(left) != len(right):
        return None
    n = len(left)
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / n
    lc, rc = Counter(left), Counter(right)
    expected = sum(lc[c] / n * rc[c] / n for c in categories)
    if abs(1.0 - expected) < 1e-12:
        return 1.0 if observed == 1.0 else None
    return (observed - expected) / (1.0 - expected)


def _quadratic_weighted_kappa(left: list[int], right: list[int]) -> float | None:
    if not left or len(left) != len(right):
        return None
    categories = list(range(5))
    n = len(left)
    lc, rc = Counter(left), Counter(right)

    def weight(a: int, b: int) -> float:
        return 1.0 - ((a - b) / 4.0) ** 2

    observed = sum(weight(a, b) for a, b in zip(left, right, strict=True)) / n
    expected = sum(lc[a] / n * rc[b] / n * weight(a, b) for a in categories for b in categories)
    if abs(1.0 - expected) < 1e-12:
        return 1.0 if observed == 1.0 else None
    return (observed - expected) / (1.0 - expected)


def calculate_inter_rater_agreement(
    evaluated_reviews: list[EvaluatedHumanReview],
    *,
    score_gap_for_adjudication: float = 0.20,
) -> AgreementReport:
    grouped: dict[str, list[EvaluatedHumanReview]] = defaultdict(list)
    for review in evaluated_reviews:
        grouped[review.blind_item_id].append(review)

    pairs: list[tuple[EvaluatedHumanReview, EvaluatedHumanReview]] = []
    for item_id, items in grouped.items():
        if len(items) != 2:
            continue
        if items[0].reviewer_id == items[1].reviewer_id:
            raise ValueError(f"{item_id} 的两个 review reviewer_id 相同。")
        pairs.append((items[0], items[1]))

    if not pairs:
        return AgreementReport(paired_items=0)

    pass_left = [int(a.passed) for a, _ in pairs]
    pass_right = [int(b.passed) for _, b in pairs]
    ordinal_left: list[int] = []
    ordinal_right: list[int] = []
    gaps: list[float] = []
    adjudicate: list[str] = []

    for left, right in pairs:
        gaps.append(abs(left.weighted_score - right.weighted_score))
        if (
            left.passed != right.passed
            or left.critical_error_triggered != right.critical_error_triggered
            or gaps[-1] >= score_gap_for_adjudication
        ):
            adjudicate.append(left.blind_item_id)
        lmap = {r.criterion_id: r.score for r in left.ratings}
        rmap = {r.criterion_id: r.score for r in right.ratings}
        common = sorted(set(lmap) & set(rmap))
        ordinal_left.extend(lmap[key] for key in common)
        ordinal_right.extend(rmap[key] for key in common)

    return AgreementReport(
        paired_items=len(pairs),
        pass_agreement_rate=sum(a == b for a, b in zip(pass_left, pass_right, strict=True))
        / len(pairs),
        cohen_kappa=_cohen_kappa(pass_left, pass_right, [0, 1]),
        weighted_kappa=_quadratic_weighted_kappa(ordinal_left, ordinal_right),
        mean_absolute_score_gap=sum(gaps) / len(gaps),
        disagreements_requiring_adjudication=sorted(adjudicate),
    )


def evaluate_adjudication(
    case: BenchmarkCase, decision: AdjudicationDecision
) -> EvaluatedHumanReview:
    review = HumanGoldReview(
        blind_item_id=decision.blind_item_id,
        case_id=decision.case_id,
        reviewer_id=f"adjudicator:{decision.adjudicator_id}",
        ratings=decision.ratings,
        covered_required_points=decision.covered_required_points,
        triggered_critical_errors=decision.triggered_critical_errors,
        submitted_at=decision.decided_at,
    )
    return evaluate_human_review(case, review)
