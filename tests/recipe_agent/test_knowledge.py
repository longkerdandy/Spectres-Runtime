"""Unit tests for ``spectres_runtime.recipe_agent.knowledge`` — pure, no DB.

Asserts the recipe-private identity (the ``recipes`` table, the AgentOS-facing
name) is wired onto the generic ``build_knowledge`` mechanism. ``Knowledge`` is
patched with a recorder so nothing connects to a database.
"""

from __future__ import annotations

import pytest
from agno.vectordb.pgvector import PgVector, SearchType

from spectres_runtime.recipe_agent.knowledge import RECIPES_TABLE, build_recipe_knowledge
from spectres_runtime.storage import knowledge as knowledge_module
from tests.conftest import make_settings

_DB_URL = "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime"


def test_recipes_table_constant() -> None:
    assert RECIPES_TABLE == "recipes"


def test_build_recipe_knowledge_wires_recipe_identity(monkeypatch: pytest.MonkeyPatch) -> None:
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
            captured["name"] = name
            captured["description"] = description

    monkeypatch.setattr(knowledge_module, "Knowledge", _RecordingKnowledge)
    build_recipe_knowledge(make_settings(database_url=_DB_URL))

    vector_db = captured["vector_db"]
    assert isinstance(vector_db, PgVector)
    # The recipe table contract and vector-only search are pinned here, not in storage/.
    assert vector_db.table_name == RECIPES_TABLE
    assert vector_db.search_type is SearchType.vector
    # The AgentOS-facing identity is the recipe domain's, supplied by this wrapper.
    assert captured["name"] == "Recipe Knowledge"
    assert captured["description"] == "Cookable recipes with ingredients and steps."
