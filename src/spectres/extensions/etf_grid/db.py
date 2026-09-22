"""Engine and session factory for the ETF grid extension's PostgreSQL tables."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from spectres.config import settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the shared SQLAlchemy engine, creating it lazily on first use.

    ``pool_pre_ping`` checks out connections with a cheap ping first, so
    pooled connections killed externally (DB restart, or the integration
    test fixture terminating backends before recreating the test database)
    are transparently recycled instead of failing the next query.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory bound to the extension engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory
