"""The Runtime's single shared relational database handle.

`PostgresDb` is the source of truth for *all* persistent relational state
(sessions, memory, profile, knowledge-content tracking, traces — see `Agents.md`).
It is **Runtime-wide and reused across agents**, not recipe-private.

In v0.3 this handle activates only one role: the knowledge ``contents_db`` — the
``agno_knowledge`` table that records what was ingested, which is what makes
ingestion idempotent (the re-run ``skipped`` count). The sessions / memory / profile
roles are the *same* handle gaining *more tables* later, deferred to the agent
release — not a different database.

Table names are left at Agno's defaults (all ``agno_*``). Idempotency is handled
inside Agno's ``contents_db`` and never references a table name from this code, so
overriding the name would only fragment the schema once the other roles activate.

The Postgres ``schema`` is pinned to ``public`` explicitly. Agno's library default
is ``ai`` — a meaningless namespace for a database dedicated to this Runtime, and one
that forces clients to juggle ``search_path``. ``PgVector`` (see ``knowledge.py``) is
pinned to the same ``public`` so both halves land in one namespace.
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
