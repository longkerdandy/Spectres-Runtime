"""Recipe domain model.

The typed internal model every recipe source normalizes into. Split into modules
by sub-concept; the public surface is re-exported here so callers import from
``spectres_runtime.recipe_agent.models`` regardless of the internal layout.
"""

from __future__ import annotations

from spectres_runtime.recipe_agent.models.ingredient import (
    Ingredient,
    IngredientRole,
)
from spectres_runtime.recipe_agent.models.provenance import RecipeProvenance
from spectres_runtime.recipe_agent.models.recipe import Recipe

__all__ = [
    "Ingredient",
    "IngredientRole",
    "Recipe",
    "RecipeProvenance",
]
