"""Unit tests for Spectres Runtime tool registrations."""

from typing import Literal

import pytest
from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools
from agno.tools.tavily import TavilyTools
from agno.tools.toolkit import Toolkit
from agno.tools.website import WebsiteTools

from spectres.config import settings
from spectres.tools.builtin import get_builtin_tools
from spectres.tools.kimi_web_search import KimiWebSearchTools

pytestmark = pytest.mark.unit


def _set_search_config(
    monkeypatch: pytest.MonkeyPatch,
    backend: Literal["kimi", "tavily"],
    kimi: str | None,
    tavily: str | None,
) -> None:
    """Select a search backend and its credentials for one test."""
    monkeypatch.setattr(settings, "web_search_backend", backend)
    monkeypatch.setattr(settings, "kimi_web_search_api_key", kimi)
    monkeypatch.setattr(settings, "tavily_api_key", tavily)


def _assert_standard_tools(tools: list[Toolkit]) -> None:
    """Assert the always-on calculator, shell, and website tools are present."""
    assert any(isinstance(tool, CalculatorTools) for tool in tools)
    assert any(isinstance(tool, ShellTools) for tool in tools)
    website = next(tool for tool in tools if isinstance(tool, WebsiteTools))
    assert "read_url" in website.get_functions()


@pytest.mark.parametrize(
    ("backend", "kimi", "tavily"),
    [
        ("kimi", None, None),
        ("kimi", None, "tavily-key"),
        ("tavily", "kimi-key", None),
    ],
)
def test_get_builtin_tools_without_selected_backend_key(
    monkeypatch: pytest.MonkeyPatch,
    backend: Literal["kimi", "tavily"],
    kimi: str | None,
    tavily: str | None,
) -> None:
    """Without a credential for the selected backend, search is omitted with no fallback."""
    _set_search_config(monkeypatch, backend=backend, kimi=kimi, tavily=tavily)

    tools = get_builtin_tools()

    assert len(tools) == 3
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, (KimiWebSearchTools, TavilyTools)) for tool in tools)


def test_get_builtin_tools_with_selected_tavily(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting Tavily registers only its basic-depth search even when Kimi is configured."""
    _set_search_config(monkeypatch, backend="tavily", kimi="kimi-key", tavily="test-key")

    tools = get_builtin_tools()

    assert len(tools) == 4
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, KimiWebSearchTools) for tool in tools)
    tavily = next(tool for tool in tools if isinstance(tool, TavilyTools))
    assert tavily.search_depth == "basic"
    assert list(tavily.get_functions()) == ["web_search_using_tavily"]


def test_get_builtin_tools_with_selected_kimi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting Kimi exposes one search function at the configured endpoint even when Tavily is configured."""
    _set_search_config(monkeypatch, backend="kimi", kimi="kimi-key", tavily="tavily-key")
    monkeypatch.setattr(settings, "kimi_web_search_base_url", "https://kimi.example.com/search")

    tools = get_builtin_tools()

    assert len(tools) == 4
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, TavilyTools) for tool in tools)
    kimi = next(tool for tool in tools if isinstance(tool, KimiWebSearchTools))
    assert kimi.base_url == "https://kimi.example.com/search"
    assert list(kimi.get_functions()) == ["web_search_using_kimi"]
    assert list(kimi.get_async_functions()) == ["web_search_using_kimi"]
