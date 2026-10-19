"""Built-in tool registrations for Spectres Runtime."""

from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools
from agno.tools.tavily import TavilyTools
from agno.tools.toolkit import Toolkit
from agno.tools.website import WebsiteTools

from spectres.config import settings


def get_builtin_tools() -> list[Toolkit]:
    """Return the list of built-in tools available to agents.

    Tavily web search is registered only when TAVILY_API_KEY is configured;
    without a key the Runtime still starts, just without web search.

    Returns:
        List containing CalculatorTools, ShellTools, WebsiteTools, and
        (when configured) TavilyTools instances.
    """
    tools: list[Toolkit] = [
        CalculatorTools(),  # type: ignore[no-untyped-call]
        ShellTools(),
        WebsiteTools(),
    ]
    if settings.tavily_api_key:
        # search_depth="basic" costs 1 credit per search (Agno's default
        # "advanced" costs 2, halving the free tier).
        tools.append(TavilyTools(api_key=settings.tavily_api_key, search_depth="basic"))
    return tools
