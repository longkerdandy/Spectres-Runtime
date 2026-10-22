"""Typed configuration for Spectres Runtime."""

import json
import os
from typing import Any, Literal, cast

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=os.getenv("SPECTRES_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Database
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(alias="DB_PORT")
    db_user: str = Field(alias="DB_USER")
    db_pass: str = Field(alias="DB_PASS")
    db_database: str = Field(alias="DB_DATABASE")

    # AgentOS server
    agent_os_host: str = Field(alias="AGENT_OS_HOST")
    agent_os_port: int = Field(alias="AGENT_OS_PORT")

    # Team Leader Agent (OpenAI-compatible API for open-source / self-hosted LLMs)
    team_leader_llm_model: str = Field(alias="TEAM_LEADER_LLM_MODEL")
    team_leader_llm_api_key: str | None = Field(alias="TEAM_LEADER_LLM_API_KEY")
    team_leader_llm_base_url: str | None = Field(alias="TEAM_LEADER_LLM_BASE_URL")
    team_leader_llm_temperature: float | None = Field(alias="TEAM_LEADER_LLM_TEMPERATURE", default=None)
    team_leader_llm_max_completion_tokens: int | None = Field(alias="TEAM_LEADER_LLM_MAX_COMPLETION_TOKENS", default=None)
    team_leader_llm_extra_headers: dict[str, str] | None = Field(alias="TEAM_LEADER_LLM_EXTRA_HEADERS", default=None)

    # CORS
    cors_allowed_origins: list[str] | None = Field(alias="CORS_ALLOWED_ORIGINS", default=None)

    # Web search (Tavily API)
    tavily_api_key: str | None = Field(alias="TAVILY_API_KEY", default=None)

    # Logging (see spectres/logging.py)
    log_level: str = Field(alias="LOG_LEVEL")
    log_format: Literal["json", "text"] = Field(alias="LOG_FORMAT")
    log_dir: str = Field(alias="LOG_DIR")
    log_retention_days: int = Field(alias="LOG_RETENTION_DAYS")

    # Scheduler (Agno built-in AgentOS scheduler)
    scheduler_enabled: bool = Field(alias="SCHEDULER_ENABLED")
    scheduler_poll_interval: int = Field(alias="SCHEDULER_POLL_INTERVAL")
    scheduler_base_url: str = Field(alias="SCHEDULER_BASE_URL")

    # JWT authentication: enabled when key material is present (JWKS file for Logto, symmetric key for local dev); otherwise the app runs open
    jwt_verification_key: str | None = Field(alias="JWT_VERIFICATION_KEY", default=None)
    jwt_jwks_file: str | None = Field(alias="JWT_JWKS_FILE", default=None)
    jwt_audience: str | None = Field(alias="JWT_AUDIENCE", default=None)
    jwt_issuer: str | None = Field(alias="JWT_ISSUER", default=None)
    jwt_algorithm: str = Field(alias="JWT_ALGORITHM", default="ES384")

    @field_validator("jwt_audience", "jwt_issuer")
    @classmethod
    def _require_verification_material_with_audience(cls, value: str | None, info: ValidationInfo) -> str | None:
        """Forbid configuring an audience or issuer without any way to verify tokens."""
        if value and not info.data.get("jwt_verification_key") and not info.data.get("jwt_jwks_file"):
            raise ValueError("JWT_AUDIENCE/JWT_ISSUER is set but neither JWT_VERIFICATION_KEY nor JWT_JWKS_FILE is configured")
        return value

    @property
    def jwt_auth_enabled(self) -> bool:
        """Whether JWT authentication should be wired into AgentOS."""
        return bool(self.jwt_verification_key or self.jwt_jwks_file)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_cors_allowed_origins(cls, value: Any) -> list[str] | None:
        """Parse the CORS origins value from a comma-separated string or list."""
        if value is None or value == "":
            return None
        if isinstance(value, list):
            return cast(list[str], value)
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        raise ValueError("CORS_ALLOWED_ORIGINS must be a comma-separated list of origins")

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
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_pass,
            host=self.db_host,
            port=self.db_port,
            database=self.db_database,
        ).render_as_string(hide_password=False)


settings = Settings()  # type: ignore[call-arg]
