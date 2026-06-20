"""Integration tests that require a running PostgreSQL database."""

import pytest
from agno.db.postgres import PostgresDb

from spectres.agents.team_leader import create_team_leader_agent
from spectres.db.postgres import get_postgres_db

pytestmark = [pytest.mark.integration, pytest.mark.db]


def test_get_postgres_db_returns_postgres_db() -> None:
    """The database adapter returns a PostgresDb instance."""
    db = get_postgres_db()
    assert isinstance(db, PostgresDb)


def test_create_team_leader_agent_with_real_db() -> None:
    """The Team Leader Agent can be created with a real database adapter."""
    db = get_postgres_db()
    agent = create_team_leader_agent(db)
    assert agent.id == "team-leader"
    assert agent.db is db
