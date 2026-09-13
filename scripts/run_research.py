"""Run one DeepScout research request from the command line."""

import argparse
import asyncio

from deepscout.graph.builder import graph


async def _main(query: str) -> None:
    result = await graph.ainvoke({"query": query, "task_results": [], "iteration": 0})
    print(result.get("final_report", ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a DeepScout research query.")
    parser.add_argument("query")
    args = parser.parse_args()
    asyncio.run(_main(args.query))


if __name__ == "__main__":
    main()
