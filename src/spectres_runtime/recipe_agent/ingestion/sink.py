"""Recipe sink — consumes a recipe stream and persists it into the local store.

The write endpoint and counterpart to ``RecipeIngester`` (the producer): it
drains a stream of normalized recipes and writes each into the knowledge base
(Postgres + pgvector) the agent later searches via Agno's native agentic RAG.
Takes a plain recipe stream, not an ingester, so it is decoupled from any origin.

The write is a **full update** every run: each recipe's embedded body
is ``Recipe.content``, inserted with ``upsert=True`` under a stable ``name``
(``Recipe.id``). Agno keys its content hash on that name, so the same name
replaces the existing row in place rather than duplicating it — a re-run simply
re-embeds the corpus over itself. No per-recipe change detection is kept: the
upstream (HowToCook) releases rarely, so re-embedding everything is cheaper to
operate than tracking and reconciling body hashes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from agno.knowledge.knowledge import Knowledge
from pydantic import BaseModel

from spectres_runtime.recipe_agent.models import Recipe

logger = logging.getLogger(__name__)


class WriteResult(BaseModel):
    """Outcome of one write run. Counts only — field shape, no behavior."""

    written: int = 0  # recipes embedded and persisted (new or replaced in place)
    failed: int = 0  # recipes that could not be persisted


class RecipeSink:
    """Consumes a recipe stream and persists it into the local store.

    Holds the shared ``Knowledge`` handle (vector store + embedder + contents
    tracking) the writes target; injected so the origin and the storage wiring
    stay decoupled and the sink is unit-testable without a live database.
    """

    def __init__(self, knowledge: Knowledge) -> None:
        self._knowledge = knowledge

    def write(self, recipes: Iterable[Recipe]) -> WriteResult:
        """Persist every recipe in ``recipes`` into the local store (full update).

        Each recipe is embedded and upserted under its stable ``Recipe.id``, so a
        re-run replaces existing rows in place rather than duplicating them.
        Recipes with no body are counted as failed; insert failures are counted
        and logged, never swallowed silently. Returns the run's counts.
        """
        result = WriteResult()
        for recipe in recipes:
            if not recipe.content:
                logger.warning("recipe %s has no content to embed; counting as failed", recipe.id)
                result.failed += 1
                continue

            try:
                self._knowledge.insert(
                    name=recipe.id,  # stable key: same name + upsert replaces in place, never duplicates
                    text_content=recipe.content,  # the only embedded text
                    metadata=self._metadata(recipe),
                    upsert=True,
                )
            except Exception:
                logger.exception("failed to persist recipe %s", recipe.id)
                result.failed += 1
            else:
                result.written += 1
        return result

    @staticmethod
    def _metadata(recipe: Recipe) -> dict[str, object]:
        """Build the JSONB metadata stored beside the vector.

        Not embedded; serves provenance (``source``, ``ref``) and the
        filter/display payload (``name``, ``category``, ``difficulty``,
        ``images``, structured ``ingredients``). ``name`` is the canonical
        display name, carried so a retrieved recipe has a stable, auditable
        dish name to cite that does not depend on the body's title heading.
        """
        provenance = recipe.provenance
        return {
            "recipe_id": recipe.id,
            "name": recipe.name,
            "source": provenance.source if provenance else None,
            "ref": provenance.ref if provenance else None,
            "category": recipe.category,
            "difficulty": recipe.difficulty,
            "images": recipe.images,
            "ingredients": [{"name": i.name, "optional": i.optional} for i in recipe.ingredients],
            "description": recipe.description,
        }
