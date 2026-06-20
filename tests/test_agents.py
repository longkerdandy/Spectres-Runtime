"""Unit tests for Spectres Runtime agent definitions."""

from unittest.mock import MagicMock

import pytest
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai.like import OpenAILike

from spectres.agents.team_leader import create_team_leader_agent
from spectres.config import settings


def test_create_team_leader_agent_returns_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Team Leader Agent factory returns a configured Agent instance."""
    monkeypatch.setattr(settings, "team_leader_llm_api_key", "test-api-key")

    db = MagicMock(spec=PostgresDb)
    agent = create_team_leader_agent(db)

    assert isinstance(agent, Agent)
    assert agent.id == "team-leader"
    assert agent.name == "Team Leader Agent"
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 3
    assert agent.add_datetime_to_context is True
    assert agent.markdown is True
    assert agent.db is db


def test_create_team_leader_agent_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The created agent is configured from application settings."""
    monkeypatch.setattr(settings, "team_leader_llm_model", "test-model")
    monkeypatch.setattr(settings, "team_leader_llm_api_key", "test-api-key")
    monkeypatch.setattr(settings, "team_leader_llm_base_url", "https://test.example.com/v1")

    db = MagicMock(spec=PostgresDb)
    agent = create_team_leader_agent(db)

    assert agent.model is not None
    assert isinstance(agent.model, OpenAILike)
    assert agent.model.id == "test-model"
    assert agent.model.api_key == "test-api-key"
    assert agent.model.base_url == "https://test.example.com/v1"
