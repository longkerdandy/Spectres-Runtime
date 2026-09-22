"""SQLAlchemy models for the ETF grid extension."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from spectres.extensions.etf_grid.types import Side

_SIDE_CHECK = ", ".join(f"'{side.value}'" for side in Side)


class EtfGridBase(DeclarativeBase):
    """Declarative base shared by all ETF grid extension tables."""


class EtfGridTrade(EtfGridBase):
    """One executed trade in the append-only ETF grid trades ledger.

    Invariants: ``side`` is ``buy`` or ``sell`` (an opening-position backfill
    is recorded as a plain ``buy`` — it replays identically); ``source`` is
    ``manual`` or ``agent``; the three amount columns are computed at entry
    from price x quantity and the per-trade commission rate.
    """

    __tablename__ = "etf_grid_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str] = mapped_column(String(6), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    commission: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"side IN ({_SIDE_CHECK})", name="ck_etf_grid_trades_side"),
        Index("ix_etf_grid_trades_symbol_trade_date", "symbol", "trade_date"),
    )
