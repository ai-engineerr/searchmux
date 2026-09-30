"""Tests for the MCP server's provider-key detection.

mcp is an optional dependency ([mcp] extra, not in requirements.txt),
but importing this module still requires it -- mcp_server.py builds
an MCPServer instance at import time. Skip rather than error when
it's not installed, the same way the CI environment doesn't have it.
"""

import pytest

pytest.importorskip("mcp")

from searchmux.adapters.mcp_server import _configured_providers  # noqa: E402


def test_configured_providers_reads_all_four_keys(monkeypatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    assert _configured_providers() == {"serpapi"}


def test_configured_providers_empty_when_nothing_is_set(monkeypatch) -> None:
    for var in (
        "SERPAPI_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "EXA_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    assert _configured_providers() == set()
