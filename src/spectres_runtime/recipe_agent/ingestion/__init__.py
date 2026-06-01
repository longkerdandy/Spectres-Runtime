"""Ingestion layer — origin-specific adapters that materialize recipes.

Each :class:`RecipeIngester` reaches one origin and yields normalized recipes;
:class:`RecipeSink` is the shared write endpoint that persists them into the
local store. New ingesters join ``howtocook`` as siblings here.
"""

from __future__ import annotations

from spectres_runtime.recipe_agent.ingestion.howtocook import HowToCookIngester
from spectres_runtime.recipe_agent.ingestion.ingester import RecipeIngester
from spectres_runtime.recipe_agent.ingestion.sink import RecipeSink, WriteResult

__all__ = ["HowToCookIngester", "RecipeIngester", "RecipeSink", "WriteResult"]
