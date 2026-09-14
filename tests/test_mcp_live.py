import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient


@pytest.mark.asyncio
async def test_real_stdio_mcp_server_discovers_and_invokes_tools():
    script = Path("scripts/mcp_research_server.py").resolve()
    client = MultiServerMCPClient(
        {
            "local": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(script)],
            }
        },
        tool_name_prefix=True,
    )
    tools = await client.get_tools()
    names = {tool.name for tool in tools}
    assert {"local_word_count", "local_extract_domain"}.issubset(names)

    word_count = next(tool for tool in tools if tool.name == "local_word_count")
    result = await word_count.ainvoke({"text": "deep research agent"})
    payload = json.loads(result[0]["text"])
    assert payload == {"words": 3, "characters": 19}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"MCP HTTP server did not start on port {port}")


@pytest.mark.asyncio
async def test_real_streamable_http_mcp_server_discovers_and_invokes_tools():
    script = Path("scripts/mcp_research_server.py").resolve()
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        client = MultiServerMCPClient(
            {
                "http": {
                    "transport": "streamable_http",
                    "url": f"http://127.0.0.1:{port}/mcp",
                }
            },
            tool_name_prefix=True,
        )
        tools = await client.get_tools()
        names = {tool.name for tool in tools}
        assert {"http_word_count", "http_extract_domain"}.issubset(names)
        extract = next(tool for tool in tools if tool.name == "http_extract_domain")
        result = await extract.ainvoke({"url": "https://www.example.com/path"})
        assert result[0]["text"] == "example.com"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
