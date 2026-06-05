"""HowToCook ingester (``Anduin2017/HowToCook``).

Composes each :class:`Recipe` from two committed, offline artifacts under a
vendored snapshot root (design §6):

- ``ai-cleaned/recipes.jsonl`` — the structured catalog (one recipe per line):
  ``name``, ``description``, ``images``, ``difficulty`` and cleaned, curated
  ``ingredients``. Built offline by ``scripts/howtocook_clean.py`` plus a
  one-time review pass; never parsed live.
- ``dishes/<ref>`` — the faithful Markdown snapshot, read only for the cooking
  ``steps`` (the ``## 操作`` section onward, structure preserved).

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

_STEPS_HEADING = "## 操作"


def _steps_from_markdown(text: str) -> str | None:
    """Return the cooking section — the ``## 操作`` heading onward — verbatim.

    Lossless-leaning: everything from the heading to end of file is kept (trailing
    sections included), structure preserved. ``None`` when the heading is absent.
    """
    for idx, line in enumerate(text.splitlines()):
        if line.strip() == _STEPS_HEADING:
            steps = "\n".join(text.splitlines()[idx:]).strip()
            return steps or None
    return None


class HowToCookIngester(RecipeIngester):
    """Ingests recipes from a vendored HowToCook snapshot — catalog + Markdown."""

    name: ClassVar[str] = "howtocook"

    def __init__(self, root: Path | None = None) -> None:
        """Bind the snapshot root (the ``datasets/howtocook`` directory).

        Defaults to the repo's vendored snapshot; tests inject a fixture root.
        """
        self._root = root if root is not None else _DEFAULT_ROOT
        self._catalog = self._root / "ai-cleaned" / "recipes.jsonl"
        self._dishes = self._root / "dishes"

    def ingest(self) -> Iterator[Recipe]:
        """Yield one :class:`Recipe` per catalog line, lazily.

        Structured fields come from the catalog entry; ``steps`` is read from the
        matching snapshot ``.md``; ``category`` is the leading ``ref`` path segment.
        """
        with self._catalog.open(encoding="utf-8") as lines:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                yield self._compose(json.loads(line))

    def _compose(self, entry: dict[str, Any]) -> Recipe:
        ref: str = entry["ref"]
        md_path = self._dishes / ref
        steps = _steps_from_markdown(md_path.read_text(encoding="utf-8")) if md_path.is_file() else None
        return Recipe(
            id=f"{self.name}/{ref.removesuffix('.md')}",
            name=entry["name"],
            description=entry.get("description"),
            images=list(entry.get("images", [])),
            category=[ref.split("/", 1)[0]],
            ingredients=[Ingredient(name=i["name"], optional=i.get("optional", False)) for i in entry["ingredients"]],
            steps=steps,
            difficulty=entry.get("difficulty"),
            provenance=RecipeProvenance(source=self.name, ref=ref),
        )
