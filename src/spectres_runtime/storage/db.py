"""The Runtime's single shared relational database handle.

``PostgresDb`` is the source of truth for all persistent relational state
(sessions, memory, profile, knowledge-content tracking, traces) — Runtime-wide and
reused across agents, not private to any one.

Currently it activates only the knowledge ``contents_db`` role: the
``agno_knowledge`` table tracking what was ingested, which is what makes ingestion
idempotent. The other roles are the same handle gaining more tables later, not a
different database.

Table names are left at Agno's defaults (``agno_*``); idempotency lives inside
Agno's ``contents_db`` and never references a table name from this code. The
Postgres ``schema`` is pinned to ``public`` (Agno's default is ``ai``); ``PgVector``
in ``knowledge.py`` is pinned to the same ``public`` so both halves share one
namespace.
"""

from __future__ import annotations

from agno.db.postgres import PostgresDb

from spectres_runtime.config import Settings


def build_db(settings: Settings) -> PostgresDb:
    """Construct the shared ``PostgresDb`` from settings.

    Offline: only configures the SQLAlchemy engine; no connection is opened until a
    table is actually read or written.
    """
    return PostgresDb(db_url=settings.database_url, db_schema="public")
