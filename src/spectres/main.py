"""Spectres Runtime AgentOS entry point."""

from agno.os import AgentOS
from agno.os.authz.authorization import Authorization
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.interfaces.agui import AGUI

from spectres.agents.team_leader import create_team_leader_agent
from spectres.auth import AnyAuthenticatedProvider
from spectres.config import settings
from spectres.db.postgres import get_postgres_db
from spectres.extensions.base import ExtensionContribution
from spectres.extensions.loader import load_extensions
from spectres.logging import TraceIdMiddleware, configure_logging
from spectres.scheduler import register_schedules


def create_agent_os() -> tuple[AgentOS, list[ExtensionContribution]]:
    """Create the AgentOS instance and load extensions.

    Logging is configured before anything else so startup logs use the
    runtime handlers. Extensions load between db
    setup and app assembly: their toolkits attach to the Team Leader, their
    routers mount onto the FastAPI app returned by ``agent_os.get_app()``
    before ``serve()``, and their schedules register with the AgentOS
    scheduler.

    When JWT verification material is configured, authentication is wired
    in as an ``Authorization`` object and the user directory is enabled;
    without it the app runs open (local development).

    Returns:
        The configured AgentOS plus the collected extension contributions.
    """
    configure_logging(settings)
    db = get_postgres_db()
    contributions = load_extensions(settings, db)
    register_schedules(contributions, db)
    toolkits = [toolkit for contribution in contributions for toolkit in contribution.toolkits]
    team_leader_agent = create_team_leader_agent(db, extra_tools=toolkits)
    authorization = (
        Authorization(
            db=db,
            verification_keys=[settings.jwt_verification_key] if settings.jwt_verification_key else None,
            jwks_file=settings.jwt_jwks_file,
            algorithm=settings.jwt_algorithm,
            audience=settings.jwt_audience,
            verify_audience=settings.jwt_audience is not None,
            issuer=settings.jwt_issuer,
            authorization_provider=[ScopeAuthorizationProvider(), AnyAuthenticatedProvider()],
        )
        if settings.jwt_auth_enabled
        else False
    )
    return (
        AgentOS(
            name="Spectres Runtime",
            db=db,
            agents=[team_leader_agent],
            interfaces=[AGUI(agent=team_leader_agent)],
            cors_allowed_origins=settings.cors_allowed_origins,
            scheduler=settings.scheduler_enabled,
            scheduler_poll_interval=settings.scheduler_poll_interval,
            scheduler_base_url=settings.scheduler_base_url,
            authorization=authorization,
            user_directory=settings.jwt_auth_enabled,
        ),
        contributions,
    )


agent_os, extension_contributions = create_agent_os()
app = agent_os.get_app()
for contribution in extension_contributions:
    for router in contribution.routers:
        app.include_router(router)
# Binds a fresh trace_id to every HTTP request (spectres/logging.py).
app.add_middleware(TraceIdMiddleware)

if __name__ == "__main__":
    agent_os.serve(
        app="spectres.main:app",
        host=settings.agent_os_host,
        port=settings.agent_os_port,
    )
