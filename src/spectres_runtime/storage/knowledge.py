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
        table_name=RECIPES_TABLE,  # the recipe vector table
        db_url=settings.database_url,  # shared Postgres + pgvector connection
        embedder=settings.build_embedder(),  # reused embedder: ingest & search share one vector space
        schema="public",  # pin namespace to public (Agno default is "ai"); matches db.py
        search_type=SearchType.vector,  # vector-only: Postgres FTS can't tokenize Chinese (hybrid deferred)
        vector_index=None,  # type: ignore[arg-type]  # no ANN index in v0.3: exact KNN at ~1-2k recipes
    )
    return Knowledge(vector_db=vector_db, contents_db=build_db(settings))
