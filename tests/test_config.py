"""Unit tests for Spectres Runtime configuration."""

import pytest
from pydantic import ValidationError

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
        ):
            monkeypatch.delenv(key, raising=False)

    def test_missing_required_field_raises(self, clean_env: None) -> None:
        """Settings raises ValidationError when a required field is missing."""
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_missing_database_field_raises(self, clean_env: None) -> None:
        """Settings raises ValidationError when database fields are missing."""
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
