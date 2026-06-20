"""Integration tests against a real LLM API.

These tests call the LLM configured in .env.test (GitHub Models by default).
The API key must be provided via the gitignored .env.test.local file.
"""

from agno.db.postgres import PostgresDb

from spectres.agents.team_leader import create_team_leader_agent
from spectres.config import settings
from spectres.db.postgres import get_postgres_db


def test_team_leader_responds_to_greeting() -> None:
    """Verify the Team Leader Agent can call the configured LLM and return a response."""
    assert settings.team_leader_llm_api_key, (
        "TEAM_LEADER_LLM_API_KEY must be set in .env.test.local to run integration tests."
    )

    db = get_postgres_db()
    assert isinstance(db, PostgresDb)

    agent = create_team_leader_agent(db)
    response = agent.run("你好,请简短回复。", stream=False)

    assert response.content is not None
    assert len(str(response.content).strip()) > 0
