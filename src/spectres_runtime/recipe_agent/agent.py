"""Recipe agent construction.

A thin construction entry point that *names* the agent's composition without
wiring its parts. The returned :class:`~agno.agent.Agent` carries only what
AgentOS needs to register and surface it — an ``id``, a ``name``, and a model.
``knowledge``, ``db``, ``tools``, ``dependencies``, and ``instructions`` are
intentionally left unwired.

The model is a :class:`_PlaceholderModel`: AgentOS requires every registered
agent to carry a constructed model (it otherwise injects a default that pulls a
provider SDK), but this agent never invokes one. The placeholder satisfies
construction while keeping the import path free of any LLM SDK, network, or
credentials — its invocation methods raise :class:`NotImplementedError`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any, Final

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse

RECIPE_AGENT_ID: Final[str] = "recipe"
RECIPE_AGENT_NAME: Final[str] = "Recipe Agent"


class _PlaceholderModel(Model):
    """A non-functional :class:`~agno.models.base.Model`.

    Constructs without any provider SDK so an agent can be registered into
    AgentOS, but is never invoked. Every provider call raises
    :class:`NotImplementedError`.
    """

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError("Recipe agent model is not wired.")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError("Recipe agent model is not wired.")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise NotImplementedError("Recipe agent model is not wired.")

    def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError("Recipe agent model is not wired.")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError("Recipe agent model is not wired.")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError("Recipe agent model is not wired.")


def build_recipe_agent() -> Agent:
    """Construct the placeholder recipe agent.

    The single construction entry point that AgentOS registers. It establishes
    *where* ``model``, ``knowledge``, ``db``, ``tools``, and ``instructions``
    will attach without wiring any of them. The agent answers no user journeys
    yet — it exists so the app boots with it registered.
    """
    return Agent(
        id=RECIPE_AGENT_ID,
        name=RECIPE_AGENT_NAME,
        model=_PlaceholderModel(
            id="placeholder",
            name="Spectres Placeholder",
            provider="spectres-placeholder",
        ),
    )
