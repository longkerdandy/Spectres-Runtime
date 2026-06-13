"""Recipe-agent-specific configuration.

Co-located with the agent it configures so the ``recipe_agent`` package stays
self-contained: its config *schema* lives next to its construction logic, not in
the top-level :mod:`spectres_runtime.config`. Shared infrastructure config
(database, embedder, chat) remains in the root ``Settings``.

Reads the same single ``.env`` as the root settings; the ``RECIPE_AGENT_``
``env_prefix`` keeps the existing variable names unchanged
(``RECIPE_AGENT_INSTRUCTIONS`` -> ``instructions``,
``RECIPE_AGENT_NUM_HISTORY_RUNS`` -> ``num_history_runs``).
"""

from __future__ import annotations

import json
from typing import Any

from agno.models.openai import OpenAILike
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RecipeAgentSettings(BaseSettings):
    """Typed, env-driven config private to the recipe agent.

    No defaults for the original required values — every value comes from the
    process env or a git-ignored ``.env`` (documented in ``.env.example``).
    Optional chat-model parameters are added so deployments can tune behaviour
    without changing code.
    """

    # Same `.env` as the root settings; the prefix maps `RECIPE_AGENT_<FIELD>`.
    model_config = SettingsConfigDict(
        env_prefix="RECIPE_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    instructions: str = ""  # Recipe agent system instructions; empty uses the built-in default.
    num_history_runs: int  # Prior conversation turns replayed into the agent's context.
    chat_model: str  # Chat model id from the configured provider. Not a data contract.
    chat_base_url: str  # Chat provider base URL (OpenAI-compatible endpoint).
    chat_api_key: SecretStr  # Secret — only ever set in the local `.env`, never committed.

    # Optional OpenAI-compatible chat-model parameters. All are passed through to
    # Agno's `OpenAILike` only when explicitly set, so provider defaults are kept
    # when these are omitted.
    chat_temperature: float | None = None  # Sampling temperature (0.0-2.0).
    chat_top_p: float | None = None  # Nucleus sampling probability (0.0-1.0).
    chat_max_tokens: int | None = None  # Max answer tokens (legacy name).
    chat_max_completion_tokens: int | None = None  # Max total output tokens (answer + reasoning).
    chat_frequency_penalty: float | None = None  # Penalty for repeated tokens (-2.0-2.0).
    chat_presence_penalty: float | None = None  # Penalty for repeated topics (-2.0-2.0).
    chat_timeout: float | None = None  # HTTP request timeout in seconds.
    chat_seed: int | None = None  # Seed for deterministic/reproducible output.
    chat_thinking: str | None = None  # Provider thinking mode: enabled / disabled / auto.
    chat_reasoning_effort: str | None = None  # Reasoning effort: minimal / low / medium / high.
    chat_request_params: dict[str, Any] | None = None  # Escape hatch for provider-specific params.

    @field_validator("chat_request_params", mode="before")
    @classmethod
    def _parse_chat_request_params(cls, value: Any) -> dict[str, Any] | None:
        """Allow the env var to be a JSON string or an already-parsed dict."""
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed: dict[str, Any] = json.loads(value)
            return parsed
        raise ValueError("chat_request_params must be a JSON object string or a dict")

    def build_chat_model(self) -> OpenAILike:
        """Build the hosted chat model. Text-only (no embeddings).

        Uses Agno's generic OpenAI-compatible client; the actual provider is driven
        entirely by config so swapping providers is a `.env` change, never a code change.
        """
        params: dict[str, Any] = {}

        if self.chat_temperature is not None:
            params["temperature"] = self.chat_temperature
        if self.chat_top_p is not None:
            params["top_p"] = self.chat_top_p
        if self.chat_max_tokens is not None:
            params["max_tokens"] = self.chat_max_tokens
        if self.chat_max_completion_tokens is not None:
            params["max_completion_tokens"] = self.chat_max_completion_tokens
        if self.chat_frequency_penalty is not None:
            params["frequency_penalty"] = self.chat_frequency_penalty
        if self.chat_presence_penalty is not None:
            params["presence_penalty"] = self.chat_presence_penalty
        if self.chat_timeout is not None:
            params["timeout"] = self.chat_timeout
        if self.chat_seed is not None:
            params["seed"] = self.chat_seed
        if self.chat_reasoning_effort is not None:
            params["reasoning_effort"] = self.chat_reasoning_effort

        # Provider-specific parameters (e.g. Volcengine's `thinking`) are not
        # accepted directly by Agno's ``OpenAILike`` constructor; pass them
        # through ``request_params`` so they reach the underlying API call.
        request_params: dict[str, Any] = dict(self.chat_request_params or {})
        if self.chat_thinking is not None:
            request_params["thinking"] = {"type": self.chat_thinking}
        if request_params:
            params["request_params"] = request_params

        return OpenAILike(
            id=self.chat_model,
            base_url=self.chat_base_url,
            api_key=self.chat_api_key.get_secret_value(),
            **params,
        )
