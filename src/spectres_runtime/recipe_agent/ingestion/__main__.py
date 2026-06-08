"""Ingestion entry point — the one-shot batch command that populates the recipe
knowledge base.

Exposed as the ``recipe-ingest`` console script (``[project.scripts]``). Because it
lives in ``__main__.py`` it is also runnable as
``python -m spectres_runtime.recipe_agent.ingestion``. It wires the HowToCook
ingester to the recipe sink through the shared ``Knowledge`` handle and reports the
resulting counts.

Idempotent: re-running rewrites the corpus over itself with no duplicate
rows, so this is the safe, repeatable way to (re)populate the store. Requires a
reachable Postgres + pgvector and a configured embedder (``Settings`` / ``.env``).
"""

from __future__ import annotations

import logging
import sys

from spectres_runtime.config import get_settings
from spectres_runtime.recipe_agent.ingestion.howtocook import HowToCookIngester
from spectres_runtime.recipe_agent.ingestion.sink import RecipeSink
from spectres_runtime.recipe_agent.knowledge import build_recipe_knowledge

logger = logging.getLogger(__name__)


def main() -> int:  # pragma: no cover - one-shot ingestion glue; needs a live DB + embedder
    """Run one full ingestion pass and report counts; return a process exit code.

    Builds the recipe ``Knowledge`` handle (DB + embedder) from ``Settings``, drains
    ``HowToCookIngester.ingest()`` through ``RecipeSink.write()``, and logs the
    ``WriteResult``. Returns ``1`` when any recipe failed to persist (so callers / CI
    can detect a partial run), ``0`` on a clean full write.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    knowledge = build_recipe_knowledge(settings)
    sink = RecipeSink(knowledge)
    ingester = HowToCookIngester()

    logger.info("ingesting recipes from source %r", ingester.name)
    result = sink.write(ingester.ingest())
    logger.info("ingestion complete: written=%d failed=%d", result.written, result.failed)

    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
