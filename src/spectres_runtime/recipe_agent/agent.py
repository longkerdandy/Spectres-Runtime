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
You are the Recipe Agent for the Spectres personal assistant. Search the recipe
knowledge base before answering and ground every answer in the retrieved recipes;
if nothing relevant is found, say so rather than inventing one. When you ground an
answer in a recipe, name the dish you drew from so the source is visible and
auditable; if you used several recipes, name each one, and keep naming the same
dish when answering follow-up questions about it. You can put together a full meal
of several dishes and a soup, or a multi-day menu, with each dish grounded in a
retrieved recipe. You do not yet keep a saved, editable meal plan, and you have no
information about household members or their dietary needs: if asked to revise a
previously saved plan, or to tailor meals to specific people's tastes, portions,
or restrictions, say that is not available yet and offer what you can do now.
Reply in the user's language.

Format every recipe answer as Markdown:
- Use a level-2 heading (##) for the dish name.
- List ingredients as bullet points or a small table.
- List cooking steps as a numbered list.
- Add a short preamble for difficulty / time if known.
- Name the dish/dishes you grounded the answer in.
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
        instructions=instructions,
        add_history_to_context=True,
        num_history_runs=settings.recipe_agent.num_history_runs,
        user_id=DEFAULT_USER_ID,
        telemetry=False,
        markdown=True,
    )
