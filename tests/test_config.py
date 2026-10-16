"""Unit tests for Spectres Runtime configuration."""

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine as sa_create_engine

from spectres.config import Settings


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all required environment variables so Settings can be instantiated."""
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5532")
    monkeypatch.setenv("DB_USER", "ai")
    monkeypatch.setenv("DB_PASS", "ai")
    monkeypatch.setenv("DB_DATABASE", "ai")
    monkeypatch.setenv("AGENT_OS_HOST", "localhost")
    monkeypatch.setenv("AGENT_OS_PORT", "7777")
    monkeypatch.setenv("TEAM_LEADER_LLM_MODEL", "gpt-4o")
    monkeypatch.setenv("TEAM_LEADER_LLM_API_KEY", "")
    monkeypatch.setenv("TEAM_LEADER_LLM_BASE_URL", "https://test.example.com/v1")
    monkeypatch.setenv("TEAM_LEADER_LLM_TEMPERATURE", "0.5")
    monkeypatch.setenv("TEAM_LEADER_LLM_MAX_COMPLETION_TOKENS", "100")
    monkeypatch.setenv("TEAM_LEADER_LLM_EXTRA_HEADERS", "")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("LOG_DIR", "logs")
    monkeypatch.setenv("LOG_RETENTION_DAYS", "14")
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("SCHEDULER_POLL_INTERVAL", "15")
    monkeypatch.setenv("SCHEDULER_BASE_URL", "http://127.0.0.1:7777")


class TestSettingsRequirements:
    """Tests for required Settings fields."""

    @pytest.fixture
    def clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove all Spectres-related environment variables."""
        for key in (
            "DB_HOST",
            "DB_PORT",
            "DB_USER",
            "DB_PASS",
            "DB_DATABASE",
            "AGENT_OS_HOST",
            "AGENT_OS_PORT",
            "TEAM_LEADER_LLM_MODEL",
            "TEAM_LEADER_LLM_API_KEY",
            "TEAM_LEADER_LLM_BASE_URL",
            "TEAM_LEADER_LLM_TEMPERATURE",
            "TEAM_LEADER_LLM_MAX_COMPLETION_TOKENS",
            "TEAM_LEADER_LLM_EXTRA_HEADERS",
            "CORS_ALLOWED_ORIGINS",
            "LOG_LEVEL",
            "LOG_FORMAT",
            "LOG_DIR",
            "LOG_RETENTION_DAYS",
            "SCHEDULER_ENABLED",
            "SCHEDULER_POLL_INTERVAL",
            "SCHEDULER_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_missing_required_field_raises(self, clean_env: None) -> None:
        """Settings raises ValidationError when a required field is missing."""
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]


class TestSettingsEnvironment:
    """Tests for loading settings from environment variables."""

    def test_load_from_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """Settings are loaded from environment variables when provided."""
        monkeypatch.setenv("DB_HOST", "test-db.example.com")
        monkeypatch.setenv("DB_PORT", "5432")
        monkeypatch.setenv("DB_USER", "tester")
        monkeypatch.setenv("TEAM_LEADER_LLM_MODEL", "test-model")

        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.db_host == "test-db.example.com"
        assert settings.db_port == 5432
        assert settings.db_user == "tester"
        assert settings.team_leader_llm_model == "test-model"


class TestOptionalLlmParams:
    """TEAM_LEADER_LLM_TEMPERATURE / MAX_COMPLETION_TOKENS are truly optional."""

    def test_absent_defaults_to_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """Commenting out both variables yields None (the model default applies)."""
        monkeypatch.delenv("TEAM_LEADER_LLM_TEMPERATURE")
        monkeypatch.delenv("TEAM_LEADER_LLM_MAX_COMPLETION_TOKENS")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.team_leader_llm_temperature is None
        assert settings.team_leader_llm_max_completion_tokens is None

    def test_valid_values_parsed(
        self,
        base_env: None,
    ) -> None:
        """Numeric strings are parsed into float and int."""
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.team_leader_llm_temperature == 0.5
        assert settings.team_leader_llm_max_completion_tokens == 100

    def test_invalid_value_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """A non-numeric value is rejected with a ValidationError."""
        monkeypatch.setenv("TEAM_LEADER_LLM_TEMPERATURE", "abc")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]


class TestSettingsValidation:
    """Tests for Settings field validation."""

    @pytest.mark.parametrize(
        ("input_value", "expected"),
        [
            ("", None),
            ('{"X-Custom": "value"}', {"X-Custom": "value"}),
        ],
    )
    def test_extra_headers_parsing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
        input_value: str,
        expected: dict[str, str] | None,
    ) -> None:
        """TEAM_LEADER_LLM_EXTRA_HEADERS accepts a JSON string or empty string."""
        monkeypatch.setenv("TEAM_LEADER_LLM_EXTRA_HEADERS", input_value)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.team_leader_llm_extra_headers == expected

    def test_extra_headers_invalid_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """TEAM_LEADER_LLM_EXTRA_HEADERS rejects non-JSON strings."""
        monkeypatch.setenv("TEAM_LEADER_LLM_EXTRA_HEADERS", "not-json")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_extra_headers_absent_defaults_to_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """TEAM_LEADER_LLM_EXTRA_HEADERS defaults to None when commented out."""
        monkeypatch.delenv("TEAM_LEADER_LLM_EXTRA_HEADERS")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.team_leader_llm_extra_headers is None

    @pytest.mark.parametrize(
        ("input_value", "expected"),
        [
            ("", None),
            ("http://localhost:3000", ["http://localhost:3000"]),
            ("http://a.example.com, http://b.example.com", ["http://a.example.com", "http://b.example.com"]),
        ],
    )
    def test_cors_allowed_origins_parsing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
        input_value: str,
        expected: list[str] | None,
    ) -> None:
        """CORS_ALLOWED_ORIGINS accepts a comma-separated string or empty string."""
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", input_value)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.cors_allowed_origins == expected

    def test_cors_absent_defaults_to_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """CORS_ALLOWED_ORIGINS defaults to None when commented out."""
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS")
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.cors_allowed_origins is None

    def test_database_url_property(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """database_url is built from the database settings."""
        monkeypatch.setenv("DB_HOST", "db.example.com")
        monkeypatch.setenv("DB_PORT", "5432")
        monkeypatch.setenv("DB_USER", "user")
        monkeypatch.setenv("DB_PASS", "secret")
        monkeypatch.setenv("DB_DATABASE", "spectres")

        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.database_url == "postgresql+psycopg://user:secret@db.example.com:5432/spectres"

    def test_database_url_property_escapes_special_characters(
        self,
        monkeypatch: pytest.MonkeyPatch,
        base_env: None,
    ) -> None:
        """database_url percent-encodes credentials containing reserved characters."""
        monkeypatch.setenv("DB_HOST", "db.example.com")
        monkeypatch.setenv("DB_PORT", "5432")
        monkeypatch.setenv("DB_USER", "user")
        monkeypatch.setenv("DB_PASS", "p@ss/word%#1")
        monkeypatch.setenv("DB_DATABASE", "spectres")

        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.database_url == "postgresql+psycopg://user:p%40ss%2Fword%25%231@db.example.com:5432/spectres"

        engine = sa_create_engine(settings.database_url)
        assert engine.url.password == "p@ss/word%#1"
