"""Phase 1 tool registry."""

from langchain_core.tools import BaseTool

from deepscout.tools.web_search import web_search


def get_research_tools() -> list[BaseTool]:
    return [web_search]
