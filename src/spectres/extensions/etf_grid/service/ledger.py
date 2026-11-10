"""Trade ledger service: record trades and derive positions from the append-only ledger."""

import logging
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from spectres.extensions.etf_grid.core.ledger import (
    LedgerTrade,
    Position,
    compute_trade_amounts,
    replay_ledger,
)
from spectres.extensions.etf_grid.models import EtfGridTrade
from spectres.extensions.etf_grid.types import (
    Side,
    SortDirection,
    SortSpec,
    Source,
    TradeSortField,
    normalize_symbol,
)

from .identity import _require_user_id

logger = logging.getLogger(__name__)

_SORTABLE_COLUMNS: dict[TradeSortField, InstrumentedAttribute[Any]] = {
    TradeSortField.ID: EtfGridTrade.id,
    TradeSortField.TRADE_DATE: EtfGridTrade.trade_date,
    TradeSortField.SYMBOL: EtfGridTrade.symbol,
    TradeSortField.SIDE: EtfGridTrade.side,
    TradeSortField.PRICE: EtfGridTrade.price,
    TradeSortField.QUANTITY: EtfGridTrade.quantity,
    TradeSortField.GROSS_AMOUNT: EtfGridTrade.gross_amount,
    TradeSortField.COMMISSION: EtfGridTrade.commission,
    TradeSortField.NET_AMOUNT: EtfGridTrade.net_amount,
    TradeSortField.CREATED_AT: EtfGridTrade.created_at,
}

_DEFAULT_ORDER: tuple[SortSpec[TradeSortField], ...] = (
    SortSpec(TradeSortField.SYMBOL),
    SortSpec(TradeSortField.TRADE_DATE),
)


def _order_clauses(order_by: Sequence[SortSpec[TradeSortField]] | None) -> list[ColumnElement[Any]]:
    """Translate sort specs into ORDER BY clauses via the column whitelist.

    ``None`` selects the replay-canonical default order (symbol, trade_date).
    Unless the caller explicitly sorts by id, ``id ASC`` is appended as a
    stable tiebreaker so every ordering is fully deterministic, as required
    by LIMIT/OFFSET pagination.
    """
    specs = list(_DEFAULT_ORDER if order_by is None else order_by)
    if not any(spec.field is TradeSortField.ID for spec in specs):
        specs.append(SortSpec(TradeSortField.ID))
    clauses: list[ColumnElement[Any]] = []
    for spec in specs:
        column = _SORTABLE_COLUMNS[spec.field]
        clauses.append(column.desc() if spec.direction is SortDirection.DESC else column.asc())
    return clauses


def _trade_filters(user_id: str, symbol: str | None, start: date | None, end: date | None) -> list[ColumnElement[Any]]:
    """Build the shared owner and optional trade predicates."""
    filters: list[ColumnElement[Any]] = [EtfGridTrade.user_id == user_id]
    if symbol is not None:
        filters.append(EtfGridTrade.symbol == normalize_symbol(symbol))
    if start is not None:
        filters.append(EtfGridTrade.trade_date >= start)
    if end is not None:
        filters.append(EtfGridTrade.trade_date <= end)
    return filters


class EtfGridLedgerService:
    """Records trades and derives positions from the append-only ledger."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Create the service with an explicitly injected session factory."""
        self._session_factory = session_factory

    def record_trade(
        self,
        *,
        user_id: str,
        trade_date: date,
        symbol: str,
        side: Side,
        price: Decimal,
        quantity: int,
        commission_rate: Decimal,
        note: str | None = None,
        source: Source = Source.MANUAL,
        commission: Decimal | None = None,
        net_amount: Decimal | None = None,
    ) -> dict[str, Any]:
        """Validate, compute amounts for, and persist one ledger trade.

        Args:
            user_id: Authenticated owner of the new ledger row.
            trade_date: Execution date of the trade.
            symbol: FTShare-style symbol (``<code>.<exchange>``); normalized
                with strip + upper and loosely validated.
            side: Trade side (an opening-position backfill is a plain buy;
                use ``note`` to record the backfill semantics).
            price: Execution price per share (must be positive).
            quantity: Number of shares (must be positive).
            commission_rate: Broker commission rate (must be non-negative).
            note: Optional free-form note.
            source: Provenance of the record.
            commission: Optional override for the computed commission
                (e.g. broker minimum commissions).
            net_amount: Optional override for the computed net amount.

        Returns:
            The persisted trade as a structured dict.

        Raises:
            ValueError: If the symbol or any numeric input fails validation.
        """
        user_id = _require_user_id(user_id)
        symbol = normalize_symbol(symbol)
        if price <= 0:
            raise ValueError(f"price must be positive, got {price}")
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        if commission_rate < 0:
            raise ValueError(f"commission_rate must be non-negative, got {commission_rate}")
        if commission is not None and commission < 0:
            raise ValueError(f"commission must be non-negative, got {commission}")
        if net_amount is not None and net_amount <= 0:
            raise ValueError(f"net_amount must be positive, got {net_amount}")

        amounts = compute_trade_amounts(side, price, quantity, commission_rate, commission, net_amount)
        trade = EtfGridTrade(
            user_id=user_id,
            trade_date=trade_date,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            gross_amount=amounts.gross_amount,
            commission_rate=commission_rate,
            commission=amounts.commission,
            net_amount=amounts.net_amount,
            source=source,
            note=note,
        )
        with self._session_factory() as session, session.begin():
            session.add(trade)
            session.flush()
            session.refresh(trade)
            result = _trade_to_dict(trade)
        logger.info(
            "trade recorded",
            extra={
                "event": "trade_recorded",
                "trade_id": result["id"],
                "user_id": user_id,
                "symbol": result["symbol"],
                "side": side.value,
                "quantity": result["quantity"],
                "price": str(result["price"]),
                "net_amount": str(result["net_amount"]),
                "source": source.value,
            },
        )
        return result

    def list_trades(
        self,
        symbol: str | None = None,
        *,
        user_id: str,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order_by: Sequence[SortSpec[TradeSortField]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return one owner's trades with filtering, sorting, and SQL pagination."""
        user_id = _require_user_id(user_id)
        stmt = select(EtfGridTrade).where(*_trade_filters(user_id, symbol, start, end)).order_by(*_order_clauses(order_by))
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)
        with self._session_factory() as session:
            return [_trade_to_dict(trade) for trade in session.scalars(stmt)]

    def count_trades(self, symbol: str | None = None, *, user_id: str, start: date | None = None, end: date | None = None) -> int:
        """Count trades matching the same owner and filters as ``list_trades``."""
        user_id = _require_user_id(user_id)
        stmt = select(func.count()).select_from(EtfGridTrade).where(*_trade_filters(user_id, symbol, start, end))
        with self._session_factory() as session:
            return session.scalar(stmt) or 0

    def get_positions(self, *, user_id: str) -> dict[str, Position]:
        """Replay one owner's ledger per symbol and return current positions."""
        positions: dict[str, list[LedgerTrade]] = {}
        for trade in self.list_trades(user_id=user_id):
            positions.setdefault(trade["symbol"], []).append(_to_ledger_trade(trade))
        return {symbol: replay_ledger(trades) for symbol, trades in positions.items()}

    def get_position(self, symbol: str, *, user_id: str) -> Position | None:
        """Replay one owner's ledger for one symbol."""
        trades = [_to_ledger_trade(trade) for trade in self.list_trades(symbol, user_id=user_id)]
        return replay_ledger(trades) if trades else None


def _to_ledger_trade(trade: dict[str, Any]) -> LedgerTrade:
    """Convert a structured trade dict into the replay input type."""
    return LedgerTrade(
        trade_date=trade["trade_date"],
        side=Side(trade["side"]),
        quantity=trade["quantity"],
        net_amount=trade["net_amount"],
    )


def _trade_to_dict(trade: EtfGridTrade) -> dict[str, Any]:
    """Convert a trade ORM row into a structured dict."""
    return {
        "id": trade.id,
        "user_id": trade.user_id,
        "trade_date": trade.trade_date,
        "symbol": trade.symbol,
        "side": trade.side,
        "price": trade.price,
        "quantity": trade.quantity,
        "gross_amount": trade.gross_amount,
        "commission_rate": trade.commission_rate,
        "commission": trade.commission,
        "net_amount": trade.net_amount,
        "source": trade.source,
        "note": trade.note,
        "created_at": trade.created_at,
    }
