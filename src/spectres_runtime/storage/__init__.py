"""Runtime data/persistence layer, shared across agents.

``storage/`` holds DB-related wiring only — the single shared ``PostgresDb``
(``build_db``) and the generic ``Knowledge`` factory (``build_knowledge``).
Domain-specific knowledge identity (table names, display names) lives in the
owning agent's package (e.g. ``recipe_agent.knowledge``), not here.
"""

from __future__ import annotations

from spectres_runtime.storage.db import build_db
from spectres_runtime.storage.knowledge import build_knowledge

__all__ = [
    "build_db",
    "build_knowledge",
]
