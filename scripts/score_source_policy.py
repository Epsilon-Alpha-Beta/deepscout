"""对一个真实 Benchmark Case 的 Evidence 执行来源政策合规评分。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from deepscout.evaluation.runner import load_corpus
from deepscout.evaluation.runtime_quality_report import save_source_compliance_report
from deepscout.evaluation.source_compliance import score_source_policy
from deepscout.models.evidence import ManagedEvidence


def _load_evidence(path: Path) -> list[ManagedEvidence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("evidence_store", payload.get("evidence", []))
    if not isinstance(payload, list):
        raise ValueError("evidence JSON 必须是 list 或包含 evidence_store/evidence 的 object。")
    return [ManagedEvidence.model_validate(item) for item in payload]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/corpora/core.json"))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evaluated-at", default=None)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("benchmark-results/source-compliance-latest")
    )
    args = parser.parse_args()
    corpus = load_corpus(args.corpus)
    try:
        case = next(case for case in corpus.cases if case.case_id == args.case_id)
    except StopIteration as exc:
        raise ValueError(f"未知 case_id: {args.case_id}") from exc
    evaluated_at = datetime.fromisoformat(args.evaluated_at) if args.evaluated_at else None
    report = score_source_policy(case, _load_evidence(args.evidence), evaluated_at=evaluated_at)
    paths = save_source_compliance_report(report, args.output_dir)
    states = {item.status for item in report.checks}
    print(
        f"case={case.case_id} passed={str(report.passed).lower()} "
        f"primary={report.primary_source_count} recent={report.recent_source_count} "
        f"freshness_unknown={report.freshness_unknown_count} json={paths['json']}"
    )
    if report.passed:
        return 0
    return 2 if "unverifiable" in states else 1


if __name__ == "__main__":
    raise SystemExit(main())
