"""Built-in tool registrations for Spectres Runtime."""

from typing import Any

from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools


def get_builtin_tools() -> list[Any]:
    """Return the list of built-in tools available to agents.

    Returns:
        List containing CalculatorTools and ShellTools instances.
    """
    return [
        CalculatorTools(),  # type: ignore[no-untyped-call]
        ShellTools(),
    ]
