"""Integration check for the generic storage factory against a live Postgres + pgvector.

Opt-in: marked ``integration`` (excluded from the default gate) and skipped unless the
runtime config is complete. Proves the *generic* ``build_knowledge`` factory materializes
a real pgvector table whose ``embedding`` column is ``vector(N)`` with N equal to the
configured embedder dimensionality — the live counterpart to ``test_storage``, which
only asserts the offline object wiring. No embedding API call is made (table creation
only needs the configured dimension).

Domain-agnostic by design: it uses a dedicated throwaway table (not ``recipes``), so the
recipe-specific realization is asserted separately in
``tests/recipe_agent/test_knowledge_integration``. Because the table is its own, this
check creates and **drops** it, leaving no residue and never touching shared corpus.

Run with a populated ``.env`` (or env vars) and Postgres up:
``uv run pytest -m integration``
"""

from __future__ import annotations

import pytest
from agno.vectordb.pgvector import PgVector
from sqlalchemy import create_engine, text

from spectres_runtime.storage import build_knowledge
from tests.conftest import settings_or_skip

pytestmark = pytest.mark.integration

# The factory pins the namespace to ``public`` (matching the shared PostgresDb), so the
# table lands at ``public.<table>`` — not PgVector's own ``ai`` default.
_SCHEMA = "public"
# Dedicated throwaway table — never the shared ``recipes`` corpus, so create/drop is safe.
_TABLE = "storage_dim_check"
# pgvector names the embedding column ``embedding``.
_COLUMN = "embedding"


def test_factory_creates_table_with_configured_dimensionality() -> None:
    settings = settings_or_skip()
    knowledge = build_knowledge(settings, table_name=_TABLE)
    vector_db = knowledge.vector_db
    assert isinstance(vector_db, PgVector)

    # Own table, so create destructively from a clean slate and drop on the way out.
    if vector_db.exists():
        vector_db.drop()
    vector_db.create()
    assert vector_db.exists()

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            column_type = conn.execute(
                text(
                    "SELECT format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a "
                    "JOIN pg_class c ON a.attrelid = c.oid "
                    "JOIN pg_namespace n ON c.relnamespace = n.oid "
                    "WHERE n.nspname = :schema AND c.relname = :table AND a.attname = :column"
                ),
                {"schema": _SCHEMA, "table": _TABLE, "column": _COLUMN},
            ).scalar_one()
    finally:
        engine.dispose()
        vector_db.drop()

    assert column_type == f"vector({settings.embedder_dimensions})"
