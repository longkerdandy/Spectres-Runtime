"""Typed configuration for Spectres Runtime."""

import json
import os
from typing import Any, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("SPECTRES_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5532, alias="DB_PORT")
    db_user: str = Field(default="ai", alias="DB_USER")
    db_pass: str = Field(default="ai", alias="DB_PASS")
    db_database: str = Field(default="ai", alias="DB_DATABASE")

    # AgentOS server
    agent_os_host: str = Field(default="localhost", alias="AGENT_OS_HOST")
    agent_os_port: int = Field(default=7777, alias="AGENT_OS_PORT")

    # Team Leader Agent (OpenAI-compatible API for open-source / self-hosted LLMs)
    team_leader_llm_model: str = Field(default="gpt-4o", alias="TEAM_LEADER_LLM_MODEL")
    team_leader_llm_api_key: str | None = Field(default=None, alias="TEAM_LEADER_LLM_API_KEY")
    team_leader_llm_base_url: str | None = Field(default=None, alias="TEAM_LEADER_LLM_BASE_URL")
    team_leader_llm_temperature: float | None = Field(default=None, alias="TEAM_LEADER_LLM_TEMPERATURE")
    team_leader_llm_max_completion_tokens: int | None = Field(
        default=None, alias="TEAM_LEADER_LLM_MAX_COMPLETION_TOKENS"
    )
    team_leader_llm_extra_headers: dict[str, str] | None = Field(default=None, alias="TEAM_LEADER_LLM_EXTRA_HEADERS")

    @field_validator("team_leader_llm_extra_headers", mode="before")
    @classmethod
    def _parse_extra_headers(cls, value: Any) -> dict[str, str] | None:
        """Parse the extra headers value from a JSON string or dict."""
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return cast(dict[str, str], json.loads(value))
        raise ValueError("TEAM_LEADER_LLM_EXTRA_HEADERS must be a JSON object mapping header names to values")

    @property
    def database_url(self) -> str:
        """Return the PostgreSQL connection URL."""
        return f"postgresql+psycopg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_database}"


settings = Settings()
