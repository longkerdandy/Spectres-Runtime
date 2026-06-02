"""Runtime configuration loaded from the environment. See `.env.example` for the
documented keys, their recommended values, and rationale."""

from __future__ import annotations

from agno.knowledge.embedder.openai import OpenAIEmbedder
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

    def build_embedder(self) -> OpenAIEmbedder:
        """Construct the configured hosted embedder, shared by ingest and search so
        both sides stay in one vector space."""
        return OpenAIEmbedder(
            id=self.embedder_model,
            dimensions=self.embedder_dimensions,
            base_url=self.embedder_base_url,
            api_key=self.embedder_api_key.get_secret_value(),
        )


def get_settings() -> Settings:
    """Build Settings from the current environment / `.env`."""
    return Settings()
