"""Integration tests against a real LLM API.

These tests call the LLM configured in .env.test (GitHub Models by default).
The API key must be provided via the gitignored .env.test.local file.
"""

import pytest

from spectres.agents.team_leader import create_team_leader_agent
from spectres.db.postgres import get_postgres_db

pytestmark = [pytest.mark.integration, pytest.mark.llm]


def test_team_leader_responds_to_greeting() -> None:
    """The Team Leader Agent can call the configured LLM and return a response."""
    db = get_postgres_db()
    agent = create_team_leader_agent(db)
    response = agent.run("你好,请简短回复。", stream=False)

    assert response.content is not None
    assert len(str(response.content).strip()) > 0
