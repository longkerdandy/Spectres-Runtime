"""FastAPI application entry point for the Spectres Runtime.

Stands up an [AgentOS](https://docs.agno.com/agent-os/introduction) instance and
registers the placeholder recipe agent. AgentOS *is* a FastAPI app and ships a
built-in ``/health`` liveness probe, so no custom base app is needed — the
module-level ``app`` is preserved so ``uvicorn spectres_runtime.app:app`` and
container / CI health checks keep working.

No ``PostgresDb``, ``knowledge``, ``dependencies``, or tools are wired here, and
the agent's model is never invoked — this is a structural skeleton only.
``telemetry`` is disabled so construction stays network-free.
"""

from __future__ import annotations

from typing import Final

from agno.os import AgentOS
from fastapi import FastAPI

from spectres_runtime.recipe_agent.agent import build_recipe_agent


def build_app() -> FastAPI:
    """Construct the AgentOS app with the placeholder recipe agent registered.

    Static construction at module load is sufficient for one built-in stub
    agent; an ``AgentFactory`` / directory-driven construction is deferred.
    The liveness probe is AgentOS's built-in ``/health`` endpoint.
    """
    agent_os = AgentOS(
        name="Spectres Runtime",
        description="Runtime tier of the Spectres personal assistant.",
        version="0.2.0",
        agents=[build_recipe_agent()],
        telemetry=False,
    )
    return agent_os.get_app()


app: Final[FastAPI] = build_app()


def main() -> None:  # pragma: no cover - thin uvicorn wrapper, exercised manually
    """Run the app with uvicorn for local development.

    Production deployments should invoke ``uvicorn spectres_runtime.app:app``
    directly with the desired worker / binding flags.
    """
    import uvicorn

    uvicorn.run(
        "spectres_runtime.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
