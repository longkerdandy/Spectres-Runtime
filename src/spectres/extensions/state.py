"""Persistent global activation state for built-in extensions."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from agno.db.postgres import PostgresDb
from sqlalchemy import Boolean, DateTime, String, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger(__name__)


class ExtensionStateBase(DeclarativeBase):
    """Declarative base for Runtime-owned extension state."""


class RuntimeExtensionState(ExtensionStateBase):
    """Global administrator-controlled activation state for one extension."""

    __tablename__ = "runtime_extension_states"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


@dataclass(frozen=True)
class ExtensionState:
    """Persistent activation state of one currently discovered extension."""

    id: str
    enabled: bool
    updated_at: datetime


class ExtensionStateService:
    """Persist and evaluate activation for a fixed set of discovered extensions."""

    def __init__(
        self,
        db: PostgresDb,
        extension_names: Sequence[str],
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """Bind the discovered ids to the shared database engine."""
        self._extension_names = tuple(extension_names)
        self._session_factory = session_factory or sessionmaker(bind=db.db_engine)

    def initialize(self) -> None:
        """Create the state table and add newly discovered extensions."""
        if not self._extension_names:
            return
        ExtensionStateBase.metadata.create_all(self._session_factory.kw["bind"])
        stmt = pg_insert(RuntimeExtensionState).values([{"name": name, "enabled": True} for name in self._extension_names])
        stmt = stmt.on_conflict_do_nothing(index_elements=["name"])
        with self._session_factory() as session, session.begin():
            session.execute(stmt)

    def list_states(self) -> list[ExtensionState]:
        """Return state for currently discovered extensions in discovery order."""
        if not self._extension_names:
            return []
        with self._session_factory() as session:
            rows = session.scalars(select(RuntimeExtensionState).where(RuntimeExtensionState.name.in_(self._extension_names)))
            by_name = {row.name: row for row in rows}
        return [ExtensionState(id=name, enabled=by_name[name].enabled, updated_at=by_name[name].updated_at) for name in self._extension_names if name in by_name]

    def is_enabled(self, name: str) -> bool:
        """Return whether a known, initialized extension is enabled."""
        if name not in self._extension_names:
            return False
        with self._session_factory() as session:
            row = session.get(RuntimeExtensionState, name)
            return row is not None and row.enabled

    def set_enabled(self, name: str, *, enabled: bool, updated_by: str) -> ExtensionState:
        """Set state for a currently discovered extension and audit the change."""
        if name not in self._extension_names:
            raise KeyError(name)
        with self._session_factory() as session, session.begin():
            row = session.get(RuntimeExtensionState, name)
            if row is None:
                raise KeyError(name)
            previous = row.enabled
            row.enabled = enabled
            row.updated_by = updated_by
            row.updated_at = func.now()
            session.flush()
            state = ExtensionState(id=row.name, enabled=row.enabled, updated_at=row.updated_at)
        logger.info(
            "extension activation updated",
            extra={
                "event": "extension_activation_updated",
                "extension_name": name,
                "updated_by": updated_by,
                "previous_enabled": previous,
                "enabled": enabled,
            },
        )
        return state
