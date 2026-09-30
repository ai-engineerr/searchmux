"""MCP stdio server exposing SearchMux's search as a single tool.

Uses the official `mcp` Python SDK (`mcp.server.mcpserver.MCPServer`,
the successor to `FastMCP` as of mcp>=2). Requires the optional `mcp`
dependency; install it with `pip install mcp`.
"""

import logging
import os
from dataclasses import asdict

from mcp.server.mcpserver import MCPServer

from searchmux.client import SearchMux
from searchmux.constants import (
    ENV_ANTHROPIC_KEY,
    ENV_API_KEY,
    ENV_BRAVE_KEY,
    ENV_EXA_KEY,
    ENV_TAVILY_KEY,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "searchmux"

server = MCPServer(SERVER_NAME)
_searchmux: SearchMux | None = None


def _client() -> SearchMux:
    """Return the module-level SearchMux, building it on first use.

    A router is attached when ANTHROPIC_API_KEY is present, restricted
    to whichever providers actually have a key configured — so it can
    never route to an engine this client has no key for. Without a
    router the `find` tool cannot resolve an engine from plain
    language, so it raises a RoutingError naming the missing variable
    rather than failing obscurely.

    Returns:
        A SearchMux client backed by whichever provider keys are set,
        with a router when routing is configured.
    """
    global _searchmux
    if _searchmux is None:
        _searchmux = SearchMux(
            api_key=os.getenv(ENV_API_KEY),
            tavily_api_key=os.getenv(ENV_TAVILY_KEY),
            brave_api_key=os.getenv(ENV_BRAVE_KEY),
            exa_api_key=os.getenv(ENV_EXA_KEY),
            router=_router(),
        )
    return _searchmux


def _configured_providers() -> set[str]:
    """Return provider names whose API key is set in the environment."""
    pairs = {
        "serpapi": ENV_API_KEY,
        "tavily": ENV_TAVILY_KEY,
        "brave": ENV_BRAVE_KEY,
        "exa": ENV_EXA_KEY,
    }
    return {name for name, env_name in pairs.items() if os.getenv(env_name)}


def _router() -> object | None:
    """Return an intent router, or None when it cannot be built.

    Returns:
        A Router when ANTHROPIC_API_KEY is set, else None.
    """
    if not os.getenv(ENV_ANTHROPIC_KEY):
        logger.warning(
            "%s is unset; the find tool will not be able to route",
            ENV_ANTHROPIC_KEY,
        )
        return None
    from searchmux.router import Router

    return Router(providers=_configured_providers())


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
    """Run the SearchMux MCP server over stdio.

    This is the `searchmux-mcp` console script entry point.
    """
    logger.info("starting %s MCP server on stdio", SERVER_NAME)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
