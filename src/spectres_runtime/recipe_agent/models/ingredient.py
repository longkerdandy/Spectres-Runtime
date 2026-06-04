"""Ingredient sub-model of the recipe domain.

Defines the structured ingredient line.
"""

from __future__ import annotations

from pydantic import BaseModel


class Ingredient(BaseModel):
    """A single structured ingredient line."""

    name: str  # ingredient name
    quantity: str | None = None  # raw amount, verbatim (e.g. "115", "10-15"); None if unstated
    unit: str | None = None  # unit of measure (e.g. "g", "ml"); None if unstated
    optional: bool = False  # True if the cook may leave it out
