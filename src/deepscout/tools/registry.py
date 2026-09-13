"""统一管理内置研究工具与 MCP 工具。"""

import json
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from deepscout.config import get_settings
from deepscout.tools.web_search import web_search


@dataclass
class ToolRegistry:
    """按来源聚合工具，并在返回前做名称冲突检查。"""

    builtin_tools: list[BaseTool] = field(default_factory=lambda: [web_search])

    async def get_tools(self) -> list[BaseTool]:
        tools = list(self.builtin_tools)
        settings = get_settings()
        if settings.mcp_servers:
            client = MultiServerMCPClient(
                settings.mcp_servers,
                tool_name_prefix=settings.mcp_tool_name_prefix,
            )
            tools.extend(await client.get_tools())
        self._validate_unique_names(tools)
        return tools

    @staticmethod
    def _validate_unique_names(tools: list[BaseTool]) -> None:
        names = [tool.name for tool in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"工具名称冲突: {duplicates}")


def registry_fingerprint() -> str:
    """用于 Research Agent 缓存失效。"""
    settings = get_settings()
    payload = {
        "mcp_servers": settings.mcp_servers,
        "mcp_tool_name_prefix": settings.mcp_tool_name_prefix,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


async def get_research_tools() -> list[BaseTool]:
    return await ToolRegistry().get_tools()
