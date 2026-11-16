"""Built-in tool registrations for Spectres Runtime."""

from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools
from agno.tools.tavily import TavilyTools
from agno.tools.toolkit import Toolkit
from agno.tools.website import WebsiteTools

from spectres.config import settings
from spectres.tools.kimi_web_search import KimiWebSearchTools


def get_builtin_tools() -> list[Toolkit]:
    """Return the built-in tools for the explicitly selected search backend.

    Returns:
        Calculator, Shell, Website, and at most one configured web-search Toolkit.
    """
    tools: list[Toolkit] = [
        CalculatorTools(),  # type: ignore[no-untyped-call]
        ShellTools(),
        WebsiteTools(),
    ]
    if settings.web_search_backend == "kimi" and settings.kimi_web_search_api_key:
        tools.append(
            KimiWebSearchTools(
                api_key=settings.kimi_web_search_api_key,
                base_url=settings.kimi_web_search_base_url,
            )
        )
    elif settings.web_search_backend == "tavily" and settings.tavily_api_key:
        # search_depth="basic" costs 1 credit per search (Agno's default
        # "advanced" costs 2, halving the free tier).
        tools.append(TavilyTools(api_key=settings.tavily_api_key, search_depth="basic"))
    return tools
