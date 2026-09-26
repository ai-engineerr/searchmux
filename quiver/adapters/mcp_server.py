"""MCP stdio server exposing Quiver's search as a single tool.

Uses the official `mcp` Python SDK (`mcp.server.mcpserver.MCPServer`,
the successor to `FastMCP` as of mcp>=2). Requires the optional `mcp`
dependency; install it with `pip install mcp`.
"""

import logging
import os
from dataclasses import asdict

from mcp.server.mcpserver import MCPServer

from quiver.client import Quiver
from quiver.constants import ENV_API_KEY

logger = logging.getLogger(__name__)

SERVER_NAME = "quiver"

server = MCPServer(SERVER_NAME)
_quiver: Quiver | None = None


def _client() -> Quiver:
    """Return the module-level Quiver, building it on first use.

    Returns:
        A Quiver client backed by the SERPAPI_API_KEY environment
        variable.
    """
    global _quiver
    if _quiver is None:
        _quiver = Quiver(api_key=os.getenv(ENV_API_KEY))
    return _quiver


@server.tool()
def find(intent: str) -> list[dict]:
    """Search the live web for the given intent.

    Args:
        intent: What the caller wants to know, in plain language.

    Returns:
        Normalized search results as plain dicts.
    """
    results = _client().find(intent)
    return [asdict(result) for result in results]


def main() -> None:
    """Run the Quiver MCP server over stdio.

    This is the `quiver-mcp` console script entry point.
    """
    logger.info("starting %s MCP server on stdio", SERVER_NAME)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
