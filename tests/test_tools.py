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


def _set_search_config(
    monkeypatch: pytest.MonkeyPatch,
    backend: Literal["kimi", "tavily"],
    kimi: str | None,
    tavily: str | None,
) -> None:
    monkeypatch.setattr(settings, "web_search_backend", backend)
    monkeypatch.setattr(settings, "kimi_web_search_api_key", kimi)
    monkeypatch.setattr(settings, "tavily_api_key", tavily)


def _assert_standard_tools(tools: list[Toolkit]) -> None:
    assert any(isinstance(tool, CalculatorTools) for tool in tools)
    assert any(isinstance(tool, ShellTools) for tool in tools)
    website = next(tool for tool in tools if isinstance(tool, WebsiteTools))
    assert "read_url" in website.get_functions()


def test_get_builtin_tools_without_search_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a credential for the selected backend, built-in tools exclude search."""
    _set_search_config(monkeypatch, backend="kimi", kimi=None, tavily=None)

    tools = get_builtin_tools()

    assert len(tools) == 3
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, (KimiWebSearchTools, TavilyTools)) for tool in tools)


def test_get_builtin_tools_with_selected_tavily(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting Tavily registers its existing search function at basic depth."""
    _set_search_config(monkeypatch, backend="tavily", kimi=None, tavily="test-key")

    tools = get_builtin_tools()

    assert len(tools) == 4
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, KimiWebSearchTools) for tool in tools)
    tavily = next(tool for tool in tools if isinstance(tool, TavilyTools))
    assert tavily.search_depth == "basic"
    assert list(tavily.get_functions()) == ["web_search_using_tavily"]


def test_get_builtin_tools_with_selected_kimi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting Kimi exposes one search function and uses the configured endpoint."""
    _set_search_config(monkeypatch, backend="kimi", kimi="kimi-key", tavily=None)
    monkeypatch.setattr(settings, "kimi_web_search_base_url", "https://kimi.example.com/search")

    tools = get_builtin_tools()

    assert len(tools) == 4
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, TavilyTools) for tool in tools)
    kimi = next(tool for tool in tools if isinstance(tool, KimiWebSearchTools))
    assert kimi.base_url == "https://kimi.example.com/search"
    assert list(kimi.get_functions()) == ["web_search_using_kimi"]
    assert list(kimi.get_async_functions()) == ["web_search_using_kimi"]


@pytest.mark.parametrize(
    ("backend", "expected_type", "unexpected_type"),
    [
        ("kimi", KimiWebSearchTools, TavilyTools),
        ("tavily", TavilyTools, KimiWebSearchTools),
    ],
)
def test_get_builtin_tools_uses_selection_when_both_keys_exist(
    monkeypatch: pytest.MonkeyPatch,
    backend: Literal["kimi", "tavily"],
    expected_type: type[Toolkit],
    unexpected_type: type[Toolkit],
) -> None:
    """The selector chooses exactly one backend even when both credentials exist."""
    _set_search_config(monkeypatch, backend=backend, kimi="kimi-key", tavily="tavily-key")

    tools = get_builtin_tools()

    assert len(tools) == 4
    _assert_standard_tools(tools)
    search_tools = [tool for tool in tools if isinstance(tool, (KimiWebSearchTools, TavilyTools))]
    assert len(search_tools) == 1
    assert isinstance(search_tools[0], expected_type)
    assert not isinstance(search_tools[0], unexpected_type)


@pytest.mark.parametrize("backend", ["kimi", "tavily"])
def test_get_builtin_tools_does_not_fallback_to_unselected_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: Literal["kimi", "tavily"],
) -> None:
    """A credential for the unselected backend does not enable its search tool."""
    _set_search_config(
        monkeypatch,
        backend=backend,
        kimi=None if backend == "kimi" else "kimi-key",
        tavily=None if backend == "tavily" else "tavily-key",
    )

    tools = get_builtin_tools()

    assert len(tools) == 3
    _assert_standard_tools(tools)
    assert not any(isinstance(tool, (KimiWebSearchTools, TavilyTools)) for tool in tools)
