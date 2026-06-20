"""Smoke tests for the spectres package."""

from agno.db.postgres import PostgresDb
from agno.tools.calculator import CalculatorTools
from agno.tools.shell import ShellTools
from fastapi import FastAPI

import spectres
from spectres.agents.team_leader import create_team_leader_agent
from spectres.config import Settings
from spectres.db.postgres import get_postgres_db
from spectres.main import app as main_app
from spectres.tools.builtin import get_builtin_tools


def test_package_importable() -> None:
    """Verify the spectres package is importable."""
    assert spectres is not None


def test_settings_load_with_defaults() -> None:
    """Verify settings load with expected default values when .env is not used."""

    class _TestSettings(Settings):
        model_config = Settings.model_config.copy()
        model_config["env_file"] = None

    settings = _TestSettings()
    assert settings.db_host == "localhost"
    assert settings.db_port == 5532
    assert settings.db_user == "ai"
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_get_postgres_db() -> None:
    """Verify the database adapter returns a PostgresDb instance."""
    db = get_postgres_db()
    assert isinstance(db, PostgresDb)


def test_builtin_tools() -> None:
    """Verify built-in tools include calculator and shell tools."""
    tools = get_builtin_tools()
    assert any(isinstance(tool, CalculatorTools) for tool in tools)
    assert any(isinstance(tool, ShellTools) for tool in tools)


def test_create_team_leader_agent() -> None:
    """Verify the Team Leader Agent stub can be created."""
    db = get_postgres_db()
    agent = create_team_leader_agent(db)
    assert agent.id == "team-leader"
    assert agent.add_history_to_context is True


def test_main_app() -> None:
    """Verify the AgentOS entry point exposes a FastAPI app."""
    assert isinstance(main_app, FastAPI)
