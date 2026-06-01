"""The ``RecipeIngester`` interface — the ingestion-time boundary.

An ingester reaches one origin, owns its transport (local snapshot, REST API,
the model itself), and yields normalized recipes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar

from spectres_runtime.recipe_agent.models import Recipe


class RecipeIngester(ABC):
    """Yields normalized recipes from a single origin. One implementation per origin."""

    name: ClassVar[str]  # stable source name, recorded as ``provenance.source``

    @abstractmethod
    def ingest(self) -> Iterator[Recipe]:
        """Yield every recipe this origin provides, normalized.

        Streamed, not listed, so a large origin need not be held in memory.
        """
        raise NotImplementedError
