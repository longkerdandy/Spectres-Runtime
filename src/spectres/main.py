"""Spectres Runtime AgentOS entry point stub."""

from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

from spectres.agents.team_leader import create_team_leader_agent
from spectres.config import settings
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
        interfaces=[AGUI(agent=team_leader_agent)],
    )


agent_os = create_agent_os()
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app="spectres.main:app",
        host=settings.agent_os_host,
        port=settings.agent_os_port,
    )
