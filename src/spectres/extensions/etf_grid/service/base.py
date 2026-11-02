"""Shared base for the ETF grid services."""

from sqlalchemy.orm import Session, sessionmaker

from spectres.extensions.etf_grid.db import get_session_factory


def _require_user_id(user_id: str) -> str:
    if not user_id:
        raise ValueError("user_id is required")
    return user_id


class _SessionBound:
    """Base for the etf_grid services: bind to the extension's shared session factory by default."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        """Create the service; defaults to the extension's shared session factory."""
        self._session_factory = session_factory or get_session_factory()
