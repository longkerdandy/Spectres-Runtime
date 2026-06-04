"""The ``Recipe`` aggregate of the recipe domain.

The normalized internal model that every recipe source produces. Composes
:class:`~spectres_runtime.recipe_agent.models.ingredient.Ingredient` and
:class:`~spectres_runtime.recipe_agent.models.provenance.RecipeProvenance`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from spectres_runtime.recipe_agent.models.ingredient import Ingredient
from spectres_runtime.recipe_agent.models.provenance import RecipeProvenance


class Recipe(BaseModel):
    """A normalized recipe — the internal representation all sources produce.

    Carries field shapes only: populating, normalizing, and enriching the data
    is the job of the source implementations and the ingestion pipeline, not of
    this model.
    """

    id: str  # stable unique identifier
    name: str  # canonical display name
    aliases: list[str] = Field(default_factory=list)  # other names for the dish
    description: str | None = None  # human-readable summary (Markdown)
    images: list[str] = Field(default_factory=list)  # runtime-resolvable refs (local path or served URL)
    category: list[str] = Field(default_factory=list)  # classification tags
    ingredients: list[Ingredient] = Field(default_factory=list)  # structured ingredient lines
    steps: str | None = None  # cooking instructions (Markdown, structure preserved)
    difficulty: int | None = None  # rating, 1 (easy) to 5 (hard)
    time: float | None = None  # total time in hours
    provenance: RecipeProvenance | None = None  # where the recipe came from
