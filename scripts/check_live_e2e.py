"""Run a low-budget live LLM + Tavily end-to-end smoke test."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from uuid import uuid4

from dotenv import load_dotenv


def _provider_key(model: str) -> str:
    provider = model.split(":", 1)[0].lower()
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google_genai": "GOOGLE_API_KEY",
        "google": "GOOGLE_API_KEY",
    }.get(provider, "")


def _prepare_environment() -> list[str]:
    load_dotenv(override=False)
    model = os.getenv("DEEPSCOUT_MODEL", "anthropic:claude-sonnet-4-6")
    required = ["TAVILY_API_KEY"]
    provider_key = _provider_key(model)
    if provider_key:
        required.append(provider_key)
    return [name for name in required if not os.getenv(name)]


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


async def _run(query: str) -> dict:
    _apply_smoke_budget()
    from deepscout.graph.builder import build_graph

    result = await build_graph().ainvoke(
        {
            "query": query,
            "task_results": [],
            "iteration": 0,
            "require_approval": False,
        },
        {"configurable": {"thread_id": f"live-e2e-{uuid4()}"}},
    )
    report = result.get("final_report", "")
    evidence = result.get("evidence_store", [])
    task_results = result.get("task_results", [])
    citation = result.get("citation_report")
    coverage = getattr(citation, "coverage_score", None)
    return {
        "status": "passed" if report else "failed_empty_report",
        "report_chars": len(report),
        "task_results": len(task_results),
        "evidence_items": len(evidence),
        "citation_coverage": coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live DeepScout LLM + Tavily smoke test.")
    parser.add_argument(
        "--query",
        default=(
            "Research the current LangGraph persistence/checkpointing documentation and "
            "summarize three production-relevant capabilities with source URLs."
        ),
    )
    args = parser.parse_args()
    missing = _prepare_environment()
    if missing:
        print(json.dumps({"status": "blocked_missing_credentials", "missing": missing}))
        return 2
    try:
        summary = asyncio.run(_run(args.query))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
