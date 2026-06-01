"""Provenance sub-model of the recipe domain.

Records where a recipe came from. Named ``provenance`` rather than ``source`` to
keep it distinct from the sibling ``ingestion`` package — the fetching layer;
this records the origin of an already-normalized recipe.
"""

from __future__ import annotations

from pydantic import BaseModel


class RecipeProvenance(BaseModel):
    """Where a recipe came from: its originating source and origin ref."""

    source: str  # name of the source the recipe was normalized from
    ref: str | None = None  # original id or URL within that source, when known
