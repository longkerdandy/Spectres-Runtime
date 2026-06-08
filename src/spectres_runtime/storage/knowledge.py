"""Generic ``Knowledge`` factory — a vector store in Postgres + pgvector.

A reusable mechanism, not a single domain's store: each knowledge base is
physically isolated by its own ``table_name`` (Agno best practice — separate
knowledge by domain, distinct tables to avoid collisions), while sharing the one
``PostgresDb`` in its ``contents_db`` role. Callers own their identity (table
name, display name, search strategy) and pass it in; agents wrap this in their own
package (e.g. ``recipe_agent.knowledge``).

The embedder defaults to the shared ``Settings.build_embedder()`` so ingest
(passages) and search (queries) share one vector space — a non-negotiable for
vector search — but a caller may inject a domain-specific embedder.
"""

from __future__ import annotations

from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

from spectres_runtime.config import Settings
from spectres_runtime.storage.db import build_db


def build_knowledge(
    settings: Settings,
    *,
    table_name: str,
    name: str | None = None,
    description: str | None = None,
    search_type: SearchType = SearchType.vector,
    embedder: Embedder | None = None,
) -> Knowledge:
    """Construct a ``Knowledge`` (vector store + contents tracking) for one domain.

    ``table_name`` physically isolates this knowledge base; ``name`` /
    ``description`` are the AgentOS-facing identity. ``search_type`` defaults to
    vector-only (Postgres FTS can't tokenize Chinese; hybrid deferred). ``embedder``
    defaults to the shared one from ``settings`` so ingest and search share a vector
    space.

    Note: ``Knowledge`` opens a Postgres connection on construction (Agno checks for
    the table), so this requires a reachable database. The ``vector`` column
    dimensionality is taken from the embedder (``EMBEDDER_DIMENSIONS``, default
    1024), keeping the stored vectors and the embedder in lock-step.
    """
    vector_db = PgVector(
        table_name=table_name,  # physically isolates this domain's vectors
        db_url=settings.database_url,  # shared Postgres + pgvector connection
        embedder=embedder or settings.build_embedder(),  # reused embedder: ingest & search share one vector space
        schema="public",  # pin namespace to public (Agno default is "ai"); matches db.py
        search_type=search_type,
        vector_index=None,  # type: ignore[arg-type]  # no ANN index: exact KNN at ~1-2k recipes
    )
    return Knowledge(
        name=name,
        description=description,
        vector_db=vector_db,
        contents_db=build_db(settings),
    )
