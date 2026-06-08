"""Retrieval check — proves the ingested corpus is searchable, no LLM involved.

Opt-in: marked ``integration`` (excluded from the default gate) and skipped unless
the runtime config is complete **and** the store is populated. Read-only: issues one
Chinese-language query via Agno's native vector search (``Knowledge.search``) and
asserts the matching recipe lands in the top results — exercising the full
embed → store → embed-query → vector-search loop end to end. This is retrieval
grounding, **not** generation: no ``Agent.run``, no chat LLM.

The corpus is populated once by the ``recipe-ingest`` command and persists in the
Postgres volume across runs, so this check needs no re-ingest. When the store is
empty (fresh DB), the test skips with a hint rather than failing.

Populate once, then run:
``recipe-ingest`` (after ``docker compose -f docker/compose.yaml --env-file .env up -d``),
then ``uv run pytest -m integration``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from spectres_runtime.config import Settings
from spectres_runtime.recipe_agent.knowledge import RECIPES_TABLE, build_recipe_knowledge
from tests.conftest import settings_or_skip

pytestmark = pytest.mark.integration

# Matches the knowledge handle's pinned namespace.
_SCHEMA = "public"

# The canonical Chinese query and the real recipe it must surface. Verified against
# the live corpus: the dish lands inside the top results — but not at rank 1
# ("美式炒蛋" scores above it), so the bar is top-k membership, never the top slot.
_QUERY = "番茄炒蛋怎么做"
_EXPECTED_ID = "howtocook/vegetable_dish/西红柿炒鸡蛋"
_TOP_K = 5


def _require_populated_corpus(settings: Settings) -> None:
    """Skip unless the recipes table exists and holds rows.

    The check is read-only and depends on a prior ``recipe-ingest`` run; an empty or
    absent table means the operator has not populated the store yet, which is a skip
    (the precondition is unmet), not a failure.
    """
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT count(*) FROM {_SCHEMA}.{RECIPES_TABLE}")).scalar_one()
    except Exception:
        pytest.skip(f"{_SCHEMA}.{RECIPES_TABLE} unreachable — run `recipe-ingest` to populate the store first.")
    finally:
        engine.dispose()
    if not count:
        pytest.skip(f"{_SCHEMA}.{RECIPES_TABLE} empty — run `recipe-ingest` to populate the store first.")


def test_chinese_query_returns_relevant_recipe() -> None:
    """A Chinese query surfaces the matching recipe in the top results (no LLM).

    Asserts the full retrieval loop: the query is embedded by the *same* embedder that
    produced the stored vectors, vector-searched against the populated corpus, and the
    expected dish appears within the top ``_TOP_K`` — proving the data is retrievable.
    """
    settings = settings_or_skip()
    _require_populated_corpus(settings)
    knowledge = build_recipe_knowledge(settings)

    docs = knowledge.search(_QUERY, max_results=_TOP_K)
    names = [doc.name for doc in docs]

    assert names, f"search for {_QUERY!r} returned no documents"
    assert _EXPECTED_ID in names, f"expected {_EXPECTED_ID!r} within top-{_TOP_K} for {_QUERY!r}, got {names}"
