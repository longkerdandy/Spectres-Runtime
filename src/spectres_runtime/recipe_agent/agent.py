"""Recipe agent construction.

The single construction entry point that AgentOS registers. ``build_recipe_agent``
wires the agent's parts from :class:`~spectres_runtime.config.Settings`:

* **model** — the hosted chat model (constructed offline; only invoked on a real run).
* **db** — the shared :class:`~agno.db.postgres.PostgresDb` (offline until a table is touched).
* **instructions / history** — env-driven (``RECIPE_AGENT_*``); instructions become
  UI-managed later.

Each part is injectable so tests can substitute hermetic doubles (a scripted model)
without touching a network or database. Defaults are built from ``settings`` for the
production path. ``telemetry`` is disabled explicitly — Agno's default is on.
"""

from __future__ import annotations

from typing import Final

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.models.base import Model

from spectres_runtime.config import Settings
from spectres_runtime.recipe_agent.tools import (
    build_get_recipe_detail_tool,
    build_search_recipes_tool,
)
from spectres_runtime.storage import build_db

RECIPE_AGENT_ID: Final[str] = "recipe"
RECIPE_AGENT_NAME: Final[str] = "Recipe Agent"

# Single-household default identity. v0.4 has no auth/multi-user (deferred module),
# so runs that omit ``user_id`` attribute to this stable id — which scopes sessions
# and history meaningfully from day one and eases a later multi-user migration. A
# request-supplied ``user_id`` still overrides it per run. Temporary: replaced by
# real authenticated identities when the profile/auth module lands.
DEFAULT_USER_ID: Final[str] = "developer"

# Default system instructions. Kept in code (not .env) so formatting requirements
# are version-controlled and consistent across deployments. Users can still override
# via the ``RECIPE_AGENT_INSTRUCTIONS`` env var when needed.
DEFAULT_RECIPE_AGENT_INSTRUCTIONS: Final[str] = """\
You are the Recipe Agent for the Spectres personal assistant. Help users with
recipes, meal planning, and cooking questions.

When to use tools:
- If the question is about recipes, dishes, ingredients, meal planning, or
  "what can I cook", use the recipe tools below.
- For greetings, chit-chat, or unrelated questions, reply directly without
  calling any tool.

How to use the tools:
- To discover candidate dishes or build a menu, call ``search_recipes``. It
  returns lightweight metadata only — no cooking steps.
- To answer "how to make" a specific dish, first call ``search_recipes`` to
  find the ``recipe_id``, then call ``get_recipe_detail`` with that
  ``recipe_id``.
- Do not call ``get_recipe_detail`` unless the user asks for detailed cooking
  instructions or ingredients.
- You may call ``search_recipes`` multiple times with different categories or
  queries to build a balanced menu.

Grounding rules:
- Base every recipe-related answer on the recipes returned by the tools. If
  nothing relevant is found, say so rather than inventing one.
- Name the dishes you refer to, and keep using the same name in follow-up
  questions about it.

Current limitations:
- You do not yet keep a saved, editable meal plan.
- You have no information about household members or their dietary needs.
- If asked to revise a previously saved plan, or to tailor meals to specific
  people's tastes, portions, or restrictions, say that is not available yet and
  offer what you can do now.

Formatting:
- Reply in the user's language.
- When you include a full recipe, format it as Markdown: use a level-2 heading
  (##) for the dish name, bullet points for ingredients, and a numbered list
  for steps.
- Mention images only if the recipe metadata includes them; do not fabricate URLs.
"""


def build_recipe_agent(
    settings: Settings,
    *,
    model: Model | None = None,
    db: BaseDb | None = None,
) -> Agent:
    """Construct the recipe agent, wiring model, db, and instructions.

    The ``model`` / ``db`` parameters default to objects built from ``settings``
    and exist as injection seams for tests. Conversation history is replayed into
    context with depth ``recipe_agent.num_history_runs``. ``user_id`` defaults to
    :data:`DEFAULT_USER_ID` (single-household), overridable per request.
    """
    instructions = settings.recipe_agent.instructions or DEFAULT_RECIPE_AGENT_INSTRUCTIONS
    return Agent(
        id=RECIPE_AGENT_ID,
        name=RECIPE_AGENT_NAME,
        model=model or settings.recipe_agent.build_chat_model(),
        db=db or build_db(settings),
        tools=[
            build_search_recipes_tool(settings),
            build_get_recipe_detail_tool(settings),
        ],
        instructions=instructions,
        add_history_to_context=True,
        num_history_runs=settings.recipe_agent.num_history_runs,
        user_id=DEFAULT_USER_ID,
        telemetry=False,
        markdown=True,
    )
