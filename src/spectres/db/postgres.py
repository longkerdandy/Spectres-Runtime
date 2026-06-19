"""PostgreSQL database adapter for Spectres Runtime."""

from agno.db.postgres import PostgresDb

from spectres.config import settings


def get_postgres_db() -> PostgresDb:
    """Return a configured Agno PostgreSQL database adapter."""
    return PostgresDb(
        db_url=settings.database_url,
        session_table="spectres_sessions",
    )
