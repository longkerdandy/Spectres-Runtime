"""FastAPI application entry point for the Spectres Runtime.

Stands up an [AgentOS](https://docs.agno.com/agent-os/introduction) instance and
registers the recipe agent. AgentOS *is* a FastAPI app and ships a built-in
``/health`` liveness probe, so no custom base app is needed.

Construction is a factory, not a module-level singleton: ``build_app`` takes its
agents by injection (pure, no I/O of its own), and ``app_factory`` is the
production wiring that reads ``Settings`` and builds the real agent. Importing
this module therefore has no side effects — no DB connection, no provider SDK,
no credentials — which keeps the unit test tier hermetic. ``telemetry`` is
disabled explicitly.

Run locally with ``uvicorn spectres_runtime.app:app_factory --factory``.
"""

from __future__ import annotations

from importlib.metadata import version

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.os import AgentOS
from fastapi import FastAPI

from spectres_runtime.config import get_settings
from spectres_runtime.recipe_agent.agent import build_recipe_agent
from spectres_runtime.recipe_agent.knowledge import build_recipe_knowledge

# The HTTP/OpenAPI version of this AgentOS surface. Sourced from the installed
# package metadata (pyproject ``version``) so there is one version to maintain,
# never a hand-synced literal that drifts from the release.
_APP_VERSION = version("spectres-runtime")


def build_app(agents: list[Agent], knowledge: list[Knowledge] | None = None) -> FastAPI:
    """Construct the AgentOS app with the given agents and knowledge registered.

    Agents and knowledge bases are injected rather than built here so tests can
    register doubles. Every ``Knowledge`` instance must be registered so the
    AgentOS control plane (content management) can reach it. The liveness probe is
    AgentOS's built-in ``/health`` endpoint.
    """
    agent_os = AgentOS(
        name="Spectres Runtime",
        description="Runtime tier of the Spectres personal assistant.",
        version=_APP_VERSION,
        # ``Agent`` is a member of AgentOS's accepted union; the ignore is only the
        # invariance of ``list`` (list[Agent] vs list[Agent | ...]).
        agents=agents,  # type: ignore[arg-type]
        knowledge=knowledge,
        telemetry=False,
    )
    return agent_os.get_app()


def app_factory() -> FastAPI:  # pragma: no cover - production wiring, exercised at deploy
    """Build the production app from the environment / ``.env``.

    The ASGI factory for ``uvicorn ... --factory``: reads ``Settings`` and
    registers the real recipe agent (live model, knowledge, and db) plus the recipe
    knowledge base on the AgentOS control plane.
    """
    settings = get_settings()
    knowledge = build_recipe_knowledge(settings)
    agent = build_recipe_agent(settings, knowledge=knowledge)
    return build_app([agent], knowledge=[knowledge])


def main() -> None:  # pragma: no cover - thin uvicorn wrapper, exercised manually
    """Run the app with uvicorn for local development.

    Production deployments should invoke
    ``uvicorn spectres_runtime.app:app_factory --factory`` directly with the
    desired worker / binding flags.
    """
    import uvicorn

    uvicorn.run(
        "spectres_runtime.app:app_factory",
        host="127.0.0.1",
        port=8000,
        reload=False,
        factory=True,
    )
