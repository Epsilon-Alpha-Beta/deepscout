"""Tavily-backed web search tool."""

import json
from typing import Any

from langchain_core.tools import tool
from tavily import TavilyClient

from deepscout.config import get_settings


@tool(parse_docstring=True)
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return compact source records.

    Args:
        query: Search query.
        max_results: Requested maximum result count.

    Returns:
        JSON text containing source records.
    """
    bounded_max = max(1, min(max_results, get_settings().search_max_results))
    response: dict[str, Any] = TavilyClient().search(
        query=query, max_results=bounded_max, search_depth="advanced"
    )
    compact = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score"),
        }
        for r in response.get("results", [])
    ]
    return json.dumps({"query": query, "results": compact}, ensure_ascii=False)
