"""Ingredient sub-model of the recipe domain.

Defines the structured ingredient line and the role it plays in a recipe.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class IngredientRole(StrEnum):
    """The role an ingredient plays in a recipe.

    The split is what makes portion-scaling and filtering possible. The role is
    assigned during normalization — an ingredient line need not state it
    explicitly, so it defaults to ``main``.
    """

    MAIN = "main"  # primary ingredient
    SUPPORTING = "supporting"  # secondary ingredient
    SEASONING = "seasoning"  # condiment or spice


class Ingredient(BaseModel):
    """A single structured ingredient line."""

    name: str  # ingredient name
    quantity: str | None = None  # raw amount, verbatim (e.g. "115", "10-15"); None if unstated
    unit: str | None = None  # unit of measure (e.g. "g", "ml"); None if unstated
    role: IngredientRole = IngredientRole.MAIN  # role in the recipe
    optional: bool = False  # True if the cook may leave it out
