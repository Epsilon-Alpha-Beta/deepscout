from types import SimpleNamespace

import pytest
from langchain_core.tools import tool

from deepscout.graph.builder import build_graph
from deepscout.runtime.checkpoint import memory_checkpointer
from deepscout.runtime.retry import llm_retry_policy
from deepscout.tools import registry as registry_module
from deepscout.tools.registry import ToolRegistry


@tool
def fake_mcp_tool(query: str) -> str:
    """Fake MCP tool used by registry tests."""
    return query


@pytest.mark.asyncio
async def test_registry_returns_builtin_tool_without_mcp(monkeypatch):
    monkeypatch.setattr(
        registry_module,
        "get_settings",
        lambda: SimpleNamespace(mcp_servers={}, mcp_tool_name_prefix=True),
    )
    tools = await ToolRegistry().get_tools()
    assert [item.name for item in tools] == ["web_search"]


@pytest.mark.asyncio
async def test_registry_loads_mcp_tools(monkeypatch):
    class FakeClient:
        def __init__(self, connections, *, tool_name_prefix, **kwargs):
            assert connections == {"docs": {"transport": "streamable_http", "url": "x"}}
            assert tool_name_prefix is True

        async def get_tools(self):
            return [fake_mcp_tool]

    monkeypatch.setattr(registry_module, "MultiServerMCPClient", FakeClient)
    monkeypatch.setattr(
        registry_module,
        "get_settings",
        lambda: SimpleNamespace(
            mcp_servers={"docs": {"transport": "streamable_http", "url": "x"}},
            mcp_tool_name_prefix=True,
        ),
    )
    tools = await ToolRegistry().get_tools()
    assert [item.name for item in tools] == ["web_search", "fake_mcp_tool"]


def test_registry_rejects_duplicate_tool_names():
    with pytest.raises(ValueError, match="工具名称冲突"):
        ToolRegistry._validate_unique_names([fake_mcp_tool, fake_mcp_tool])


def test_graph_accepts_memory_checkpointer():
    saver = memory_checkpointer()
    compiled = build_graph(checkpointer=saver)
    assert compiled.checkpointer is saver


def test_default_retry_policy_matches_config():
    policy = llm_retry_policy()
    assert policy.max_attempts == 3
    assert policy.initial_interval == 0.5
    assert policy.max_interval == 8.0
