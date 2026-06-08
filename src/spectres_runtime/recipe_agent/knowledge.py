"""The recipe agent's knowledge base — recipe vectors in Postgres + pgvector.

Owns the recipe-private identity (the ``recipes`` table, the AgentOS-facing name)
and wraps the generic :func:`~spectres_runtime.storage.knowledge.build_knowledge`
mechanism. The ingestion sink writes through this handle; the agent searches the
same one.
"""

from __future__ import annotations

from typing import Final

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import SearchType

from spectres_runtime.config import Settings
from spectres_runtime.storage import build_knowledge

# The recipe vector table — a schema data contract, pinned here as a constant.
RECIPES_TABLE: Final[str] = "recipes"


def build_recipe_knowledge(settings: Settings) -> Knowledge:
    """Construct the recipe ``Knowledge`` base (vector store + contents tracking).

    Vector-only search: Postgres FTS can't tokenize Chinese (hybrid deferred). Uses
    the shared embedder so ingest and search share one vector space.
    """
    return build_knowledge(
        settings,
        table_name=RECIPES_TABLE,
        name="Recipe Knowledge",
        description="Cookable recipes with ingredients and steps.",
        search_type=SearchType.vector,
    )
