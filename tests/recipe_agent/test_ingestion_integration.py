"""Integration probe for Agno's write semantics that the §7 sink relies on.

Opt-in: marked ``integration`` (excluded from the default gate) and skipped unless
the runtime config is complete and Postgres is reachable. Pins the property the §7
full-update depends on by exercising *how* ``Knowledge.insert`` behaves when the
same ``name`` is written twice with a **different body**: does it replace the row
in place, leave it stale, or duplicate?

The sink's full-update contract — "re-embed every recipe each run, no duplicate
vectors" — depends on a stable ``name`` upserting **in place**, so that answer is
asserted here against live pgvector. One real embedder call per insert; bodies are
kept short (single chunk) to keep the row bookkeeping 1:1.

Run with a populated ``.env`` (or env vars) and Postgres up:
``uv run pytest -m integration``
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from spectres_runtime.config import Settings, get_settings
from spectres_runtime.storage.knowledge import RECIPES_TABLE, build_knowledge

pytestmark = pytest.mark.integration

# A namespaced, obviously-synthetic name so the probe never collides with real
# recipes and is trivial to clean up by prefix.
_PROBE_NAME = "__probe__/howtocook/replace-semantics"
_SCHEMA = "public"  # matches build_knowledge's pinned namespace


def _settings_or_skip() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        pytest.skip("Runtime config incomplete (no DB/key via env / .env) — live check skipped.")


def _rows_for_name(database_url: str, name: str) -> list[dict[str, str]]:
    """Every pgvector row carrying ``name``, with its content-identity columns."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT content_id, content_hash, content FROM {_SCHEMA}.{RECIPES_TABLE} WHERE name = :name"),
                {"name": name},
            )
            return [dict(row._mapping) for row in result]
    finally:
        engine.dispose()


def _delete_probe_rows(database_url: str, name: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {_SCHEMA}.{RECIPES_TABLE} WHERE name = :name"),
                {"name": name},
            )
    finally:
        engine.dispose()


def test_same_name_changed_body_replaces_in_place() -> None:
    """A second write of the same ``name`` with a new body must not leave the old
    body behind nor fork a second logical content — the sink's in-place re-embed
    contract. Asserts: exactly one ``content_id`` for the name, and the stored body
    reflects the *latest* write (no stale text, no duplicate vector)."""
    settings = _settings_or_skip()
    knowledge = build_knowledge(settings)
    if not knowledge.vector_db.exists():  # type: ignore[union-attr]
        knowledge.vector_db.create()  # type: ignore[union-attr]

    _delete_probe_rows(settings.database_url, _PROBE_NAME)
    try:
        body_a = "蒸蛋：鸡蛋两个，加温水搅匀，上锅蒸八分钟。"
        body_b = "蒸蛋：鸡蛋三个，加牛奶搅匀，上锅蒸十分钟，出锅淋酱油。"

        knowledge.insert(name=_PROBE_NAME, text_content=body_a, upsert=True)
        first = _rows_for_name(settings.database_url, _PROBE_NAME)
        assert first, "first insert produced no rows"
        assert all(body_a[:6] in (r["content"] or "") for r in first), "body A not stored"

        knowledge.insert(name=_PROBE_NAME, text_content=body_b, upsert=True)
        second = _rows_for_name(settings.database_url, _PROBE_NAME)

        content_ids = {r["content_id"] for r in second}
        assert len(content_ids) == 1, (
            f"changed body forked into {len(content_ids)} logical contents "
            f"(content_ids={content_ids}) — duplicate vectors, not an in-place replace"
        )
        joined = " ".join(r["content"] or "" for r in second)
        assert "牛奶" in joined, "latest body B was not persisted (stale content kept)"
        assert "温水" not in joined, "stale body A still present alongside B (not replaced)"
    finally:
        _delete_probe_rows(settings.database_url, _PROBE_NAME)
