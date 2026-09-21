"""Integration tests that require a running PostgreSQL database."""

import pytest

from spectres.agents.team_leader import create_team_leader_agent
from spectres.db.postgres import get_postgres_db

pytestmark = [pytest.mark.integration, pytest.mark.db]


def test_create_team_leader_agent_with_real_db() -> None:
    """The database adapter connects and the Team Leader Agent uses it."""
    db = get_postgres_db()
    agent = create_team_leader_agent(db)
    assert agent.id == "team-leader"
    assert agent.db is db
