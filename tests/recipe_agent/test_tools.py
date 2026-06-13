"""Tests for recipe agent tools.

Hermetic — tests SQL generation directly and mocks the DB layer so no network or
real database is needed.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spectres_runtime.recipe_agent.tools import (
    _build_search_sql,
    build_get_recipe_detail_tool,
    build_search_recipes_tool,
)


class TestBuildSearchSql:
    """Tests for SQL generation logic."""

    def test_basic_structure(self) -> None:
        sql, params = _build_search_sql([0.1, 0.2], None, None, None, 4)
        assert "SELECT" in sql
        assert "FROM recipes" in sql
        assert "ORDER BY embedding" in sql
        assert "LIMIT %s" in sql
        assert params[-1] == 4

    def test_excludes_template(self) -> None:
        sql, _ = _build_search_sql([0.1], None, None, None, 4)
        assert "NOT meta_data->'category' @>" in sql
        assert "template" in sql

    def test_category_filter(self) -> None:
        sql, params = _build_search_sql([0.1], "soup", None, None, 4)
        assert "meta_data->'category' @> %s::jsonb" in sql
        assert params[1] == '["soup"]'

    def test_must_include_and_logic(self) -> None:
        sql, params = _build_search_sql([0.1], None, ["番茄", "鸡蛋"], None, 4)
        # Should have two jsonb_path_exists clauses.
        assert sql.count("jsonb_path_exists") == 2
        assert params[1] == '$.ingredients[*].name ? (@ == "番茄")'
        assert params[2] == '$.ingredients[*].name ? (@ == "鸡蛋")'

    def test_must_exclude_or_logic(self) -> None:
        sql, _params = _build_search_sql([0.1], None, None, ["辣椒", "花椒"], 4)
        # Should have two NOT jsonb_path_exists clauses.
        assert sql.count("NOT jsonb_path_exists") == 2

    def test_limit_clamping_in_sql(self) -> None:
        # The SQL generator itself does not clamp — that's the tool's job.
        _, params = _build_search_sql([0.1], None, None, None, 100)
        assert params[-1] == 100


class TestSearchRecipesTool:
    """Tests for the search_recipes tool end-to-end."""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        embedder = MagicMock()
        embedder.get_embedding.return_value = [0.1, 0.2, 0.3]
        return embedder

    @pytest.fixture
    def tool(self, mock_embedder: MagicMock) -> Any:
        # Build tool with mocked embedder injected directly.
        return build_search_recipes_tool(_mock_settings(), embedder=mock_embedder)

    def test_returns_lightweight_metadata(self, tool: Any) -> None:
        rows = [
            (
                "howtocook/soup/tomato_egg",
                "西红柿鸡蛋汤",
                ["soup"],
                "2",
                "酸甜开胃...",
                [{"name": "西红柿", "optional": False}],
            )
        ]
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg.connect", return_value=conn):
            result = json.loads(tool.entrypoint("清淡的汤"))

        assert len(result) == 1
        assert result[0]["recipe_id"] == "howtocook/soup/tomato_egg"
        assert "content" not in result[0]

    def test_invalid_category_returns_error(self, tool: Any) -> None:
        result = json.loads(tool.entrypoint("汤", category="invalid"))
        assert "error" in result

    def test_limit_is_clamped(self, tool: Any) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg.connect", return_value=conn):
            tool.entrypoint("x", limit=0)
            assert cursor.execute.call_args[0][1][-1] == 1

            tool.entrypoint("x", limit=100)
            assert cursor.execute.call_args[0][1][-1] == 8


class TestGetRecipeDetailTool:
    """Tests for the get_recipe_detail tool end-to-end."""

    @pytest.fixture
    def tool(self) -> Any:
        return build_get_recipe_detail_tool(_mock_settings())

    def test_returns_full_recipe_content(self, tool: Any) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = ("# 西红柿鸡蛋汤\n\n## 原料\n- 西红柿\n\n## 步骤\n1. 切块",)
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg.connect", return_value=conn):
            result = tool.entrypoint("howtocook/soup/tomato_egg")

        assert "西红柿鸡蛋汤" in result
        assert "# " in result

    def test_returns_not_found_for_missing_id(self, tool: Any) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg.connect", return_value=conn):
            result = tool.entrypoint("howtocook/missing/dish")

        assert "not found" in result.lower()

    def test_truncates_long_content(self, tool: Any) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = ("x" * 4000,)
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("psycopg.connect", return_value=conn):
            result = tool.entrypoint("howtocook/soup/long_recipe")

        assert "... (truncated)" in result
        assert len(result) <= 3100


def _mock_settings() -> Any:
    """Minimal settings double."""
    from pydantic import SecretStr

    from spectres_runtime.config import Settings
    from spectres_runtime.recipe_agent.config import RecipeAgentSettings

    return Settings(
        _env_file=None,
        database_url="postgresql://developer:devpass@localhost:5532/spectres_runtime",
        runtime_port=7777,
        spectres_web_origin="http://localhost:3000",
        embedder_model="test-model",
        embedder_base_url="https://test.example/v1",
        embedder_dimensions=3,
        embedder_api_key=SecretStr("sk-test"),
        recipe_agent=RecipeAgentSettings(
            _env_file=None,
            instructions="Test.",
            num_history_runs=3,
            chat_model="gpt-4",
            chat_base_url="https://test.example/v1",
            chat_api_key=SecretStr("sk-test"),
        ),
    )
