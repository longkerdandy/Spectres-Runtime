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

_VALID_CATEGORIES = frozenset(_CATEGORY_MAP.keys())


def _build_search_sql(
    embedding: list[float],
    category: str | None,
    must_include: list[str] | None,
    must_exclude: list[str] | None,
    limit: int,
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
    params: list[Any] = [embedding]

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


def build_search_recipes_tool(settings: Settings, *, embedder: Any | None = None) -> Any:
    """Build the ``search_recipes`` tool with access to settings.

    Args:
        settings: Runtime configuration.
        embedder: Optional embedder override (for testing).
    """
    embedder = embedder or settings.build_embedder()
    db_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @tool(name="search_recipes")
    def search_recipes(
        query: str,
        category: str | None = None,
        must_include: list[str] | None = None,
        must_exclude: list[str] | None = None,
        limit: int = 4,
    ) -> str:
        """Search the recipe catalog by semantic meaning.

        Use this tool to find dishes matching a description. Returns lightweight
        metadata (name, description, ingredients) — no cooking steps.

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
