"""PostgreSQL database adapter for Spectres Runtime."""

from agno.db.postgres import PostgresDb

from spectres.config import settings

_db: PostgresDb | None = None


def get_postgres_db() -> PostgresDb:
    """Return the process-wide Agno PostgreSQL adapter, creating it lazily.

    The single db handle also owns the single SQLAlchemy engine
    (``db.db_engine``, a public Agno attribute): Agno's own tables and the
    extensions' business tables share one connection pool. Agno builds the
    engine with ``pool_pre_ping=True`` (``agno.db.postgres._engine_options``),
    which recycles connections killed when the test database is dropped and
    recreated between integration tests.
    """
    global _db
    if _db is None:
        _db = PostgresDb(db_url=settings.database_url)
    return _db
