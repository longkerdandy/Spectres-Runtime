"""Spectres Runtime AgentOS entry point."""

import logging

from agno.os import AgentOS
from agno.os.authz.authorization import Authorization
from agno.os.interfaces.agui import AGUI
from agno.workflow import RemoteWorkflow, Workflow, WorkflowFactory
from fastapi import FastAPI

from spectres.agents.team_leader import create_team_leader_agent
from spectres.api import create_api_router
from spectres.auth import UserProfileSyncMiddleware
from spectres.config import settings
from spectres.db.postgres import get_postgres_db
from spectres.extensions.activation import guard_extension_toolkit, guard_extension_workflows, include_extension_routers
from spectres.extensions.base import LoadedExtension
from spectres.extensions.loader import load_extensions
from spectres.extensions.state import ExtensionStateService
from spectres.logging import TraceIdMiddleware, configure_logging
from spectres.scheduler import register_schedules

logger = logging.getLogger(__name__)


def mount_extension_routers(app: FastAPI, extensions: list[LoadedExtension]) -> None:
    """Mount built-in Extension routers with database-backed activation guards."""
    state_service = ExtensionStateService(get_postgres_db(), [extension.id for extension in extensions])
    include_extension_routers(app, extensions, state_service)


def create_agent_os() -> tuple[AgentOS, list[LoadedExtension]]:
    """Create the AgentOS instance and load extensions.

    Logging is configured before anything else so startup logs use the
    runtime handlers. Extensions load between db
    setup and app assembly: their toolkits attach to the Team Leader, their
    Workflows join the AgentOS registry, their routers mount onto the FastAPI
    app returned by ``agent_os.get_app()`` before ``serve()``, and their
    schedules register with the AgentOS scheduler.

    When JWT verification material is configured, authentication is wired
    in as an ``Authorization`` object and the user directory is enabled;
    without it the app runs open (local development).

    Returns:
        The configured AgentOS plus the loaded extensions.
    """
    configure_logging(settings)
    logger.info("Per-user data isolation enabled", extra={"event": "user_isolation_enabled"})
    db = get_postgres_db()
    extensions = load_extensions(settings, db)
    extension_state = ExtensionStateService(db, [extension.id for extension in extensions])
    extension_state.initialize()
    register_schedules([spec for extension in extensions for spec in extension.contribution.schedules], db)
    for extension in extensions:
        guard_extension_toolkit(extension, extension_state)
        guard_extension_workflows(extension, extension_state)
    toolkits = [toolkit for extension in extensions for toolkit in extension.contribution.toolkits]
    workflows: list[Workflow | RemoteWorkflow | WorkflowFactory] = [workflow for extension in extensions for workflow in extension.contribution.workflows]
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
        )
        if settings.jwt_auth_enabled
        else False
    )
    base_app = FastAPI()
    base_app.add_middleware(UserProfileSyncMiddleware)
    base_app.include_router(create_api_router(extension_state, extensions))
    return (
        AgentOS(
            name="Spectres Runtime",
            base_app=base_app,
            db=db,
            agents=[team_leader_agent],
            workflows=workflows,
            interfaces=[AGUI(agent=team_leader_agent)],
            cors_allowed_origins=settings.cors_allowed_origins,
            telemetry=settings.agno_telemetry,
            scheduler=settings.scheduler_enabled,
            scheduler_poll_interval=settings.scheduler_poll_interval,
            scheduler_base_url=settings.scheduler_base_url,
            authorization=authorization,
            user_directory=settings.jwt_auth_enabled,
            user_isolation=True,
        ),
        extensions,
    )


agent_os, loaded_extensions = create_agent_os()
app = agent_os.get_app()
mount_extension_routers(app, loaded_extensions)
# Binds a fresh trace_id to every HTTP request (spectres/logging.py).
app.add_middleware(TraceIdMiddleware)

if __name__ == "__main__":
    agent_os.serve(
        app="spectres.main:app",
        host=settings.agent_os_host,
        port=settings.agent_os_port,
    )
