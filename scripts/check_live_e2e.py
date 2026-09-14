"""Run staged live Provider + Tavily + DeepScout end-to-end diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from uuid import uuid4

from dotenv import load_dotenv


@dataclass
class ProbeResult:
    stage: str
    status: str
    duration_seconds: float
    details: dict[str, object]


def _provider_key(model: str) -> str:
    provider = model.split(":", 1)[0].lower()
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google_genai": "GOOGLE_API_KEY",
        "google": "GOOGLE_API_KEY",
    }.get(provider, "")


def _prepare_environment() -> tuple[str, list[str]]:
    load_dotenv(override=False)
    model = os.getenv("DEEPSCOUT_MODEL", "anthropic:claude-sonnet-4-6")
    required = ["TAVILY_API_KEY"]
    provider_key = _provider_key(model)
    if provider_key:
        required.append(provider_key)
    return model, [name for name in required if not os.getenv(name)]


def _apply_smoke_budget() -> None:
    defaults = {
        "DEEPSCOUT_MAX_CONCURRENCY": "1",
        "DEEPSCOUT_MAX_REPLANS": "0",
        "DEEPSCOUT_MAX_RESEARCH_TASKS": "3",
        "DEEPSCOUT_MAX_EVIDENCE_ITEMS": "12",
        "DEEPSCOUT_MAX_SEARCHES": "4",
        "DEEPSCOUT_MAX_RESEARCH_TOKENS": "30000",
        "DEEPSCOUT_MAX_WORKER_SECONDS": "180",
        "DEEPSCOUT_SEARCH_MAX_CALLS_PER_TASK": "2",
        "DEEPSCOUT_SEARCH_MAX_RESULTS": "3",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)


async def _provider_probe(model: str, timeout: float) -> ProbeResult:
    from langchain_core.messages import HumanMessage

    from deepscout.llm import get_chat_model

    started = time.perf_counter()
    response = await asyncio.wait_for(
        get_chat_model(model).ainvoke([HumanMessage(content="Reply with DEEPSCOUT_OK.")]),
        timeout=timeout,
    )
    content = response.content
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    return ProbeResult(
        stage="provider",
        status="passed",
        duration_seconds=round(time.perf_counter() - started, 3),
        details={"model": model, "response_chars": len(text)},
    )


async def _tavily_probe(timeout: float) -> ProbeResult:
    from tavily import TavilyClient

    started = time.perf_counter()

    def _search() -> dict:
        return TavilyClient().search(
            query="LangGraph persistence checkpointing",
            max_results=1,
            search_depth="basic",
        )

    response = await asyncio.wait_for(asyncio.to_thread(_search), timeout=timeout)
    results = response.get("results", [])
    return ProbeResult(
        stage="tavily",
        status="passed" if results else "failed_no_results",
        duration_seconds=round(time.perf_counter() - started, 3),
        details={"result_count": len(results)},
    )


async def _graph_probe(query: str, timeout: float) -> ProbeResult:
    _apply_smoke_budget()
    from deepscout.graph.builder import build_graph

    started = time.perf_counter()
    result = await asyncio.wait_for(
        build_graph().ainvoke(
            {
                "query": query,
                "task_results": [],
                "iteration": 0,
                "require_approval": False,
            },
            {"configurable": {"thread_id": f"live-e2e-{uuid4()}"}},
        ),
        timeout=timeout,
    )
    report = result.get("final_report", "")
    evidence = result.get("evidence_store", [])
    task_results = result.get("task_results", [])
    citation = result.get("citation_report")
    coverage = getattr(citation, "coverage_score", None)
    return ProbeResult(
        stage="graph",
        status="passed" if report else "failed_empty_report",
        duration_seconds=round(time.perf_counter() - started, 3),
        details={
            "report_chars": len(report),
            "task_results": len(task_results),
            "evidence_items": len(evidence),
            "citation_coverage": coverage,
        },
    )


async def _run_diagnostics(query: str, probe_timeout: float, graph_timeout: float) -> dict:
    model, missing = _prepare_environment()
    if missing:
        return {
            "status": "blocked_missing_credentials",
            "missing": missing,
            "model": model,
            "stages": [],
        }

    stages: list[ProbeResult] = []
    for stage_name, operation in (
        ("provider", lambda: _provider_probe(model, probe_timeout)),
        ("tavily", lambda: _tavily_probe(probe_timeout)),
        ("graph", lambda: _graph_probe(query, graph_timeout)),
    ):
        try:
            result = await operation()
        except Exception as exc:
            stages.append(
                ProbeResult(
                    stage=stage_name,
                    status="failed",
                    duration_seconds=0.0,
                    details={"error_type": type(exc).__name__},
                )
            )
            return {
                "status": "failed",
                "failed_stage": stage_name,
                "model": model,
                "stages": [asdict(item) for item in stages],
            }
        stages.append(result)
        if result.status != "passed":
            return {
                "status": "failed",
                "failed_stage": stage_name,
                "model": model,
                "stages": [asdict(item) for item in stages],
            }

    return {
        "status": "passed",
        "model": model,
        "stages": [asdict(item) for item in stages],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run staged live DeepScout diagnostics.")
    parser.add_argument(
        "--query",
        default=(
            "Research the current LangGraph persistence/checkpointing documentation and "
            "summarize three production-relevant capabilities with source URLs."
        ),
    )
    parser.add_argument("--probe-timeout", type=float, default=30.0)
    parser.add_argument("--graph-timeout", type=float, default=240.0)
    parser.add_argument("--output", help="Optional JSON result file path.")
    args = parser.parse_args()

    summary = asyncio.run(_run_diagnostics(args.query, args.probe_timeout, args.graph_timeout))
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    if summary["status"] == "passed":
        return 0
    if summary["status"] == "blocked_missing_credentials":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
