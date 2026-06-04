"""The recipe knowledge base — recipe vectors in Postgres + pgvector.

Constructs the shared ``Knowledge`` handle: a ``PgVector`` store (the embedded
recipe body) plus the shared ``PostgresDb`` in its ``contents_db`` role. The
embedder is **reused** from ``Settings.build_embedder()`` so ingest (passages) and
search (queries) share one vector space — a non-negotiable for vector search.

Runtime-wide and reused across agents, not recipe-private. The ingestion sink
(plan §7) writes through this handle; the agent (v0.4) searches the same one.
"""

from __future__ import annotations

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

from spectres_runtime.config import Settings
from spectres_runtime.storage.db import build_db

# The recipe vector table.
RECIPES_TABLE = "recipes"


def build_knowledge(settings: Settings) -> Knowledge:
    """Construct the shared recipe ``Knowledge`` (vector store + contents tracking).

    Note: ``Knowledge`` opens a Postgres connection on construction (Agno checks for
    the table), so this requires a reachable database. The ``vector`` column
    dimensionality is taken from the embedder (``EMBEDDER_DIMENSIONS``, default
    1024), keeping the stored vectors and the embedder in lock-step.
    """
    vector_db = PgVector(
        table_name=RECIPES_TABLE,
        db_url=settings.database_url,
        embedder=settings.build_embedder(),
        # Vector-only: the default Postgres FTS config does not tokenize Chinese, so
        # a hybrid keyword leg would be near-useless without zhparser/pg_jieba.
        # Chinese FTS / hybrid is deferred (plan Resolved Questions).
        search_type=SearchType.vector,
        # No ANN index in v0.3: at HowToCook scale (~1-2k recipes) exact (un-indexed)
        # KNN is millisecond-fast and more accurate than ANN (plan §Out of Scope).
        # Agno types this non-Optional, but the runtime treats None as "no index".
        vector_index=None,  # type: ignore[arg-type]
    )
    return Knowledge(vector_db=vector_db, contents_db=build_db(settings))
