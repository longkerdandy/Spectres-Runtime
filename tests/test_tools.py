"""Unit tests for Spectres Runtime tool registrations."""

import pytest
from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools
from agno.tools.tavily import TavilyTools
from agno.tools.website import WebsiteTools

from spectres.config import settings
from spectres.tools.builtin import get_builtin_tools


def test_get_builtin_tools_without_tavily_key() -> None:
    """Without TAVILY_API_KEY, built-in tools exclude web search."""
    tools = get_builtin_tools()
    assert len(tools) == 3
    assert any(isinstance(tool, CalculatorTools) for tool in tools)
    assert any(isinstance(tool, ShellTools) for tool in tools)
    assert any(isinstance(tool, WebsiteTools) for tool in tools)
    assert not any(isinstance(tool, TavilyTools) for tool in tools)


def test_get_builtin_tools_with_tavily_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """With TAVILY_API_KEY set, Tavily web search is registered at basic depth."""
    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    tools = get_builtin_tools()
    assert len(tools) == 4
    tavily = next(tool for tool in tools if isinstance(tool, TavilyTools))
    assert tavily.search_depth == "basic"
