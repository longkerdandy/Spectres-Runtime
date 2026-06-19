"""Session management stub for Spectres Runtime."""

from agno.db.postgres import PostgresDb

from spectres.db.postgres import get_postgres_db


class SessionManager:
    """Manages persistent agent sessions backed by PostgreSQL."""

    def __init__(self, db: PostgresDb) -> None:
        """Initialize the session manager.

        Args:
            db: Configured PostgreSQL database adapter.
        """
        self.db = db

    @classmethod
    def from_settings(cls) -> "SessionManager":
        """Create a SessionManager from application settings."""
        return cls(db=get_postgres_db())
