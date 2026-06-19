"""Typed configuration for Spectres Runtime."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5532, alias="DB_PORT")
    db_user: str = Field(default="ai", alias="DB_USER")
    db_pass: str = Field(default="ai", alias="DB_PASS")
    db_database: str = Field(default="ai", alias="DB_DATABASE")

    # Model providers
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    @property
    def database_url(self) -> str:
        """Return the PostgreSQL connection URL."""
        return f"postgresql+psycopg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_database}"


settings = Settings()
