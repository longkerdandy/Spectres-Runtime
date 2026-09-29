"""Spectres Runtime AgentOS entry point stub."""

from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

from spectres.agents.team_leader import create_team_leader_agent
from spectres.config import settings
from spectres.db.postgres import get_postgres_db
from spectres.extensions.base import ExtensionContribution
from spectres.extensions.loader import load_extensions


def create_agent_os() -> tuple[AgentOS, list[ExtensionContribution]]:
    """Create the AgentOS instance and load extensions (runtime-extensions.md §5.2).

    Extensions load between db setup and app assembly: their toolkits
    attach to the Team Leader, their routers mount onto the FastAPI app
    returned by ``agent_os.get_app()`` before ``serve()``.

    Returns:
        The configured AgentOS plus the collected extension contributions.
    """
    db = get_postgres_db()
    contributions = load_extensions(settings, db)
    toolkits = [toolkit for contribution in contributions for toolkit in contribution.toolkits]
    team_leader_agent = create_team_leader_agent(db, extra_tools=toolkits)
    return (
        AgentOS(
            name="Spectres Runtime",
            agents=[team_leader_agent],
            interfaces=[AGUI(agent=team_leader_agent)],
            cors_allowed_origins=settings.cors_allowed_origins,
        ),
        contributions,
    )


agent_os, extension_contributions = create_agent_os()
app = agent_os.get_app()
for contribution in extension_contributions:
    for router in contribution.routers:
        app.include_router(router)

if __name__ == "__main__":
    agent_os.serve(
        app="spectres.main:app",
        host=settings.agent_os_host,
        port=settings.agent_os_port,
    )
