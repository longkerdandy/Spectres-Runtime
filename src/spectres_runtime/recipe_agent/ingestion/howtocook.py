"""HowToCook ingester (``Anduin2017/HowToCook``).

Composes each :class:`Recipe` from two committed, offline artifacts under a
vendored snapshot root (design §6):

- ``catalog/recipes.jsonl`` — the structured catalog (one recipe per line):
  ``name``, ``description``, ``images``, ``difficulty`` and cleaned, curated
  ``ingredients``. Built offline by ``scripts/howtocook_extract.py`` plus a
  one-time review pass; never parsed live.
- ``dishes/<ref>`` — the faithful Markdown snapshot, read for the recipe's full
  body (``content``): the entire ``.md`` with the project's contributor footer
  stripped, structure otherwise preserved. This body is what gets embedded.

Online origin, served locally: no network, DB, or LLM at ingest time.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from spectres_runtime.recipe_agent.ingestion.ingester import RecipeIngester
from spectres_runtime.recipe_agent.models import Ingredient, Recipe
from spectres_runtime.recipe_agent.models.provenance import RecipeProvenance

# Repo-root-relative location of the vendored snapshot, used as the default
# root. ``parents[4]`` walks ingestion -> recipe_agent -> spectres_runtime ->
# src -> repo root.
_DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "datasets" / "howtocook"

# Distinctive phrase of HowToCook's trailing contributor footer ("...请提出 Issue
# 或 Pull request 。"), present in every dish. It addresses contributors, not
# cooks — zero retrieval signal and identical across the corpus, so it is dropped
# from the embedded body. Matched as a substring to catch its standalone,
# image-trailing, and list-item ("- ...") variants alike.
_FOOTER_MARKER = "请提出 Issue 或 Pull request"


def _content_from_markdown(text: str) -> str | None:
    """Return the dish's full Markdown body with the contributor footer removed.

    Keeps every line verbatim (structure preserved) except those carrying the
    footer marker. ``None`` when nothing remains.
    """
    body = "\n".join(line for line in text.splitlines() if _FOOTER_MARKER not in line)
    return body.strip() or None


class HowToCookIngester(RecipeIngester):
    """Ingests recipes from a vendored HowToCook snapshot — catalog + Markdown."""

    name: ClassVar[str] = "howtocook"

    def __init__(self, root: Path | None = None) -> None:
        """Bind the snapshot root (the ``datasets/howtocook`` directory).

        Defaults to the repo's vendored snapshot; tests inject a fixture root.
        """
        self._root = root if root is not None else _DEFAULT_ROOT
        self._catalog = self._root / "catalog" / "recipes.jsonl"
        self._dishes = self._root / "dishes"

    def ingest(self) -> Iterator[Recipe]:
        """Yield one :class:`Recipe` per catalog line, lazily.

        Structured fields come from the catalog entry; ``content`` is the matching
        snapshot ``.md`` (footer stripped); ``category`` is the leading ``ref`` segment.
        """
        with self._catalog.open(encoding="utf-8") as lines:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                yield self._compose(json.loads(line))

    def _compose(self, entry: dict[str, Any]) -> Recipe:
        """Build one :class:`Recipe` from a catalog ``entry`` plus its snapshot ``.md``.

        Structured fields come from the entry; ``content`` is the matching ``.md``'s full
        body with the contributor footer stripped (``None`` when the file is missing);
        ``id`` is the source-namespaced ``ref`` slug; ``category`` is the leading ``ref``
        segment; the raw ``ref`` is kept in ``provenance``.
        """
        ref: str = entry["ref"]
        md_path = self._dishes / ref
        content = _content_from_markdown(md_path.read_text(encoding="utf-8")) if md_path.is_file() else None
        return Recipe(
            id=f"{self.name}/{ref.removesuffix('.md')}",
            name=entry["name"],
            description=entry.get("description"),
            images=list(entry.get("images", [])),
            category=[ref.split("/", 1)[0]],
            ingredients=[Ingredient(name=i["name"], optional=i.get("optional", False)) for i in entry["ingredients"]],
            content=content,
            difficulty=entry.get("difficulty"),
            provenance=RecipeProvenance(source=self.name, ref=ref),
        )
