"""Recipe agent tools — tool-driven precise retrieval.

Provides two tools:
* ``search_recipes`` — catalog search returning lightweight metadata
* ``get_recipe_detail`` — full recipe retrieval by stable ID
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from agno.tools import tool

from spectres_runtime.config import Settings

# Category mapping: English key (stored in DB) → Chinese label (for LLM reference).
_CATEGORY_MAP = {
    "aquatic": "水产",
    "breakfast": "早餐",
    "condiment": "调味",
    "dessert": "甜品",
    "drink": "饮品",
    "meat_dish": "肉菜",
    "semi-finished": "半成品",
    "soup": "汤",
    "staple": "主食",
    "vegetable_dish": "素菜",
}

_VALID_CATEGORIES = frozenset(_CATEGORY_MAP.keys())  # Valid category keys for the search tool.


def _build_search_sql(
    embedding: list[float],  # Query embedding vector for semantic search.
    category: str | None,  # Optional category filter (exact match).
    must_include: list[str] | None,  # Ingredients that must all be present (AND logic).
    must_exclude: list[str] | None,  # Ingredients where any match excludes the recipe (OR logic).
    limit: int,  # Maximum number of results to return.
) -> tuple[str, list[Any]]:
    """Build the parameterized SQL for recipe search.

    Uses PgVector cosine distance for semantic ranking and JSONB path queries
    for ingredient filtering (exact match, not substring).
    """
    sql = """
    SELECT
        name AS recipe_id,
        meta_data->>'name' AS name,
        meta_data->'category' AS category,
        meta_data->>'difficulty' AS difficulty,
        meta_data->>'description' AS description,
        meta_data->'ingredients' AS ingredients,
        embedding <=> %s::vector AS distance
    FROM recipes
    WHERE 1=1
      AND NOT meta_data->'category' @> '["template"]'::jsonb
    """
    params: list[Any] = [embedding]  # First param is the embedding vector.

    if category:
        sql += " AND meta_data->'category' @> %s::jsonb"
        params.append(json.dumps([category]))

    if must_include:
        for ing in must_include:
            sql += " AND jsonb_path_exists(meta_data, %s::jsonpath)"
            params.append(f'$.ingredients[*].name ? (@ == "{ing}")')

    if must_exclude:
        for ing in must_exclude:
            sql += " AND NOT jsonb_path_exists(meta_data, %s::jsonpath)"
            params.append(f'$.ingredients[*].name ? (@ == "{ing}")')

    sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
    params.extend([embedding, limit])

    return sql, params


def build_get_recipe_detail_tool(settings: Settings) -> Any:
    """Build the ``get_recipe_detail`` tool with access to settings."""
    db_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @tool(name="get_recipe_detail")
    def get_recipe_detail(recipe_id: str) -> str:
        """Retrieve the full recipe with ingredients, quantities, and steps.

        Use this tool ONLY when the user explicitly asks how to make a dish or
        wants detailed ingredients and cooking steps. For recommendations,
        menu planning, or general questions, use ``search_recipes`` instead.

        The ``recipe_id`` must come from a previous ``search_recipes`` result.
        Returns the complete recipe in Markdown, including ingredients and
        numbered steps.

        Args:
            recipe_id: Stable ID from ``search_recipes`` (e.g.
                "howtocook/soup/tomato_egg").

        Returns:
            Complete Markdown recipe, or a clear "not found" message if the ID
            does not exist.
        """
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT content FROM recipes WHERE name = %s LIMIT 1", (recipe_id,))
            row = cur.fetchone()

        if not row or not row[0]:
            return f"Recipe '{recipe_id}' not found."

        content = str(row[0])
        max_len = 3000
        if len(content) > max_len:
            content = content[:max_len] + "\n\n... (truncated)"
        return content

    return get_recipe_detail


def build_search_recipes_tool(
    settings: Settings,  # Runtime configuration (DB URL, embedder settings).
    *,
    embedder: Any | None = None,  # Optional embedder override (for testing).
) -> Any:
    """Build the ``search_recipes`` tool with access to settings."""
    embedder = embedder or settings.build_embedder()
    db_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @tool(name="search_recipes")
    def search_recipes(
        query: str,  # Natural language description of what the user wants.
        category: str | None = None,  # Optional category filter (e.g. "soup", "meat_dish").
        must_include: list[str] | None = None,  # Ingredients that must all be present.
        must_exclude: list[str] | None = None,  # Ingredients where any match excludes.
        limit: int = 4,  # Maximum results (clamped to 1-8).
    ) -> str:
        """Search the recipe catalog by semantic meaning.

        Use this tool to discover candidate dishes when the user asks for
        recommendations, meal planning, or a menu. It returns lightweight
        metadata only — no cooking steps. To get full instructions for a dish,
        call ``get_recipe_detail`` with the ``recipe_id`` from a result.

        Args:
            query: Natural language description of what you want (e.g. "light soup",
                   "savory meat dish", "quick veggie").
            category: Filter by category. Valid: soup, meat_dish, vegetable_dish,
                      staple, breakfast, dessert, condiment, drink, aquatic.
            must_include: Ingredients that MUST be present (exact match, AND logic).
            must_exclude: Ingredients that MUST NOT be present (exact match, excludes if any match).
            limit: Maximum results (default 4, max 8).
        """
        # Clamp limit to reasonable range.
        limit = max(1, min(limit, 8))

        # Validate category if provided.
        if category and category not in _VALID_CATEGORIES:
            valid_cats = ", ".join(f"{en}({zh})" for en, zh in sorted(_CATEGORY_MAP.items()))
            return json.dumps(
                {"error": f"Invalid category '{category}'. Use English keys. Valid: {valid_cats}"},
                ensure_ascii=False,
            )

        embedding = embedder.get_embedding(query)
        sql, params = _build_search_sql(embedding, category, must_include, must_exclude, limit)

        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            raw_ingredients = row[5] or []
            ingredient_names = [i["name"] for i in raw_ingredients] if isinstance(raw_ingredients, list) else []
            results.append(
                {
                    "recipe_id": row[0],
                    "name": row[1],
                    "category": row[2] if isinstance(row[2], list) else [row[2]] if row[2] else [],
                    "difficulty": row[3],
                    "description": row[4] or "",
                    "ingredients": ingredient_names,
                }
            )

        return json.dumps(results, ensure_ascii=False)

    return search_recipes
