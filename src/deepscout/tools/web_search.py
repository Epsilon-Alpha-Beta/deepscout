"""Tavily-backed web search tool."""

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from langchain_core.tools import tool
from tavily import TavilyClient

from deepscout.config import get_settings
from deepscout.evidence.metadata import classify_source_url
from deepscout.runtime.search_budget import consume_search


def _normalize_published_at(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


@tool(parse_docstring=True)
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return compact source records.

    Args:
        query: Search query.
        max_results: Requested maximum result count.

    Returns:
        JSON text containing source records.
    """
    if not consume_search():
        return json.dumps(
            {"query": query, "results": [], "error": "search_budget_exhausted"},
            ensure_ascii=False,
        )

    bounded_max = max(1, min(max_results, get_settings().search_max_results))
    response: dict[str, Any] = TavilyClient().search(
        query=query, max_results=bounded_max, search_depth="advanced"
    )
    retrieved_at = datetime.now(UTC).isoformat()
    compact = []
    for item in response.get("results", []):
        url = item.get("url", "")
        compact.append(
            {
                "title": item.get("title", ""),
                "url": url,
                "content": item.get("content", ""),
                "score": item.get("score"),
                "source_class": classify_source_url(url),
                "published_at": _normalize_published_at(
                    item.get("published_date") or item.get("published_at")
                ),
                "retrieved_at": retrieved_at,
            }
        )
    return json.dumps({"query": query, "results": compact}, ensure_ascii=False)
