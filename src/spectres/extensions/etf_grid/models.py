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

    This table is the sole source of truth for positions and cost basis:
    ``core.ledger.replay_ledger`` derives holdings by replaying rows ordered
    by ``(symbol, trade_date, id)``.

    Invariants:

    - Append-only. Rows are never updated or deleted; a mistaken entry is
      corrected by inserting a reversal row.
    - The three amount fields are derived once at entry time (see
      ``service.record_trade``) and stored as facts::

          gross_amount = price * quantity
          commission   = round(gross_amount * commission_rate, 2)
          net_amount   = gross_amount + commission   (buy)
                         gross_amount - commission   (sell)

    - ``side`` is ``buy`` or ``sell``. An opening-position backfill is a
      plain ``buy`` — it replays identically; the backfill semantics go in
      ``note``.
    - ``commission_rate`` is stored per row (not in global config) so the
      ledger stays re-computable even if the broker's rate changes over time.
    - Money is ``Numeric``, never float: parity with the originating
      quant-advisor scripts is an acceptance requirement, and float rounding
      must not enter through the storage layer.
    """

    __tablename__ = "etf_grid_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, comment="Execution date of the trade")
    symbol: Mapped[str] = mapped_column(String(6), comment="Six-digit fund code, e.g. '513330'")
    side: Mapped[str] = mapped_column(String(8), comment="Trade direction: buy | sell (values generated from the Side enum)")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 4), comment="Execution price per share")
    quantity: Mapped[int] = mapped_column(Integer, comment="Number of shares (round lots of 100)")
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), comment="Turnover before fees: price * quantity")
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), comment="Broker commission rate applied to gross_amount, e.g. 0.001")
    commission: Mapped[Decimal] = mapped_column(Numeric(10, 2), comment="Commission charged: round(gross_amount * commission_rate, 2), overridable")
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), comment="Cash actually paid (buy: gross + commission) or received (sell: gross - commission)")
    source: Mapped[str] = mapped_column(String(32), default="manual", comment="Entry channel: manual | agent")
    note: Mapped[str | None] = mapped_column(Text, comment="Free-form remark, e.g. backfill semantics or reconciliation notes")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="When the row was recorded (distinct from trade_date for backfills)")

    __table_args__ = (
        CheckConstraint(f"side IN ({_SIDE_CHECK})", name="ck_etf_grid_trades_side"),
        # Replay always reads one symbol ordered by date; the index also
        # documents the canonical access pattern.
        Index("ix_etf_grid_trades_symbol_trade_date", "symbol", "trade_date"),
    )


class EtfGridCandle(EtfGridBase):
    """One forward-adjusted (qfq) daily candle for a tracked symbol.

    Local cache of FTShare ``ft_v1_etf_candlesticks`` (``adjust_kind=
    Forward``). Contracts:

    - **qfq basis**: a dividend recomputes ALL historical bars, so rows
      are **upserted, never append-only** — sync refetches a trailing
      ~90-day window (covering the MA60 computation window) so
      re-adjustments self-heal. The original script's 10-day lookback
      only fixes vendor corrections — a latent flaw for dividend-paying
      symbols like 513530, deviated from deliberately.
    - The composite PK is the upsert key and covers the only access
      pattern (history per symbol, date-ordered) — no surrogate id, no
      extra indexes.
    - Sole data source: FTShare. The 6-digit ``symbol`` maps to
      FTShare's exchange-suffixed form (``513330.XSHG``) in config.
    """

    __tablename__ = "etf_grid_candles"

    symbol: Mapped[str] = mapped_column(String(6), primary_key=True, comment="Six-digit fund code, e.g. '513330'")
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, comment="Trading day of the bar")
    open: Mapped[Decimal] = mapped_column(Numeric(10, 4), comment="Forward-adjusted open price")
    high: Mapped[Decimal] = mapped_column(Numeric(10, 4), comment="Forward-adjusted high price")
    low: Mapped[Decimal] = mapped_column(Numeric(10, 4), comment="Forward-adjusted low price")
    close: Mapped[Decimal] = mapped_column(Numeric(10, 4), comment="Forward-adjusted close price")
    volume: Mapped[int] = mapped_column(BigInteger, comment="Volume in shares (800M+ values exist in history)")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), comment="When this row was last refreshed by sync (data freshness marker)")
