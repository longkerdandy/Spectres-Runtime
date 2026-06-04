"""Runtime data/persistence layer, shared across agents.

``storage/`` holds DB-related wiring only — the single shared ``PostgresDb``
(``build_db``) and the recipe ``Knowledge`` base (``build_knowledge``). Domain
logic (e.g. profile management) lives elsewhere, even though it later *uses* the
db. Grouping settled in plan v0.3 §4.
"""

from __future__ import annotations

from spectres_runtime.storage.db import KNOWLEDGE_CONTENTS_TABLE, build_db
from spectres_runtime.storage.knowledge import RECIPES_TABLE, build_knowledge

__all__ = [
    "KNOWLEDGE_CONTENTS_TABLE",
    "RECIPES_TABLE",
    "build_db",
    "build_knowledge",
]
