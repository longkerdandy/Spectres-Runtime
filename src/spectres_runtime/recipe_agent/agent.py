"""Recipe agent construction.

The single construction entry point that AgentOS registers. ``build_recipe_agent``
wires the agent's parts from :class:`~spectres_runtime.config.Settings`:

* **model** — the hosted chat model (constructed offline; only invoked on a real run).
* **db** — the shared :class:`~agno.db.postgres.PostgresDb` (offline until a table is touched).
* **knowledge** — the shared recipe :class:`~agno.knowledge.knowledge.Knowledge` base.
* **instructions / history** — env-driven (``RECIPE_AGENT_*``); instructions become
  UI-managed later.

Each part is injectable so tests can substitute hermetic doubles (a scripted model,
a fake knowledge base) without touching a network or database. Defaults are built
from ``settings`` for the production path. ``telemetry`` is disabled explicitly —
Agno's default is on.
"""

from __future__ import annotations

from typing import Final

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.knowledge.protocol import KnowledgeProtocol
from agno.models.base import Model

from spectres_runtime.config import Settings
from spectres_runtime.recipe_agent.knowledge import build_recipe_knowledge
from spectres_runtime.storage import build_db

RECIPE_AGENT_ID: Final[str] = "recipe"
RECIPE_AGENT_NAME: Final[str] = "Recipe Agent"


def build_recipe_agent(
    settings: Settings,
    *,
    model: Model | None = None,
    knowledge: KnowledgeProtocol | None = None,
    db: BaseDb | None = None,
) -> Agent:
    """Construct the recipe agent, wiring model, knowledge, db, and instructions.

    The ``model`` / ``knowledge`` / ``db`` parameters default to objects built from
    ``settings`` and exist as injection seams for tests. ``search_knowledge`` is left
    at Agno's default (``True``), so the agent gains a knowledge-search tool;
    ``add_knowledge_to_context`` stays off (no whole-dataset injection). Conversation
    history is replayed into context with depth ``recipe_agent.num_history_runs``.
    """
    return Agent(
        id=RECIPE_AGENT_ID,
        name=RECIPE_AGENT_NAME,
        model=model or settings.build_chat_model(),
        db=db or build_db(settings),
        knowledge=knowledge or build_recipe_knowledge(settings),
        instructions=settings.recipe_agent.instructions,
        add_history_to_context=True,
        num_history_runs=settings.recipe_agent.num_history_runs,
        telemetry=False,
    )
