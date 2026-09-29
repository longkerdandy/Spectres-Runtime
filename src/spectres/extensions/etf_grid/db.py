"""Session factory for the ETF grid extension's PostgreSQL tables.

Bound lazily to the process-wide Agno db handle's engine
(``get_postgres_db().db_engine``) so the whole Runtime shares one
connection pool; this module only caches the session factory.
"""

from sqlalchemy.orm import Session, sessionmaker

from spectres.db.postgres import get_postgres_db

_session_factory: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory bound to the Runtime's engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_postgres_db().db_engine)
    return _session_factory
