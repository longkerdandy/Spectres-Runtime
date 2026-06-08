"""Unit tests for ``spectres_runtime.storage`` — pure, no DB, no network.

``build_db`` and the ``PgVector`` half of ``build_knowledge`` construct offline
(SQLAlchemy engines are lazy). Only ``Knowledge(...)`` opens a connection, so here it
is patched with a recorder to assert the wiring without a database. The live
table-creation check lives in the ``integration`` tier (see
``test_storage_integration``).
"""

from __future__ import annotations

import pytest
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.vectordb.pgvector import PgVector, SearchType

from spectres_runtime.config import Settings
from spectres_runtime.storage import build_db, build_knowledge
from spectres_runtime.storage import knowledge as knowledge_module
from tests.conftest import make_settings

_DB_URL = "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime"


def _settings() -> Settings:
    # Shared factory; the embedder/db fields below are what these tests assert on.
    return make_settings(database_url=_DB_URL)


def test_build_db_returns_shared_postgres_handle() -> None:
    db = build_db(_settings())

    assert isinstance(db, PostgresDb)
    assert db.db_url == _DB_URL
    # Schema is pinned to public, not Agno's library default ("ai").
    assert db.db_schema == "public"


def test_build_knowledge_wires_vector_store_and_contents_db(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _RecordingKnowledge:
        def __init__(
            self,
            vector_db: object = None,
            contents_db: object = None,
            name: object = None,
            description: object = None,
        ) -> None:
            captured["vector_db"] = vector_db
            captured["contents_db"] = contents_db
            captured["name"] = name
            captured["description"] = description

    # Patch only the connecting part; the real PgVector / PostgresDb are built offline.
    monkeypatch.setattr(knowledge_module, "Knowledge", _RecordingKnowledge)
    result = build_knowledge(
        _settings(),
        table_name="widgets",
        name="Widget Knowledge",
        description="Test widgets.",
    )

    vector_db = captured["vector_db"]
    assert isinstance(vector_db, PgVector)
    # The caller-supplied table name is wired through (generic factory, no hardcoded domain).
    assert vector_db.table_name == "widgets"
    # Pinned to public, matching the shared PostgresDb (not Agno's default "ai").
    assert vector_db.schema == "public"
    assert vector_db.search_type is SearchType.vector
    # Dimensionality flows from the reused embedder, not a hardcoded value.
    assert vector_db.dimensions == 1024
    assert isinstance(vector_db.embedder, OpenAIEmbedder)
    assert vector_db.embedder.id == "Qwen/Qwen3-Embedding-0.6B"
    # No ANN index (exact KNN).
    assert vector_db.vector_index is None
    # Caller-supplied identity flows to Knowledge.
    assert captured["name"] == "Widget Knowledge"
    assert captured["description"] == "Test widgets."
    # The contents_db is the shared PostgresDb handle.
    assert isinstance(captured["contents_db"], PostgresDb)
    assert isinstance(result, _RecordingKnowledge)
