"""FastAPI application entry point for the Spectres Runtime.

Stands up an [AgentOS](https://docs.agno.com/agent-os/introduction) instance and
registers the placeholder recipe agent. AgentOS *is* a FastAPI app; we build our
own base app to keep the ``/healthz`` liveness probe and hand it to AgentOS via
``base_app`` so the merged app retains both surfaces. The module-level ``app``
is preserved so ``uvicorn spectres_runtime.app:app`` and existing probes keep
working.

No ``PostgresDb``, ``knowledge``, ``dependencies``, or tools are wired here, and
the agent's model is never invoked — this is a structural skeleton only.
``telemetry`` is disabled so construction stays network-free.
"""

from __future__ import annotations

from typing import Final

from agno.os import AgentOS
from fastapi import FastAPI

from spectres_runtime.recipe_agent.agent import build_recipe_agent


def _build_base_app() -> FastAPI:
    """Build the base FastAPI app that owns the ``/healthz`` probe.

    Handed to AgentOS as ``base_app`` so the merged application keeps this
    route alongside the AgentOS HTTP surface.
    """
    base = FastAPI(
        title="Spectres Runtime",
        version="0.2.0",
        description="Runtime tier of the Spectres personal assistant.",
    )

    @base.get("/healthz", tags=["meta"], summary="Liveness probe")
    async def healthz() -> dict[str, str]:
        """Return a static OK payload.

        Intended for container / CI liveness checks. Has no side effects and
        performs no I/O, so it is safe to poll at high frequency.
        """
        return {"status": "ok"}

    return base


def build_app() -> FastAPI:
    """Construct the AgentOS app with the placeholder recipe agent registered.

    Static construction at module load is sufficient for one built-in stub
    agent; an ``AgentFactory`` / directory-driven construction is deferred.
    """
    agent_os = AgentOS(
        name="Spectres Runtime",
        description="Runtime tier of the Spectres personal assistant.",
        version="0.2.0",
        agents=[build_recipe_agent()],
        base_app=_build_base_app(),
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
