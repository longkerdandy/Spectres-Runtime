"""Spectres Runtime AgentOS entry point stub."""

from agno.os import AgentOS

from spectres.agents.master import create_master_agent
from spectres.db.postgres import get_postgres_db


def create_agent_os() -> AgentOS:
    """Create and return the Spectres Runtime AgentOS instance.

    Returns:
        Configured AgentOS with the Master Agent.
    """
    db = get_postgres_db()
    master_agent = create_master_agent(db)
    return AgentOS(
        name="Spectres Runtime",
        agents=[master_agent],
    )


agent_os = create_agent_os()
app = agent_os.get_app()
