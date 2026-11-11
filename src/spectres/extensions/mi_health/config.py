"""Settings fragment for the Mi Health Extension."""

import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _environment_files() -> tuple[str, str]:
    env_file = os.getenv("SPECTRES_ENV_FILE", ".env")
    local_file = ".env.test.local" if env_file == ".env.test" else ".env.local"
    return env_file, local_file


class MiHealthConfig(BaseSettings):
    """Load Mi Health protocol and credential-protection settings."""

    model_config = SettingsConfigDict(
        env_prefix="MI_HEALTH_",
        env_file=_environment_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    region: Literal["cn"]
    credential_key: str | None = None
    http_timeout_seconds: float
    qr_poll_timeout_seconds: int


def load_config() -> MiHealthConfig:
    """Load configuration from the selected Runtime environment files."""
    return MiHealthConfig()  # type: ignore[call-arg]  # required fields come from environment files
