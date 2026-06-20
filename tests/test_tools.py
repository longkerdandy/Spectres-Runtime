"""Unit tests for Spectres Runtime tool registrations."""

from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools

from spectres.tools.builtin import get_builtin_tools


def test_get_builtin_tools_returns_expected_tools() -> None:
    """Built-in tools include calculator and shell tools."""
    tools = get_builtin_tools()
    assert any(isinstance(tool, CalculatorTools) for tool in tools)
    assert any(isinstance(tool, ShellTools) for tool in tools)


def test_get_builtin_tools_returns_two_tools() -> None:
    """The built-in tool registry contains exactly two tools."""
    tools = get_builtin_tools()
    assert len(tools) == 2
