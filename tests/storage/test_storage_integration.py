"""Integration check for the §4 storage wiring against a live Postgres + pgvector.

Opt-in: marked ``integration`` (excluded from the default gate) and skipped unless
the runtime config is complete. Builds the real ``Knowledge`` handle, **ensures** the
``recipes`` table exists (non-destructively — see below), and asserts the
``embedding`` column is ``vector(N)`` with N equal to the configured embedder
dimensionality — the §4 acceptance bar. No embedding API call is made (table creation
only needs the configured dimension).

This check is deliberately **non-destructive**: it never drops the shared ``recipes``
table, so it cannot wipe the corpus the §9 retrieval test reads. The vector column's
dimensionality is fixed by the embedder config (not by rows), so asserting it against
the existing table is valid; a dimension change is a manual re-embed (operator drops
+ re-ingests), out of scope here.

Run with a populated ``.env`` (or env vars) and Postgres up:
``uv run pytest -m integration``
"""

from __future__ import annotations

import pytest
from agno.vectordb.pgvector import PgVector
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from spectres_runtime.config import Settings, get_settings
from spectres_runtime.storage.knowledge import RECIPES_TABLE, build_knowledge

pytestmark = pytest.mark.integration

# build_knowledge pins the namespace to ``public`` (storage/knowledge.py), so the
# table lands at ``public.recipes`` — not PgVector's own ``ai`` default.
_SCHEMA = "public"
# pgvector names the embedding column ``embedding``.
_COLUMN = "embedding"


def _settings_or_skip() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        pytest.skip("Runtime config incomplete (no DB/key via env / .env) — live check skipped.")


def test_recipes_table_created_with_configured_dimensionality() -> None:
    settings = _settings_or_skip()
    knowledge = build_knowledge(settings)
    vector_db = knowledge.vector_db
    assert isinstance(vector_db, PgVector)

    # Non-destructive: ensure the table exists without dropping it, so this check
    # never wipes the corpus the §9 retrieval test reads (the dimensionality comes
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
