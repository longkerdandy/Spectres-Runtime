"""v0.4.1 Task #1: Data layer investigation script.

Runs diagnostic queries against the local Postgres + pgvector to verify:
1. The exact schema of the `recipes` table
2. The content storage layout (text_content column vs. agno_knowledge)
3. The JSONB metadata structure (category, ingredients, description)
4. Sample data for validation

Usage:
    python scripts/investigate_data_layer.py

Requires:
    DATABASE_URL environment variable or `.env` file in repo root.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on path so we can import spectres_runtime
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg

from spectres_runtime.config import get_settings


def main() -> int:
    settings = get_settings()
    # psycopg expects "postgresql://" not "postgresql+psycopg://"
    db_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    conn = psycopg.connect(db_url)
    cur = conn.cursor()

    print("=" * 70)
    print("Task #1: Data Layer Investigation")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. recipes table schema
    # ------------------------------------------------------------------
    print("\n## 1. recipes table schema (public schema)")
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'recipes' AND table_schema = 'public'
        ORDER BY ordinal_position
        """
    )
    rows = cur.fetchall()
    for col_name, data_type, nullable in rows:
        print(f"  {col_name}: {data_type} {'(nullable)' if nullable == 'YES' else '(not null)'}")

    # ------------------------------------------------------------------
    # 2. Total row count
    # ------------------------------------------------------------------
    print("\n## 2. Total recipes count")
    cur.execute("SELECT COUNT(*) FROM recipes")
    count = cur.fetchone()[0]
    print(f"  {count} recipes")

    # ------------------------------------------------------------------
    # 3. Sample row: text_content length and metadata structure
    # ------------------------------------------------------------------
    print("\n## 3. Sample row (first recipe)")
    cur.execute(
        """
        SELECT name, LENGTH(text_content), metadata
        FROM recipes
        ORDER BY name
        LIMIT 1
        """
    )
    name, content_len, metadata = cur.fetchone()
    print(f"  name (recipe_id): {name}")
    print(f"  text_content length: {content_len} chars")
    print(f"  metadata keys: {list(metadata.keys())}")
    print(f"  metadata pretty:\n{json.dumps(metadata, ensure_ascii=False, indent=4)}")

    # ------------------------------------------------------------------
    # 4. text_content preview (first 500 chars)
    # ------------------------------------------------------------------
    print("\n## 4. text_content preview (first 500 chars)")
    cur.execute("SELECT LEFT(text_content, 500) FROM recipes ORDER BY name LIMIT 1")
    preview = cur.fetchone()[0]
    print(preview)

    # ------------------------------------------------------------------
    # 5. Category distribution
    # ------------------------------------------------------------------
    print("\n## 5. Category distribution")
    cur.execute(
        """
        SELECT
            jsonb_array_elements_text(metadata->'category') AS cat,
            COUNT(*) AS cnt
        FROM recipes
        GROUP BY cat
        ORDER BY cnt DESC
        """
    )
    for cat, cnt in cur.fetchall():
        print(f"  {cat}: {cnt}")

    # ------------------------------------------------------------------
    # 6. Ingredient name samples (first 20 unique)
    # ------------------------------------------------------------------
    print("\n## 6. Sample ingredient names (first 20 unique)")
    cur.execute(
        """
        SELECT DISTINCT jsonb_array_elements(metadata->'ingredients')->>'name'
        FROM recipes
        LIMIT 20
        """
    )
    for (ing_name,) in cur.fetchall():
        print(f"  - {ing_name}")

    # ------------------------------------------------------------------
    # 7. agno_knowledge table check
    # ------------------------------------------------------------------
    print("\n## 7. agno_knowledge table check")
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'agno_knowledge' AND table_schema = 'public'
        """
    )
    has_agno_knowledge = cur.fetchone()[0]
    if has_agno_knowledge:
        cur.execute("SELECT COUNT(*) FROM agno_knowledge")
        agno_count = cur.fetchone()[0]
        print(f"  agno_knowledge table exists with {agno_count} rows")
    else:
        print("  agno_knowledge table NOT found in public schema")

    # ------------------------------------------------------------------
    # 8. Content length stats
    # ------------------------------------------------------------------
    print("\n## 8. text_content length statistics")
    cur.execute(
        """
        SELECT
            MIN(LENGTH(text_content)) AS min_len,
            MAX(LENGTH(text_content)) AS max_len,
            ROUND(AVG(LENGTH(text_content))) AS avg_len,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY LENGTH(text_content)) AS median_len
        FROM recipes
        """
    )
    min_len, max_len, avg_len, median_len = cur.fetchone()
    print(f"  min: {min_len}, max: {max_len}, avg: {avg_len}, median: {median_len}")

    # ------------------------------------------------------------------
    # 9. Description field presence in metadata
    # ------------------------------------------------------------------
    print("\n## 9. Description field in metadata")
    cur.execute(
        """
        SELECT COUNT(*) FILTER (WHERE metadata ? 'description') AS has_desc,
               COUNT(*) FILTER (WHERE NOT metadata ? 'description') AS no_desc
        FROM recipes
        """
    )
    has_desc, no_desc = cur.fetchone()
    print(f"  has description: {has_desc}, missing: {no_desc}")
    if has_desc > 0:
        cur.execute(
            """
            SELECT metadata->>'description'
            FROM recipes
            WHERE metadata ? 'description'
            LIMIT 3
            """
        )
        for (desc,) in cur.fetchall():
            print(f"    sample: {desc[:100]}...")

    conn.close()

    print("\n" + "=" * 70)
    print("Investigation complete.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
