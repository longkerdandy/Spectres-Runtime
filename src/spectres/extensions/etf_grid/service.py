"""Application services for the ETF grid extension."""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.core.grid import (
    GridSignalInput,
    SignalSnapshot,
    compute_signal,
    gate_state,
    moving_average,
)
from spectres.extensions.etf_grid.core.ledger import (
    LedgerTrade,
    Position,
    compute_trade_amounts,
    replay_ledger,
)
from spectres.extensions.etf_grid.db import get_session_factory
from spectres.extensions.etf_grid.models import EtfGridCandle, EtfGridSignal, EtfGridTrade, EtfGridValuation
from spectres.extensions.etf_grid.types import (
    CandleInput,
    OrderAdvice,
    Side,
    SignalSortField,
    SortDirection,
    SortSpec,
    Source,
    TradeSortField,
    ValuationInput,
    normalize_symbol,
)

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


class EtfGridLedgerService:
    """Records trades and derives positions from the append-only ledger."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        """Create the service; defaults to the extension's shared session factory."""
        self._session_factory = session_factory or get_session_factory()

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
            return _trade_to_dict(trade)

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
            positions.setdefault(trade["symbol"], []).append(
                LedgerTrade(
                    trade_date=trade["trade_date"],
                    side=Side(trade["side"]),
                    quantity=trade["quantity"],
                    net_amount=trade["net_amount"],
                )
            )
        return {symbol: replay_ledger(trades) for symbol, trades in positions.items()}


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


class EtfGridCandleService:
    """Stores and reads the local forward-adjusted (qfq) daily candle cache."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        """Create the service; defaults to the extension's shared session factory."""
        self._session_factory = session_factory or get_session_factory()

    def upsert_candles(self, candles: Sequence[CandleInput]) -> int:
        """Upsert a batch of daily candles in a single transaction.

        Upsert contract: on conflict of the ``(symbol, trade_date)`` primary
        key the OHLCV values are overwritten and ``fetched_at`` is refreshed.
        This overwrite-and-refresh behavior is deliberate self-healing, not
        just idempotency: on the qfq basis a dividend recomputes ALL
        historical bars, so re-syncing a trailing window must replace stale
        rows rather than skip them.

        Args:
            candles: The candles to write (provider-translated inputs).

        Returns:
            The number of rows written.

        Raises:
            ValueError: If any symbol fails validation, any price is not
                positive, or any volume negative.
        """
        rows = []
        for candle in candles:
            symbol = normalize_symbol(candle.symbol)
            if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
                raise ValueError(f"{symbol} {candle.trade_date}: candle prices must be positive, got O={candle.open} H={candle.high} L={candle.low} C={candle.close}")
            if candle.volume < 0:
                raise ValueError(f"{symbol} {candle.trade_date}: volume must be non-negative, got {candle.volume}")
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": candle.trade_date,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
            )
        if not rows:
            return 0
        stmt = pg_insert(EtfGridCandle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "fetched_at": func.now(),
            },
        )
        with self._session_factory() as session, session.begin():
            session.execute(stmt)
        return len(candles)

    def list_candles(
        self,
        symbol: str,
        *,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return one symbol's candles ordered by trade date.

        Time is the only meaningful sort dimension for candles, and the
        ``(symbol, trade_date)`` primary key already guarantees uniqueness —
        so unlike ``list_trades`` there is no ``SortSpec`` machinery and no
        stable-suffix rule here. If a genuine multi-dimensional need ever
        appears, add it following the trades template. ``limit`` is pushed
        down into SQL; combine with ``descending=True`` for the latest N
        bars.

        Args:
            symbol: The symbol whose history to read.
            descending: Newest first when True (default: chronological).
            limit: Optional maximum number of rows, pushed down into SQL.

        Returns:
            The candles as structured dicts in the requested order.
        """
        direction = EtfGridCandle.trade_date.desc() if descending else EtfGridCandle.trade_date.asc()
        stmt = select(EtfGridCandle).where(EtfGridCandle.symbol == normalize_symbol(symbol)).order_by(direction)
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._session_factory() as session:
            return [_candle_to_dict(candle) for candle in session.scalars(stmt)]


def _candle_to_dict(candle: EtfGridCandle) -> dict[str, Any]:
    """Convert a candle ORM row into a structured dict."""
    return {
        "symbol": candle.symbol,
        "trade_date": candle.trade_date,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "fetched_at": candle.fetched_at,
    }


class EtfGridValuationService:
    """Stores and reads the 930914 index valuation series (gate input)."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        """Create the service; defaults to the extension's shared session factory."""
        self._session_factory = session_factory or get_session_factory()

    def upsert_valuation(self, rows: Sequence[ValuationInput]) -> int:
        """Upsert valuation rows in a single transaction.

        Upsert semantics match candles: on conflict of the ``trade_date``
        primary key the values are overwritten and ``fetched_at`` refreshed,
        so csindex history revisions self-heal.

        Returns:
            The number of rows written.
        """
        if not rows:
            return 0
        stmt = pg_insert(EtfGridValuation).values([{"trade_date": row.trade_date, "close": row.close, "pe_ttm": row.pe_ttm, "dyr": row.dyr} for row in rows])
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_date"],
            set_={"close": stmt.excluded.close, "pe_ttm": stmt.excluded.pe_ttm, "dyr": stmt.excluded.dyr, "fetched_at": func.now()},
        )
        with self._session_factory() as session, session.begin():
            session.execute(stmt)
        return len(rows)

    def latest_valuation(self) -> dict[str, Any] | None:
        """Return the most recent valuation row, or None when the table is empty."""
        stmt = select(EtfGridValuation).order_by(EtfGridValuation.trade_date.desc()).limit(1)
        with self._session_factory() as session:
            row = session.scalars(stmt).first()
            return _valuation_to_dict(row) if row else None

    def list_valuation(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return valuation rows oldest-first (the gate needs the full series for percentiles)."""
        stmt = select(EtfGridValuation).order_by(EtfGridValuation.trade_date.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._session_factory() as session:
            return [_valuation_to_dict(row) for row in session.scalars(stmt)]


def _valuation_to_dict(row: EtfGridValuation) -> dict[str, Any]:
    """Convert a valuation ORM row into a structured dict."""
    return {
        "trade_date": row.trade_date,
        "close": row.close,
        "pe_ttm": row.pe_ttm,
        "dyr": row.dyr,
        "fetched_at": row.fetched_at,
    }


_SIGNAL_SORTABLE_COLUMNS: dict[SignalSortField, InstrumentedAttribute[Any]] = {
    SignalSortField.TRADE_DATE: EtfGridSignal.trade_date,
    SignalSortField.SYMBOL: EtfGridSignal.symbol,
    SignalSortField.CLOSE: EtfGridSignal.close,
    SignalSortField.LEVEL: EtfGridSignal.level,
    SignalSortField.COMPUTED_AT: EtfGridSignal.computed_at,
}

_SIGNAL_DEFAULT_ORDER: tuple[SortSpec[SignalSortField], ...] = (
    SortSpec(SignalSortField.SYMBOL),
    SortSpec(SignalSortField.TRADE_DATE),
)

_SIGNAL_STABLE_KEYS = (SignalSortField.SYMBOL, SignalSortField.TRADE_DATE)


def _signal_order_clauses(order_by: Sequence[SortSpec[SignalSortField]] | None) -> list[ColumnElement[Any]]:
    """Translate signal sort specs into ORDER BY clauses via the column whitelist.

    Same pattern as the trades ledger: ``None`` selects the canonical
    ``(symbol, trade_date)`` order. The stable suffix is the composite
    primary key (whichever of its parts the caller did not sort by) —
    there is no surrogate id here because the PK already guarantees
    uniqueness.
    """
    specs = list(_SIGNAL_DEFAULT_ORDER if order_by is None else order_by)
    for key in _SIGNAL_STABLE_KEYS:
        if not any(spec.field is key for spec in specs):
            specs.append(SortSpec(key))
    clauses: list[ColumnElement[Any]] = []
    for spec in specs:
        column = _SIGNAL_SORTABLE_COLUMNS[spec.field]
        clauses.append(column.desc() if spec.direction is SortDirection.DESC else column.asc())
    return clauses


class EtfGridSignalService:
    """Stores and reads computed daily signal snapshots."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        """Create the service; defaults to the extension's shared session factory."""
        self._session_factory = session_factory or get_session_factory()

    def upsert_signals(self, snapshots: Sequence[SignalSnapshot]) -> int:
        """Upsert signal snapshots in a single transaction.

        Upsert on recompute: on conflict of the ``(symbol, trade_date)``
        primary key the row is overwritten and ``computed_at`` refreshed —
        the signal is advice, not fact, and the latest computation is
        always the most accurate (e.g. after recording a trade).

        Returns:
            The number of rows written.
        """
        if not snapshots:
            return 0
        stmt = pg_insert(EtfGridSignal).values([_snapshot_to_row(snapshot) for snapshot in snapshots])
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "trade_date"],
            set_={
                "close": stmt.excluded.close,
                "anchor_ma60": stmt.excluded.anchor_ma60,
                "level": stmt.excluded.level,
                "prev_level": stmt.excluded.prev_level,
                "orders": stmt.excluded.orders,
                "block_reason": stmt.excluded.block_reason,
                "gate_metric_value": stmt.excluded.gate_metric_value,
                "gate_percentile": stmt.excluded.gate_percentile,
                "gate_closed": stmt.excluded.gate_closed,
                "computed_at": func.now(),
            },
        )
        with self._session_factory() as session, session.begin():
            session.execute(stmt)
        return len(snapshots)

    def list_signals(
        self,
        symbol: str | None = None,
        *,
        order_by: Sequence[SortSpec[SignalSortField]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return signal snapshots, optionally filtered by symbol and sorted.

        ``order_by=None`` keeps the canonical ``(symbol, trade_date)``
        order; the composite primary key (whichever parts are not explicit
        sort keys) is appended as the stable suffix.
        """
        stmt = select(EtfGridSignal).order_by(*_signal_order_clauses(order_by))
        if symbol is not None:
            stmt = stmt.where(EtfGridSignal.symbol == normalize_symbol(symbol))
        with self._session_factory() as session:
            return [_signal_to_dict(signal) for signal in session.scalars(stmt)]

    def latest_signal(self, symbol: str) -> dict[str, Any] | None:
        """Return the symbol's most recent signal snapshot, or None."""
        stmt = select(EtfGridSignal).where(EtfGridSignal.symbol == normalize_symbol(symbol)).order_by(EtfGridSignal.trade_date.desc()).limit(1)
        with self._session_factory() as session:
            row = session.scalars(stmt).first()
            return _signal_to_dict(row) if row else None


def _order_to_json(order: OrderAdvice) -> dict[str, Any]:
    """Serialize one order advice for the JSONB column (Decimals as strings)."""
    return {
        "side": order.side,
        "limit_price": str(order.limit_price),
        "grids": order.grids,
        "shares_est": order.shares_est,
        "kind": order.kind,
        "note": order.note,
    }


def _snapshot_to_row(snapshot: SignalSnapshot) -> dict[str, Any]:
    """Convert a computed signal snapshot into row values for upsert."""
    return {
        "symbol": snapshot.symbol,
        "trade_date": snapshot.trade_date,
        "close": snapshot.close,
        "anchor_ma60": snapshot.anchor_ma60,
        "level": snapshot.level,
        "prev_level": snapshot.prev_level,
        "orders": [_order_to_json(order) for order in snapshot.orders],
        "block_reason": snapshot.block_reason.value if snapshot.block_reason else None,
        "gate_metric_value": snapshot.gate_metric_value,
        "gate_percentile": snapshot.gate_percentile,
        "gate_closed": snapshot.gate_closed,
    }


def _signal_to_dict(signal: EtfGridSignal) -> dict[str, Any]:
    """Convert a signal ORM row into a structured dict."""
    return {
        "symbol": signal.symbol,
        "trade_date": signal.trade_date,
        "close": signal.close,
        "anchor_ma60": signal.anchor_ma60,
        "level": signal.level,
        "prev_level": signal.prev_level,
        "orders": signal.orders,
        "block_reason": signal.block_reason,
        "gate_metric_value": signal.gate_metric_value,
        "gate_percentile": signal.gate_percentile,
        "gate_closed": signal.gate_closed,
        "computed_at": signal.computed_at,
    }


def compute_daily_signals(
    symbols: Sequence[str] | None = None,
    *,
    config: EtfGridConfig | None = None,
    ledger_service: EtfGridLedgerService | None = None,
    candle_service: EtfGridCandleService | None = None,
    valuation_service: EtfGridValuationService | None = None,
    signal_service: EtfGridSignalService | None = None,
) -> dict[str, Any]:
    """Compute and persist daily grid signals for the portfolio.

    For each configured symbol: read the candle history (61+ bars are
    required — MA60 today plus MA60 yesterday), replay the ledger for the
    position and lot queue, resolve the valuation gate when configured,
    compute the signal via ``core.grid``, and upsert the snapshot.

    Symbols with insufficient candle history are skipped (not crashed)
    and recorded under ``skipped``; a symbol with a configured gate but no
    usable valuation series is skipped too — emitting un-gated buy advice
    for a gated symbol would defeat the gate's purpose.

    Returns:
        ``{"signals": {symbol: signal dict}, "skipped": {symbol: reason}}``.
    """
    config = config or EtfGridConfig()  # type: ignore[call-arg]  # required fields come from ETF_GRID_* env vars
    ledger_service = ledger_service or EtfGridLedgerService()
    candle_service = candle_service or EtfGridCandleService()
    valuation_service = valuation_service or EtfGridValuationService()
    signal_service = signal_service or EtfGridSignalService()

    items = [item for item in config.portfolio if symbols is None or item.symbol in {normalize_symbol(s) for s in symbols}]
    positions = ledger_service.get_positions()
    valuation_rows: list[dict[str, Any]] | None = None

    signals: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for item in items:
        candles = candle_service.list_candles(item.symbol)
        if len(candles) < 61:
            skipped[item.symbol] = "insufficient_candles"
            continue

        gate = None
        if item.gate is not None:
            if valuation_rows is None:
                valuation_rows = valuation_service.list_valuation()
            values = [row[item.gate.metric] for row in valuation_rows if row[item.gate.metric] is not None]
            gate = gate_state(values, Decimal(str(item.gate.threshold)), item.gate.block_when)
            if gate is None:
                skipped[item.symbol] = "no_valuation_data"
                continue

        closes = [candle["close"] for candle in candles]
        anchor = moving_average(closes)
        prev_anchor = moving_average(closes[:-1])
        assert anchor is not None and prev_anchor is not None  # guaranteed by the >=61 candle check
        position = positions.get(item.symbol)
        snapshot = compute_signal(
            GridSignalInput(
                symbol=item.symbol,
                trade_date=candles[-1]["trade_date"],
                close=closes[-1],
                prev_close=closes[-2],
                anchor=anchor,
                prev_anchor=prev_anchor,
                shares=position.shares if position else 0,
                lots=position.lots if position else (),
                per_grid_amount=item.per_grid_amount,
                max_grids=item.max_grids,
                gate=gate,
            ),
            config.grid_step,
        )
        signal_service.upsert_signals([snapshot])
        signals[item.symbol] = _snapshot_to_row(snapshot)
    return {"signals": signals, "skipped": skipped}


def get_portfolio_status(
    *,
    config: EtfGridConfig | None = None,
    ledger_service: EtfGridLedgerService | None = None,
    candle_service: EtfGridCandleService | None = None,
    signal_service: EtfGridSignalService | None = None,
) -> list[dict[str, Any]]:
    """Per-symbol portfolio summary for presentation surfaces (toolkit/UI).

    Combines the ledger-derived position (shares, average cost, realized
    P&L) with the latest close (market value) and the latest persisted
    signal snapshot. Positions always come from the ledger — never from
    stored snapshots.
    """
    config = config or EtfGridConfig()  # type: ignore[call-arg]  # required fields come from ETF_GRID_* env vars
    ledger_service = ledger_service or EtfGridLedgerService()
    candle_service = candle_service or EtfGridCandleService()
    signal_service = signal_service or EtfGridSignalService()

    positions = ledger_service.get_positions()
    status = []
    for item in config.portfolio:
        position = positions.get(item.symbol)
        latest = candle_service.list_candles(item.symbol, descending=True, limit=1)
        close = latest[0]["close"] if latest else None
        status.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "shares": position.shares if position else 0,
                "avg_cost": position.avg_cost if position else None,
                "realized": position.realized if position else Decimal(0),
                "close": close,
                "close_date": latest[0]["trade_date"] if latest else None,
                "market_value": close * position.shares if close is not None and position else None,
                "signal": signal_service.latest_signal(item.symbol),
            }
        )
    return status


def to_jsonable[T](value: T) -> T:
    """Normalize service outputs into JSON-serializable structures.

    Decimals become strings, dates/datetimes ISO strings, applied
    recursively through dicts and sequences. Shared by the toolkit and
    API adapters so the chat and HTTP surfaces serialize identically.
    The container shape is preserved; only leaf scalar types change
    (hence the casts: T describes the container, not the leaves).
    """
    if isinstance(value, Decimal):
        return cast(T, str(value))
    if isinstance(value, datetime):
        return cast(T, value.isoformat())
    if isinstance(value, date):
        return cast(T, value.isoformat())
    if isinstance(value, dict):
        return cast(T, {key: to_jsonable(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return cast(T, [to_jsonable(item) for item in value])
    return value
