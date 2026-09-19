"""创建 Producer Plan、恢复计划并查询 shard 复用决策。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepscout.evaluation.producer_plan import (
    ProducerPlan,
    ProducerResumePlan,
    artifact_names_from_api_response,
    build_dispatch_approval,
    build_producer_plan,
    plan_producer_resume,
    shard_resume_decision,
    validate_dispatch_approval,
    validate_history_artifact_inventory,
    validate_shard_provenance_set,
)


def _load_plan(path: Path) -> ProducerPlan:
    return ProducerPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _write_model(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _create(args: argparse.Namespace) -> int:
    plan = build_producer_plan(
        corpus_path=args.corpus,
        matrix_path=args.matrix,
        protocol=args.protocol,
        model=args.model,
        git_sha=args.git_sha,
        lineage_mode=args.lineage_mode,
        history_run_id=args.history_run_id or None,
        experiment_id=args.experiment_id,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        max_parallel=args.max_parallel,
    )
    _write_model(args.output, plan)
    print(
        f"protocol={plan.protocol} experiment_id={plan.experiment_id} "
        f"runs={plan.total_runs} shards={plan.total_shards} "
        f"search_upper={plan.total_search_call_upper_bound} "
        f"research_token_upper={plan.total_research_token_upper_bound} "
        f"fingerprint={plan.compatibility_fingerprint}"
    )
    return 0


def _resume(args: argparse.Namespace) -> int:
    current = _load_plan(args.current_plan)
    previous = _load_plan(args.previous_plan) if args.previous_plan else None
    artifact_names: set[str] | None = None
    if args.artifacts_api_json:
        payload = json.loads(args.artifacts_api_json.read_text(encoding="utf-8"))
        artifact_names = artifact_names_from_api_response(payload)

    resume = plan_producer_resume(
        current,
        previous=previous,
        available_artifacts=artifact_names,
        resume_run_id=args.resume_run_id or None,
        max_new_shards=args.max_new_shards,
        max_new_search_calls=args.max_new_search_calls,
        max_new_research_tokens=args.max_new_research_tokens,
    )
    _write_model(args.output, resume)
    print(
        f"passed={str(resume.passed).lower()} reused_shards={resume.reused_shards} "
        f"new_shards={resume.new_shards} reused_runs={resume.reused_run_units} "
        f"new_runs={resume.new_run_units} "
        f"new_search_upper={resume.new_search_call_upper_bound} "
        f"new_research_token_upper={resume.new_research_token_upper_bound} "
        f"blockers={len(resume.blockers)}"
    )
    for blocker in resume.blockers:
        print(f"blocker={blocker}")
    return 0 if resume.passed else 2


def _approval(args: argparse.Namespace) -> int:
    current = _load_plan(args.current_plan)
    resume = ProducerResumePlan.model_validate_json(args.resume_plan.read_text(encoding="utf-8"))
    try:
        if args.expected_digest:
            approval = validate_dispatch_approval(
                current,
                resume,
                expected_digest=args.expected_digest,
            )
        else:
            approval = build_dispatch_approval(current, resume)
    except ValueError as exc:
        print(f"error={exc}")
        return 2
    _write_model(args.output, approval)
    print(
        f"approval_digest={approval.approval_digest} "
        f"reused_shards={approval.reused_shards} new_shards={approval.new_shards} "
        f"new_runs={approval.new_run_units} "
        f"new_search_upper={approval.new_search_call_upper_bound} "
        f"new_research_token_upper={approval.new_research_token_upper_bound}"
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"approval_digest={approval.approval_digest}\n")
    return 0


def _inventory(args: argparse.Namespace) -> int:
    payload = json.loads(args.artifacts_api_json.read_text(encoding="utf-8"))
    try:
        if args.require_history_lineage:
            names = validate_history_artifact_inventory(payload)
        else:
            names = artifact_names_from_api_response(payload)
    except ValueError as exc:
        print(f"error={exc}")
        return 2
    print(f"artifacts={len(names)}")
    for name in sorted(names):
        print(f"artifact={name}")
    return 0


def _shard(args: argparse.Namespace) -> int:
    resume = ProducerResumePlan.model_validate_json(args.resume_plan.read_text(encoding="utf-8"))
    if not resume.passed:
        raise ValueError("resume plan 未通过预算/兼容性校验。")
    shard = shard_resume_decision(
        resume,
        repetition=args.repetition,
        case_shard=args.case_shard,
    )
    print(
        f"repetition={shard.repetition} case_shard={shard.case_shard} "
        f"reuse={str(shard.reuse).lower()} artifact={shard.artifact_name}"
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"reuse={str(shard.reuse).lower()}\n")
            handle.write(f"artifact_name={shard.artifact_name}\n")
    return 0


def _provenance(args: argparse.Namespace) -> int:
    current = _load_plan(args.current_plan)
    resume = ProducerResumePlan.model_validate_json(args.resume_plan.read_text(encoding="utf-8"))
    summary = validate_shard_provenance_set(
        args.shards_root,
        current=current,
        resume=resume,
    )
    _write_model(args.output, summary)
    print(
        f"total={summary.total_shards} reused={summary.reused_shards} "
        f"executed={summary.executed_shards} "
        f"reused_runs={summary.reused_run_units} "
        f"executed_runs={summary.executed_run_units}"
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--corpus", default="benchmarks/corpora/core.json")
    create.add_argument("--matrix", default="benchmarks/ablations/core.json")
    create.add_argument("--protocol", choices=("smoke", "official"), required=True)
    create.add_argument("--model", required=True)
    create.add_argument("--git-sha", required=True)
    create.add_argument("--lineage-mode", choices=("continue", "new"), default=None)
    create.add_argument("--history-run-id", default="")

    create.add_argument("--experiment-id", required=True)
    create.add_argument("--workflow-run-id", required=True)
    create.add_argument("--workflow-run-attempt", type=int, required=True)
    create.add_argument("--max-parallel", type=int, default=2)
    create.add_argument("--output", type=Path, required=True)
    create.set_defaults(handler=_create)

    resume = sub.add_parser("resume")
    resume.add_argument("--current-plan", type=Path, required=True)
    resume.add_argument("--previous-plan", type=Path, default=None)
    resume.add_argument("--artifacts-api-json", type=Path, default=None)
    resume.add_argument("--resume-run-id", default="")
    resume.add_argument("--max-new-shards", type=int, required=True)
    resume.add_argument("--max-new-search-calls", type=int, default=None)
    resume.add_argument("--max-new-research-tokens", type=int, default=None)
    resume.add_argument("--output", type=Path, required=True)
    resume.set_defaults(handler=_resume)

    approval = sub.add_parser("approval")
    approval.add_argument("--current-plan", type=Path, required=True)
    approval.add_argument("--resume-plan", type=Path, required=True)
    approval.add_argument("--expected-digest", default="")
    approval.add_argument("--output", type=Path, required=True)
    approval.add_argument("--github-output", type=Path, default=None)
    approval.set_defaults(handler=_approval)

    inventory = sub.add_parser("inventory")
    inventory.add_argument("--artifacts-api-json", type=Path, required=True)
    inventory.add_argument("--require-history-lineage", action="store_true")
    inventory.set_defaults(handler=_inventory)

    shard = sub.add_parser("shard")
    shard.add_argument("--resume-plan", type=Path, required=True)
    shard.add_argument("--repetition", type=int, required=True)
    shard.add_argument("--case-shard", type=int, required=True)
    shard.add_argument("--github-output", type=Path, default=None)
    shard.set_defaults(handler=_shard)

    provenance = sub.add_parser("provenance")
    provenance.add_argument("--current-plan", type=Path, required=True)
    provenance.add_argument("--resume-plan", type=Path, required=True)
    provenance.add_argument("--shards-root", type=Path, required=True)
    provenance.add_argument("--output", type=Path, required=True)
    provenance.set_defaults(handler=_provenance)

    return parser


def main() -> int:
    args = _parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
