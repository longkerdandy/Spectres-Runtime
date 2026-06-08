"""Integration check for the recipe knowledge handle against a live Postgres + pgvector.

Opt-in: marked ``integration`` (excluded from the default gate) and skipped unless the
runtime config is complete. Builds the real recipe ``Knowledge`` handle, **ensures** the
``recipes`` table exists (non-destructively — see below), and asserts its ``embedding``
column is ``vector(N)`` with N equal to the configured embedder dimensionality. No
embedding API call is made (table creation only needs the configured dimension).

This proves the recipe-private identity (``build_recipe_knowledge`` / ``RECIPES_TABLE``)
is materialized correctly in the live store — the recipe-layer counterpart to the
generic ``test_storage_integration``. It runs even on a fresh, unpopulated DB, so it
complements ``test_retrieval_integration`` (which skips when the corpus is empty).

This check is deliberately **non-destructive**: it never drops the shared ``recipes``
table, so it cannot wipe the corpus the retrieval test reads. The vector column's
dimensionality is fixed by the embedder config (not by rows), so asserting it against
the existing table is valid; a dimension change is a manual re-embed (operator drops
+ re-ingests), out of scope here.

Run with a populated ``.env`` (or env vars) and Postgres up:
``uv run pytest -m integration``
"""

from __future__ import annotations

import pytest
from agno.vectordb.pgvector import PgVector
from sqlalchemy import create_engine, text

from spectres_runtime.recipe_agent.knowledge import RECIPES_TABLE, build_recipe_knowledge
from tests.conftest import settings_or_skip

pytestmark = pytest.mark.integration

# The knowledge handle pins the namespace to ``public``, so the table lands at
# ``public.recipes`` — not PgVector's own ``ai`` default.
_SCHEMA = "public"
# pgvector names the embedding column ``embedding``.
_COLUMN = "embedding"


def test_recipes_table_created_with_configured_dimensionality() -> None:
    settings = settings_or_skip()
    knowledge = build_recipe_knowledge(settings)
    vector_db = knowledge.vector_db
    assert isinstance(vector_db, PgVector)

    # Non-destructive: ensure the table exists without dropping it, so this check
    # never wipes the corpus the retrieval test reads (the dimensionality comes
    # from the embedder config, not the rows, so the existing table is fine to assert
    # against).
    if not vector_db.exists():
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
                {"schema": _SCHEMA, "table": RECIPES_TABLE, "column": _COLUMN},
            ).scalar_one()
    finally:
        engine.dispose()

    assert column_type == f"vector({settings.embedder_dimensions})"
