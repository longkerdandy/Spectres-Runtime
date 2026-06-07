"""Runtime configuration loaded from the environment. See `.env.example` for the
documented keys, their recommended values, and rationale."""

from __future__ import annotations

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.moonshot import MoonShot
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, env-driven runtime config. No defaults — every value comes from the
    process env or a git-ignored `.env` (documented in `.env.example`)."""

    # Read `.env` after the process env; ignore unrelated vars instead of erroring.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str  # Postgres + pgvector connection URL.
    embedder_model: str  # Embedding model id (a data contract — changing it means a full re-embed).
    embedder_base_url: str  # Embedding provider base URL (any OpenAI-compatible endpoint).
    embedder_dimensions: int  # Embedding vector size.
    embedder_api_key: SecretStr  # Secret — only ever set in the local `.env`, never committed.

    chat_model: str  # Chat model id (e.g. "kimi-for-coding"). Generation quality/cost only, not a data contract.
    chat_base_url: str  # Chat provider base URL (Kimi Code endpoint or Moonshot open platform).
    chat_api_key: SecretStr  # Secret — a separate key/provider from the embedder; only in the local `.env`.

    recipe_agent_instructions: str  # Recipe agent system instructions (env-driven now; UI-managed later).
    recipe_agent_num_history_runs: int  # Prior conversation turns replayed into the agent's context.

    def build_embedder(self) -> OpenAIEmbedder:
        """Build the hosted embedder, shared by ingest and search to stay in one vector space."""
        return OpenAIEmbedder(
            id=self.embedder_model,
            dimensions=self.embedder_dimensions,
            base_url=self.embedder_base_url,
            api_key=self.embedder_api_key.get_secret_value(),
        )

    def build_chat_model(self) -> MoonShot:
        """Build the hosted chat model. Text-only (no embeddings) — distinct from the embedder.

        Provider-agnostic: id/base_url/key come from config, so swapping providers is a config change.
        """
        return MoonShot(
            id=self.chat_model,  # provider-agnostic model id
            base_url=self.chat_base_url,  # OpenAI-compatible endpoint
            api_key=self.chat_api_key.get_secret_value(),  # unwrapped for the client
        )


def get_settings() -> Settings:
    """Build Settings from the current environment / `.env`."""
    return Settings()
