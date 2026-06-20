"""Unit tests for Spectres Runtime configuration."""

from typing import Any

import pytest
from pydantic import ValidationError

from spectres.config import Settings


class TestSettingsDefaults:
    """Tests for Settings default values."""

    @pytest.fixture
    def clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove Spectres-related environment variables so defaults are used."""
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

    def test_default_database_settings(self, clean_env: None) -> None:
        """Default database settings match documented defaults."""
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.db_host == "localhost"
        assert settings.db_port == 5532
        assert settings.db_user == "ai"
        assert settings.db_pass == "ai"
        assert settings.db_database == "ai"

    def test_default_agent_os_settings(self, clean_env: None) -> None:
        """Default AgentOS server settings match documented defaults."""
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.agent_os_host == "localhost"
        assert settings.agent_os_port == 7777

    def test_default_llm_settings(self, clean_env: None) -> None:
        """Default Team Leader LLM settings match documented defaults."""
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.team_leader_llm_model == "gpt-4o"
        assert settings.team_leader_llm_api_key is None
        assert settings.team_leader_llm_base_url is None
        assert settings.team_leader_llm_temperature is None
        assert settings.team_leader_llm_max_completion_tokens is None
        assert settings.team_leader_llm_extra_headers is None


class TestSettingsEnvironment:
    """Tests for loading settings from environment variables."""

    def test_load_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
            (None, None),
            ("", None),
            ({"X-Custom": "value"}, {"X-Custom": "value"}),
            ('{"X-Custom": "value"}', {"X-Custom": "value"}),
        ],
    )
    def test_extra_headers_parsing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        input_value: Any,
        expected: dict[str, str] | None,
    ) -> None:
        """TEAM_LEADER_LLM_EXTRA_HEADERS accepts dict, JSON string, None, and empty string."""
        monkeypatch.delenv("TEAM_LEADER_LLM_EXTRA_HEADERS", raising=False)
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            team_leader_llm_extra_headers=input_value,
        )
        assert settings.team_leader_llm_extra_headers == expected

    def test_extra_headers_invalid_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEAM_LEADER_LLM_EXTRA_HEADERS rejects non-JSON strings."""
        monkeypatch.delenv("TEAM_LEADER_LLM_EXTRA_HEADERS", raising=False)
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,  # type: ignore[call-arg]
                team_leader_llm_extra_headers="not-json",
            )

    def test_database_url_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """database_url is built from the database settings."""
        for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASS", "DB_DATABASE"):
            monkeypatch.delenv(key, raising=False)

        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            db_host="db.example.com",
            db_port=5432,
            db_user="user",
            db_pass="secret",
            db_database="spectres",
        )
        assert settings.database_url == "postgresql+psycopg://user:secret@db.example.com:5432/spectres"
