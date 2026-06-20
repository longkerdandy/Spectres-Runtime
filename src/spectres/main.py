"""Spectres Runtime AgentOS entry point stub."""

from agno.os import AgentOS

from spectres.agents.team_leader import create_team_leader_agent
from spectres.db.postgres import get_postgres_db


def create_agent_os() -> AgentOS:
    """Create and return the Spectres Runtime AgentOS instance.

    Returns:
        Configured AgentOS with the Team Leader Agent.
    """
    db = get_postgres_db()
    team_leader_agent = create_team_leader_agent(db)
    return AgentOS(
        name="Spectres Runtime",
        agents=[team_leader_agent],
    )


agent_os = create_agent_os()
app = agent_os.get_app()
