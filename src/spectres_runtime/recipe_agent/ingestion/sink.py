"""Recipe sink — consumes a recipe stream and persists it into the local store.

The write endpoint and counterpart to ``RecipeIngester`` (the producer): it
drains a stream of normalized recipes and writes each into the knowledge base
(Postgres + pgvector) the agent later searches via Agno's native agentic RAG.
Takes a plain recipe stream, not an ingester, so it is decoupled from any
origin. Writes go through the ``Knowledge`` ingestion API. Stub — not yet wired.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from spectres_runtime.recipe_agent.models import Recipe


class WriteResult(BaseModel):
    """Outcome of one write run. Counts only — field shape, no behavior."""

    written: int = 0  # recipes newly persisted into the store
    skipped: int = 0  # recipes already present, left unchanged (idempotent re-run)
    failed: int = 0  # recipes that could not be persisted


class RecipeSink:
    """Consumes a recipe stream and persists it into the local store.

    Will hold the ``Knowledge`` handle (vector store + embedder) the writes
    target; unwired in this stub.
    """

    def write(self, recipes: Iterable[Recipe]) -> WriteResult:
        """Persist every recipe in ``recipes`` into the local store, lazily.

        Returns counts of what was written, skipped, and failed.
        """
        raise NotImplementedError("Recipe sink is not wired.")
