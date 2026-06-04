"""The Runtime's single shared relational database handle.

`PostgresDb` is the source of truth for *all* persistent relational state
(sessions, memory, profile, knowledge-content tracking, traces — see `Agents.md`).
It is **Runtime-wide and reused across agents**, not recipe-private.

In v0.3 this handle activates only one role: the knowledge ``contents_db`` — the
``knowledge_contents`` table that records what was ingested, which is what makes
ingestion idempotent (the re-run ``skipped`` count). The sessions / memory / profile
roles are the *same* handle gaining *more tables* later, deferred to the agent
release — not a different database.
"""

from __future__ import annotations

from agno.db.postgres import PostgresDb

from spectres_runtime.config import Settings

# The knowledge content-tracking table (the ``contents_db`` role). Named explicitly
# so the ingestion idempotency path (plan §7) refers to a stable table.
KNOWLEDGE_CONTENTS_TABLE = "knowledge_contents"


def build_db(settings: Settings) -> PostgresDb:
    """Construct the shared ``PostgresDb`` from settings.

    Offline: only configures the SQLAlchemy engine; no connection is opened until a
    table is actually read or written.
    """
    return PostgresDb(db_url=settings.database_url, knowledge_table=KNOWLEDGE_CONTENTS_TABLE)
