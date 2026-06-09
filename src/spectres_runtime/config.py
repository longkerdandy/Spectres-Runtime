"""Runtime configuration loaded from the environment. See `.env.example` for the
documented keys, their recommended values, and rationale."""

from __future__ import annotations

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAILike
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from spectres_runtime.recipe_agent.config import RecipeAgentSettings


class Settings(BaseSettings):
    """Typed, env-driven runtime config. No defaults — every value comes from the
    process env or a git-ignored `.env` (documented in `.env.example`).

    Holds only *shared* infrastructure config (database, embedder, chat). Each
    agent's private config lives in its own module (e.g.
    :class:`~spectres_runtime.recipe_agent.config.RecipeAgentSettings`) and is
    composed in as a nested field by :func:`get_settings`, so adding an agent
    never touches this class.
    """

    # Read `.env` after the process env; ignore unrelated vars instead of erroring.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str  # Postgres + pgvector connection URL.
    embedder_model: str  # Embedding model id (a data contract — changing it means a full re-embed).
    embedder_base_url: str  # Embedding provider base URL (any OpenAI-compatible endpoint).
    embedder_dimensions: int  # Embedding vector size.
    embedder_api_key: SecretStr  # Secret — only ever set in the local `.env`, never committed.

    chat_model: str  # Chat model id from the configured provider. Not a data contract — can change run-to-run.
    chat_base_url: str  # Chat provider base URL (OpenAI-compatible endpoint).
    chat_api_key: SecretStr  # Secret — a separate key/provider from the embedder; only in the local `.env`.

    recipe_agent: RecipeAgentSettings  # Recipe-agent-private config (see its own module); composed by `get_settings`.

    def build_embedder(self) -> OpenAIEmbedder:
        """Build the hosted embedder, shared by ingest and search to stay in one vector space."""
        return OpenAIEmbedder(
            id=self.embedder_model,
            dimensions=self.embedder_dimensions,
            base_url=self.embedder_base_url,
            api_key=self.embedder_api_key.get_secret_value(),
        )

    def build_chat_model(self) -> OpenAILike:
        """Build the hosted chat model. Text-only (no embeddings) — distinct from the embedder.

        Uses Agno's generic OpenAI-compatible client; the actual provider is driven
        entirely by config (base_url + api_key + model id) so swapping providers is
        a config change, never a code change.
        """
        return OpenAILike(
            id=self.chat_model,
            base_url=self.chat_base_url,
            api_key=self.chat_api_key.get_secret_value(),
        )


def get_settings() -> Settings:
    """Build Settings from the current environment / `.env`.

    Each agent's nested config is constructed explicitly (rather than via a model
    default) so the hermetic `_env_file=None` guarantee stays under the caller's
    control in tests.
    """
    return Settings(recipe_agent=RecipeAgentSettings())
