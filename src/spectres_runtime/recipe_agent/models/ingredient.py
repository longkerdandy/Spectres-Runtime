"""Ingredient sub-model of the recipe domain.

Defines the structured ingredient line.
"""

from __future__ import annotations

from pydantic import BaseModel


class Ingredient(BaseModel):
    """A single structured ingredient line."""

    name: str  # ingredient name
    optional: bool = False  # True if the cook may leave it out
