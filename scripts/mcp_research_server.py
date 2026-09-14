"""Small real MCP server for DeepScout integration and deployment smoke tests."""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP


def build_server(*, host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    mcp = FastMCP(
        "deepscout-research-utils",
        instructions="Deterministic research utility tools for DeepScout MCP tests.",
        host=host,
        port=port,
    )

    @mcp.tool()
    def word_count(text: str) -> dict[str, int]:
        """Count whitespace-separated words and characters in research text."""
        return {"words": len(text.split()), "characters": len(text)}

    @mcp.tool()
    def extract_domain(url: str) -> str:
        """Extract and normalize the hostname from an HTTP(S) source URL."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an absolute HTTP(S) URL")
        return parsed.hostname.lower().removeprefix("www.")

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DeepScout MCP utility server.")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    build_server(host=args.host, port=args.port).run(transport=args.transport)


if __name__ == "__main__":
    main()
