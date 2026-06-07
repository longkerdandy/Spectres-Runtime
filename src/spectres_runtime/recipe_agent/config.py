"""Recipe-agent-specific configuration.

Co-located with the agent it configures so the ``recipe_agent`` package stays
self-contained: its config *schema* lives next to its construction logic, not in
the top-level :mod:`spectres_runtime.config`. Shared infrastructure config
(database, embedder, chat) remains in the root ``Settings``.

Reads the same single ``.env`` as the root settings; the ``RECIPE_AGENT_``
``env_prefix`` keeps the existing variable names unchanged
(``RECIPE_AGENT_INSTRUCTIONS`` -> ``instructions``,
``RECIPE_AGENT_NUM_HISTORY_RUNS`` -> ``num_history_runs``).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class RecipeAgentSettings(BaseSettings):
    """Typed, env-driven config private to the recipe agent.

    No defaults — every value comes from the process env or a git-ignored
    ``.env`` (documented in ``.env.example``).
    """

    # Same `.env` as the root settings; the prefix maps `RECIPE_AGENT_<FIELD>`.
    model_config = SettingsConfigDict(
        env_prefix="RECIPE_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    instructions: str  # Recipe agent system instructions (env-driven now; UI-managed later).
    num_history_runs: int  # Prior conversation turns replayed into the agent's context.
