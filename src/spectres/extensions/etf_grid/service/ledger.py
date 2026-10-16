"""Trade ledger service: record trades and derive positions from the append-only ledger."""

import logging
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute
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

from .base import _SessionBound

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
    stable tiebreaker so every ordering is fully deterministic (a
    precondition for future LIMIT/OFFSET pagination).
    """
    specs = list(_DEFAULT_ORDER if order_by is None else order_by)
    if not any(spec.field is TradeSortField.ID for spec in specs):
        specs.append(SortSpec(TradeSortField.ID))
    clauses: list[ColumnElement[Any]] = []
    for spec in specs:
        column = _SORTABLE_COLUMNS[spec.field]
        clauses.append(column.desc() if spec.direction is SortDirection.DESC else column.asc())
    return clauses


class EtfGridLedgerService(_SessionBound):
    """Records trades and derives positions from the append-only ledger."""

    def record_trade(
        self,
        *,
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
        order_by: Sequence[SortSpec[TradeSortField]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return ledger trades, optionally filtered by symbol and sorted.

        Args:
            symbol: Restrict the result to one symbol when given.
            order_by: Sort keys as whitelisted ``SortSpec`` items; directions
                are pushed down into SQL. ``None`` keeps the replay-canonical
                order ``(symbol ASC, trade_date ASC, id ASC)`` that
                ``get_positions`` relies on. Unless ``id`` is an explicit
                sort key, ``id ASC`` is appended as a stable tiebreaker, so
                every ordering is fully deterministic — a precondition for
                future LIMIT/OFFSET pagination.

        Returns:
            The matching trades as structured dicts, in the requested order.
        """
        stmt = select(EtfGridTrade).order_by(*_order_clauses(order_by))
        if symbol is not None:
            stmt = stmt.where(EtfGridTrade.symbol == normalize_symbol(symbol))
        with self._session_factory() as session:
            return [_trade_to_dict(trade) for trade in session.scalars(stmt)]

    def get_positions(self) -> dict[str, Position]:
        """Replay the ledger per symbol and return the current positions.

        Positions are always derived from the append-only ledger, never
        stored: ``replay_ledger`` folds each symbol's trades (in the
        replay-canonical order provided by ``list_trades()``) into a
        ``Position`` — current shares, moving weighted-average cost
        (fee-inclusive, via ``net_amount``), realized P&L from sells, and
        the open-lot queue kept cheapest-entry-first for the grid's
        cost-protection sell pairing.

        This is the single source of "what do I hold" for both the grid
        signal computation (lots and average cost feed the strategy) and
        any presentation surface (holdings answers in chat, the future
        ledger page). It reflects ledger facts only; market value and
        unrealized P&L require candle data and are layered on elsewhere.

        Returns:
            A mapping of symbol to its replayed ``Position``.
        """
        positions: dict[str, list[LedgerTrade]] = {}
        for trade in self.list_trades():
            positions.setdefault(trade["symbol"], []).append(_to_ledger_trade(trade))
        return {symbol: replay_ledger(trades) for symbol, trades in positions.items()}

    def get_position(self, symbol: str) -> Position | None:
        """Replay the ledger for one symbol and return its current position.

        Returns ``None`` when the symbol has no trades. The per-symbol
        companion of ``get_positions()``: callers that must keep one
        symbol's ledger failure from aborting the rest of the portfolio
        (signal computation) use this inside their isolation boundary.
        """
        trades = [_to_ledger_trade(trade) for trade in self.list_trades(symbol)]
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
