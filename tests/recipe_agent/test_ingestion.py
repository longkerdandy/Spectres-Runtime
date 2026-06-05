"""Ingestion layer — ingester behavior and sink stub assertions.

The HowToCook ingester composes typed recipes from committed offline artifacts —
no network, DB, or LLM. A small synthetic snapshot exercises field mapping; the
vendored snapshot is smoke-tested for shape. The sink stay a stub here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spectres_runtime.recipe_agent.ingestion import (
    HowToCookIngester,
    RecipeIngester,
    RecipeSink,
    WriteResult,
)
from spectres_runtime.recipe_agent.models import Recipe


def _write_snapshot(root: Path, entry: dict, markdown: str) -> None:
    """Lay out a minimal ``datasets/howtocook`` snapshot: one catalog line + .md."""
    catalog = root / "catalog" / "recipes.jsonl"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    md = root / "dishes" / entry["ref"]
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(markdown, encoding="utf-8")


def test_howtocook_is_a_recipe_ingester() -> None:
    assert issubclass(HowToCookIngester, RecipeIngester)
    assert HowToCookIngester.name == "howtocook"


def test_ingest_composes_typed_recipe_from_artifacts(tmp_path: Path) -> None:
    entry = {
        "ref": "aquatic/示例菜.md",
        "name": "示例菜",
        "description": "一段简介。",
        "images": ["aquatic/示例菜/成品.jpg"],
        "difficulty": 3,
        "ingredients": [
            {"name": "青蟹", "optional": False},
            {"name": "香菜", "optional": True},
        ],
    }
    markdown = (
        "# 示例菜的做法\n\n一段简介。\n\n## 必备原料和工具\n\n- 青蟹\n\n"
        "## 操作\n\n- 第一步\n- 第二步\n\n## 附加内容\n\n- 参考链接\n"
    )
    _write_snapshot(tmp_path, entry, markdown)

    recipes = list(HowToCookIngester(root=tmp_path).ingest())

    assert len(recipes) == 1
    recipe = recipes[0]
    assert isinstance(recipe, Recipe)
    assert recipe.id == "howtocook/aquatic/示例菜"
    assert recipe.name == "示例菜"
    assert recipe.description == "一段简介。"
    assert recipe.images == ["aquatic/示例菜/成品.jpg"]
    assert recipe.difficulty == 3
    assert recipe.category == ["aquatic"]
    assert [(i.name, i.optional) for i in recipe.ingredients] == [("青蟹", False), ("香菜", True)]
    assert recipe.provenance is not None
    assert (recipe.provenance.source, recipe.provenance.ref) == ("howtocook", "aquatic/示例菜.md")


def test_ingest_content_is_full_markdown_without_footer(tmp_path: Path) -> None:
    entry = {"ref": "staple/面.md", "name": "面", "images": [], "difficulty": 1, "ingredients": []}
    markdown = (
        "# 面的做法\n\n简介。\n\n## 必备原料和工具\n\n- 面条\n\n"
        "## 操作\n\n- 下锅\n\n## 附加内容\n\n- 链接\n\n"
        "如果您遵循本指南的制作流程而发现有问题或可以改进的流程，请提出 Issue 或 Pull request 。\n"
    )
    _write_snapshot(tmp_path, entry, markdown)

    recipe = next(HowToCookIngester(root=tmp_path).ingest())

    assert recipe.content is not None
    assert recipe.content.startswith("# 面的做法")  # full body from the title down
    assert "## 必备原料和工具" in recipe.content  # whole document kept, not just steps
    assert "## 操作" in recipe.content
    assert "## 附加内容" in recipe.content
    assert "请提出 Issue 或 Pull request" not in recipe.content  # contributor footer stripped


def test_ingest_content_none_when_markdown_missing(tmp_path: Path) -> None:
    # Catalog entry whose snapshot .md is absent — content cannot be read.
    catalog = tmp_path / "catalog" / "recipes.jsonl"
    catalog.parent.mkdir(parents=True)
    entry = {"ref": "drink/水.md", "name": "水", "images": [], "difficulty": 1, "ingredients": []}
    catalog.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    assert next(HowToCookIngester(root=tmp_path).ingest()).content is None


def test_ingest_skips_blank_catalog_lines(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog" / "recipes.jsonl"
    catalog.parent.mkdir(parents=True)
    entry = {"ref": "drink/茶.md", "name": "茶", "images": [], "difficulty": 1, "ingredients": []}
    catalog.write_text("\n" + json.dumps(entry, ensure_ascii=False) + "\n\n", encoding="utf-8")
    (tmp_path / "dishes" / "drink").mkdir(parents=True)
    (tmp_path / "dishes" / "drink" / "茶.md").write_text("# 茶\n\n## 操作\n\n- 泡\n", encoding="utf-8")

    assert [r.name for r in HowToCookIngester(root=tmp_path).ingest()] == ["茶"]


def test_ingest_over_vendored_snapshot_yields_valid_recipes() -> None:
    """Smoke-test the committed snapshot: every catalog line composes a Recipe."""
    recipes = list(HowToCookIngester().ingest())

    assert len(recipes) == 357
    assert all(isinstance(r, Recipe) for r in recipes)
    assert all(r.id and r.name for r in recipes)
    assert all(r.id.startswith("howtocook/") for r in recipes)
    assert all(r.provenance is not None and r.provenance.source == "howtocook" for r in recipes)
    assert all(r.category and r.category[0] for r in recipes)
    assert all(r.content for r in recipes)  # every dish has a Markdown body
    assert all("请提出 Issue 或 Pull request" not in r.content for r in recipes)  # footer stripped corpus-wide


def test_write_result_defaults_to_zero() -> None:
    result = WriteResult()
    assert (result.written, result.skipped, result.failed) == (0, 0, 0)


def test_recipe_sink_is_unimplemented() -> None:
    with pytest.raises(NotImplementedError):
        RecipeSink().write([])
