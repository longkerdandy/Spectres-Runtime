"""Private Mi Health account, QR-attempt, and legacy synchronization-run tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MiHealthBase(DeclarativeBase):
    """Declarative base for Mi Health Extension tables."""


class MiHealthBinding(MiHealthBase):
    """The current user's encrypted Xiaomi account and health session."""

    __tablename__ = "mi_health_bindings"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    region: Mapped[str] = mapped_column(String(8))
    device_id: Mapped[str] = mapped_column(String(64))
    xiaomi_user_id: Mapped[str] = mapped_column(Text)
    c_user_id: Mapped[str] = mapped_column(Text)
    pass_token: Mapped[str] = mapped_column(Text)
    service_token: Mapped[str] = mapped_column(Text)
    ssecurity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="authenticated")
    revision: Mapped[int] = mapped_column(default=0)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MiHealthQrAttempt(MiHealthBase):
    """One short-lived owner-scoped QR approval attempt."""

    __tablename__ = "mi_health_qr_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64))
    lp_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="waiting")
    server_timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_mi_health_qr_attempts_user_id", "user_id"),)


class MiHealthSyncRun(MiHealthBase):
    """Legacy run history retained only for upgrade compatibility and unbind cleanup."""

    __tablename__ = "mi_health_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    streams: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64))
    schedule_run_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_mi_health_sync_runs_user_created", "user_id", "created_at"),
        Index(
            "uq_mi_health_sync_runs_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
