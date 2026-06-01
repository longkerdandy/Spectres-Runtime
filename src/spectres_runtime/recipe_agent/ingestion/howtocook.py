"""HowToCook ingester (``Anduin2017/HowToCook``).

Reads a vendored, pinned snapshot of the repo's templated Markdown ``dishes/``
tree and normalizes each file into a recipe — online origin, served locally, no
network at ingest time. Stub — not yet implemented.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

from spectres_runtime.recipe_agent.ingestion.ingester import RecipeIngester
from spectres_runtime.recipe_agent.models import Recipe


class HowToCookIngester(RecipeIngester):
    """Ingests recipes from a vendored HowToCook snapshot. Stub — unimplemented."""

    name: ClassVar[str] = "howtocook"

    def ingest(self) -> Iterator[Recipe]:
        raise NotImplementedError("HowToCook ingestion is not implemented.")
