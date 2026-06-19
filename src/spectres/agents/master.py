"""Master Agent stub for Spectres Runtime."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb

from spectres.tools.builtin import get_builtin_tools


def create_master_agent(db: PostgresDb) -> Agent:
    """Create and return the Master Agent stub.

    Args:
        db: Persistent PostgreSQL storage for sessions and chat history.

    Returns:
        Configured Agno Agent instance.
    """
    return Agent(
        id="master",
        name="Master Agent",
        db=db,
        tools=get_builtin_tools(),
        instructions=[
            "You are the Master Agent for Spectres Runtime.",
            "Answer user questions using the available tools when needed.",
        ],
        add_history_to_context=True,
        num_history_runs=5,
        markdown=True,
    )
