"""Benchmark corpus 加载、执行与单 Case 评测。"""

import json
from collections.abc import Mapping
from pathlib import Path
from time import monotonic
from typing import Any

from deepscout.evaluation.metrics import calculate_metrics, evaluate_expectations
from deepscout.evaluation.models import (
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkPricing,
    BenchmarkRunResult,
)
from deepscout.evaluation.trajectory import TrajectoryRecorder


def load_corpus(path: str | Path) -> BenchmarkCorpus:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkCorpus.model_validate(payload)


def _input_state(case: BenchmarkCase) -> dict[str, Any]:
    return {
        "query": case.query,
        "task_results": [],
        "iteration": 0,
        "require_approval": False,
    }


async def run_case(
    graph: Any,
    case: BenchmarkCase,
    pricing: BenchmarkPricing | None = None,
) -> BenchmarkRunResult:
    """串流执行一个 Case，并同时记录 trajectory 与最终 state。"""
    recorder = TrajectoryRecorder()
    started_at = monotonic()
    final_state: Mapping[str, Any] = _input_state(case)
    status = "completed"
    error: str | None = None

    try:
        async for mode, payload in graph.astream(
            _input_state(case),
            stream_mode=["updates", "values"],
        ):
            if mode == "updates":
                recorder.record_update(payload)
                if isinstance(payload, Mapping) and "__interrupt__" in payload:
                    status = "interrupted"
            elif mode == "values" and isinstance(payload, Mapping):
                final_state = payload
    except Exception as exc:  # noqa: BLE001 - benchmark 必须把失败记录成结果
        status = "error"
        error = f"{type(exc).__name__}: {exc}"

    wall_seconds = monotonic() - started_at
    metrics = calculate_metrics(case, final_state, recorder.events, wall_seconds, pricing)
    checks = evaluate_expectations(case, metrics)
    passed = status == "completed" and all(check.passed for check in checks)
    return BenchmarkRunResult(
        case=case,
        status=status,
        passed=passed,
        metrics=metrics,
        expectations=checks,
        trajectory=recorder.events,
        error=error,
    )


async def run_corpus(
    graph: Any,
    corpus: BenchmarkCorpus,
    *,
    limit: int | None = None,
    pricing: BenchmarkPricing | None = None,
) -> list[BenchmarkRunResult]:
    """顺序执行 Corpus，避免并发噪声污染 wall-time 对比。"""
    cases = corpus.cases[:limit] if limit is not None else corpus.cases
    results: list[BenchmarkRunResult] = []
    for case in cases:
        results.append(await run_case(graph, case, pricing))
    return results
