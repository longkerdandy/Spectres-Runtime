"""Team Leader Agent stub for Spectres Runtime."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai.like import OpenAILike

from spectres.config import settings
from spectres.tools.builtin import get_builtin_tools


def create_team_leader_agent(db: PostgresDb) -> Agent:
    """Create and return the Team Leader Agent stub.

    Args:
        db: Persistent PostgreSQL storage for sessions and chat history.

    Returns:
        Configured Agno Agent instance.
    """
    return Agent(
        id="team-leader",
        name="Team Leader Agent",
        model=OpenAILike(
            id=settings.team_leader_llm_model,
            api_key=settings.team_leader_llm_api_key,
            base_url=settings.team_leader_llm_base_url,
        ),
        db=db,
        tools=get_builtin_tools(),
        instructions=[
            "You are the Team Leader Agent for Spectres Runtime.",
            "Answer user questions using the available tools when needed.",
        ],
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
