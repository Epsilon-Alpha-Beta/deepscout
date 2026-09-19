"""生成盲评包或汇总双评审/仲裁结果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepscout.evaluation.human_review import (
    AdjudicationDecision,
    HumanGoldReview,
    build_blind_packet,
)
from deepscout.evaluation.quality_aggregate import BlindReviewAssignment
from deepscout.evaluation.review_audit import build_human_review_audit
from deepscout.evaluation.runner import load_corpus
from deepscout.evaluation.runtime_quality_report import save_human_review_audit


def _load_models(directory: Path, model_type):
    items = []
    if not directory.exists():
        return items
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
        items.extend(model_type.model_validate(row) for row in rows)
    return items


def _case(corpus, case_id: str):
    try:
        return next(case for case in corpus.cases if case.case_id == case_id)
    except StopIteration as exc:
        raise ValueError(f"未知 case_id: {case_id}") from exc


def _prepare(args) -> int:
    corpus = load_corpus(args.corpus)
    case = _case(corpus, args.case_id)
    response = args.response_file.read_text(encoding="utf-8")
    packet = build_blind_packet(case, response, blind_item_id=args.blind_item_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(packet.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.assignment_output is not None:
        if args.profile is None or args.repetition is None:
            raise ValueError("--assignment-output 需要同时提供 --profile 和 --repetition。")
        assignment = BlindReviewAssignment(
            blind_item_id=packet.blind_item_id,
            repetition=args.repetition,
            profile=args.profile,
            case_id=packet.case_id,
        )
        args.assignment_output.parent.mkdir(parents=True, exist_ok=True)
        args.assignment_output.write_text(
            assignment.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    print(f"blind_item_id={packet.blind_item_id} case={packet.case_id} output={args.output}")
    return 0


def _audit(args) -> int:
    corpus = load_corpus(args.corpus)
    reviews = _load_models(args.reviews_dir, HumanGoldReview)
    adjudications = (
        _load_models(args.adjudications_dir, AdjudicationDecision) if args.adjudications_dir else []
    )
    report = build_human_review_audit(
        corpus,
        reviews,
        adjudications=adjudications,
        score_gap_for_adjudication=args.score_gap,
    )
    paths = save_human_review_audit(report, args.output_dir)
    print(
        f"reviews={report.review_count} paired={report.paired_item_count} "
        f"resolved={report.resolved_item_count} unresolved={report.unresolved_item_count} "
        f"kappa={report.agreement.cohen_kappa} weighted_kappa={report.agreement.weighted_kappa} "
        f"json={paths['json']}"
    )
    return 0 if report.unresolved_item_count == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--corpus", type=Path, default=Path("benchmarks/corpora/core.json"))
    prepare.add_argument("--case-id", required=True)
    prepare.add_argument("--response-file", type=Path, required=True)
    prepare.add_argument("--blind-item-id", default=None)
    prepare.add_argument("--profile", default=None)
    prepare.add_argument("--repetition", type=int, default=None)
    prepare.add_argument("--assignment-output", type=Path, default=None)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.set_defaults(handler=_prepare)

    audit = sub.add_parser("audit")
    audit.add_argument("--corpus", type=Path, default=Path("benchmarks/corpora/core.json"))
    audit.add_argument("--reviews-dir", type=Path, required=True)
    audit.add_argument("--adjudications-dir", type=Path, default=None)
    audit.add_argument("--score-gap", type=float, default=0.20)
    audit.add_argument(
        "--output-dir", type=Path, default=Path("benchmark-results/human-review-latest")
    )
    audit.set_defaults(handler=_audit)
    args = parser.parse_args()
    if not 0.0 <= getattr(args, "score_gap", 0.2) <= 1.0:
        parser.error("--score-gap 必须位于 [0,1]。")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
