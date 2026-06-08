"""Shared test fixtures and hermetic doubles for the unit tier.

Centralizes the ``Settings`` factory (so individual tests stop duplicating the
filler kwargs) and the two doubles the agent tests need:

* :class:`ScriptedModel` — a run-capable model that bypasses the provider
  pipeline and returns a canned response, so ``agent.run`` works with no network.
* :class:`FakeKnowledge` — a :class:`~agno.knowledge.protocol.KnowledgeProtocol`
  implementation that exposes no tools and connects to nothing.

Also provides :func:`settings_or_skip`, the one skip-or-load helper the
``integration`` tier shares. Anything that touches real infrastructure (Postgres,
the live providers) lives in that tier.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest
from agno.knowledge.document import Document
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from pydantic import SecretStr, ValidationError

from spectres_runtime.config import Settings, get_settings
from spectres_runtime.recipe_agent.config import RecipeAgentSettings

SCRIPTED_RESPONSE = "scripted-response"


def settings_or_skip() -> Settings:
    """Load ``Settings`` for an integration test, or skip if config is incomplete.

    ``get_settings`` reads the process env and a local ``.env``; a missing required
    field (no DB URL / API key) raises ``ValidationError``, turned into a skip so the
    opt-in integration tier is a no-op without credentials.
    """
    try:
        return get_settings()
    except ValidationError:
        pytest.skip("Runtime config incomplete (no DB/key via env / .env) — integration check skipped.")


def make_settings(**overrides: Any) -> Settings:
    """Build a fully-populated ``Settings`` double (no env / ``.env`` read).

    Supplies every required field with inert test values; ``overrides`` replace
    individual fields for tests that care about a specific one. The nested
    ``recipe_agent`` can be overridden wholesale by passing a
    ``RecipeAgentSettings`` (or a dict of its fields).
    """
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime",
        "embedder_model": "Qwen/Qwen3-Embedding-0.6B",
        "embedder_base_url": "https://api.siliconflow.cn/v1",
        "embedder_dimensions": 1024,
        "embedder_api_key": SecretStr("sk-secret"),
        "chat_model": "kimi-for-coding",
        "chat_base_url": "https://api.kimi.com/coding/v1",
        "chat_api_key": SecretStr("sk-chat-secret"),
        "recipe_agent": RecipeAgentSettings(
            _env_file=None,
            instructions="Test instructions.",
            num_history_runs=5,
        ),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class ScriptedModel(Model):
    """A run-capable model double that never touches a provider.

    Overrides the high-level ``response`` / ``aresponse`` entry points to return a
    canned assistant message, bypassing the provider invoke + parse pipeline. The
    low-level abstract methods are stubbed and never reached on this path.
    """

    def response(
        self,
        messages: list[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        tool_call_limit: Any = None,
        run_response: Any = None,
        send_media_to_model: bool = True,
        compression_manager: Any = None,
    ) -> ModelResponse:
        return ModelResponse(role="assistant", content=SCRIPTED_RESPONSE)

    async def aresponse(
        self,
        messages: list[Message],
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        tool_call_limit: Any = None,
        run_response: Any = None,
        send_media_to_model: bool = True,
        compression_manager: Any = None,
    ) -> ModelResponse:
        return ModelResponse(role="assistant", content=SCRIPTED_RESPONSE)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise NotImplementedError

    def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


class FakeKnowledge:
    """A ``KnowledgeProtocol`` double: satisfies the agent's wiring, connects to nothing."""

    def build_context(self, **kwargs: Any) -> str:
        return ""

    def get_tools(self, **kwargs: Any) -> list[Callable[..., Any]]:
        return []

    async def aget_tools(self, **kwargs: Any) -> list[Callable[..., Any]]:
        return []

    def retrieve(self, query: str, **kwargs: Any) -> list[Document]:
        return []

    async def aretrieve(self, query: str, **kwargs: Any) -> list[Document]:
        return []


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def scripted_model() -> ScriptedModel:
    return ScriptedModel(id="scripted", name="Scripted", provider="scripted")


@pytest.fixture
def fake_knowledge() -> FakeKnowledge:
    return FakeKnowledge()
