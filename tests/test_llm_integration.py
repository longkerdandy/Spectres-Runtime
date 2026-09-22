"""Integration tests against a real LLM API.

These tests call the LLM configured in .env.test (z.ai's free GLM model
by default; GitHub Models was retired 2026-07-30). The API key must be
provided via the gitignored .env.test.local file.
"""

import pytest

from spectres.agents.team_leader import create_team_leader_agent
from spectres.config import settings
from spectres.db.postgres import get_postgres_db

pytestmark = [pytest.mark.integration, pytest.mark.llm]

_PLACEHOLDER_KEYS = {None, "", "FAKE_API_KEY"}


@pytest.mark.skipif(
    settings.team_leader_llm_api_key in _PLACEHOLDER_KEYS,
    reason="requires a real LLM API key in .env.test.local",
)
def test_team_leader_responds_to_greeting() -> None:
    """The Team Leader Agent can call the configured LLM and return a response."""
    db = get_postgres_db()
    agent = create_team_leader_agent(db)
    response = agent.run("你好,请简短回复。", stream=False)

    assert response.content is not None
    # A real LLM call consumes tokens. Agno embeds provider/parse failures as
    # plain content strings, so a content-only assertion passes vacuously on
    # errors (seen in practice with a retired endpoint returning a stub body).
    assert response.metrics is not None
    assert response.metrics.output_tokens > 0
