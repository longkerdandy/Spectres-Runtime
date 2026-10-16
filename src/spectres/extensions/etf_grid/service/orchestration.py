"""Portfolio-level orchestration: daily signal computation and portfolio status."""

import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from spectres.extensions.etf_grid.config import EtfGridConfig, load_config
from spectres.extensions.etf_grid.core.grid import (
    GridSignalInput,
    SignalSnapshot,
    compute_signal,
    gate_state,
    moving_average,
)
from spectres.extensions.etf_grid.types import normalize_symbol

from .candles import EtfGridCandleService
from .ledger import EtfGridLedgerService
from .signals import EtfGridSignalService, _snapshot_to_row
from .valuation import EtfGridValuationService

logger = logging.getLogger(__name__)


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

    For each configured symbol: read the latest 61 candle bars (MA60
    today plus MA60 yesterday), replay the ledger for the position and
    lot queue, resolve the valuation gate when configured, compute the
    signal via ``core.grid``, and upsert the snapshot.

    Symbols with insufficient candle history are skipped (not crashed)
    and recorded under ``skipped``; a symbol with a configured gate but no
    usable valuation series is skipped too — emitting un-gated buy advice
    for a gated symbol would defeat the gate's purpose. Any other
    per-symbol failure (ledger replay errors, provider outages, malformed
    rows) is caught, logged at ERROR, and recorded under ``skipped`` as
    ``"error: <type>: <message>"`` so one broken symbol never aborts the
    rest of the batch. Computed snapshots are persisted in a single
    transaction at the end; if that batch upsert fails, every computed
    symbol is moved from ``signals`` into ``skipped`` with the same
    error reason — the portfolio is never left half-persisted.

    Returns:
        ``{"signals": {symbol: signal dict}, "skipped": {symbol: reason}}``.
    """
    config = config or load_config()
    ledger_service = ledger_service or EtfGridLedgerService()
    candle_service = candle_service or EtfGridCandleService()
    valuation_service = valuation_service or EtfGridValuationService()
    signal_service = signal_service or EtfGridSignalService()

    wanted = None if symbols is None else {normalize_symbol(s) for s in symbols}
    items = [item for item in config.portfolio if wanted is None or item.symbol in wanted]
    valuation_rows: list[dict[str, Any]] | None = None

    signals: dict[str, Any] = {}
    snapshots: list[SignalSnapshot] = []
    skipped: dict[str, str] = {}
    for item in items:
        try:
            # The strategy only consumes the latest 61 bars; fetch newest-first
            # with a SQL limit and restore chronological order.
            candles = list(reversed(candle_service.list_candles(item.symbol, descending=True, limit=61)))
            if len(candles) < 61:
                skipped[item.symbol] = "insufficient_candles"
                logger.debug("signal skipped: insufficient candles", extra={"event": "signal_skipped", "symbol": item.symbol, "reason": "insufficient_candles", "candle_count": len(candles)})
                continue

            gate = None
            if item.gate is not None:
                if valuation_rows is None:
                    valuation_rows = valuation_service.list_valuation()
                values = [row[item.gate.metric] for row in valuation_rows if row[item.gate.metric] is not None]
                gate = gate_state(values, Decimal(str(item.gate.threshold)), item.gate.block_when)
                if gate is None:
                    skipped[item.symbol] = "no_valuation_data"
                    logger.debug(
                        "signal skipped: gate has no usable valuation data",
                        extra={"event": "signal_skipped", "symbol": item.symbol, "reason": "no_valuation_data", "valuation_rows": len(valuation_rows)},
                    )
                    continue

            closes = [candle["close"] for candle in candles]
            anchor = moving_average(closes)
            prev_anchor = moving_average(closes[:-1])
            assert anchor is not None and prev_anchor is not None  # guaranteed by the >=61 candle check
            position = ledger_service.get_position(item.symbol)
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
            snapshots.append(snapshot)
            signals[item.symbol] = _snapshot_to_row(snapshot)
        except Exception as exc:
            skipped[item.symbol] = f"error: {type(exc).__name__}: {exc}"
            logger.error(
                "signal computation failed",
                exc_info=exc,
                extra={"event": "signal_error", "symbol": item.symbol},
            )
    try:
        signal_service.upsert_signals(snapshots)
    except Exception as exc:
        logger.error(
            "signal persistence failed",
            exc_info=exc,
            extra={"event": "signal_error", "symbols": sorted(signals)},
        )
        for symbol in signals:
            skipped[symbol] = f"error: {type(exc).__name__}: {exc}"
        signals.clear()
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
    P&L) with the latest close (market value, unrealized P&L and percent)
    and the latest persisted signal snapshot. Positions always come from
    the ledger — never from stored snapshots.
    """
    config = config or load_config()
    ledger_service = ledger_service or EtfGridLedgerService()
    candle_service = candle_service or EtfGridCandleService()
    signal_service = signal_service or EtfGridSignalService()

    positions = ledger_service.get_positions()
    portfolio_symbols = [item.symbol for item in config.portfolio]
    latest_candles = candle_service.latest_candles(portfolio_symbols)
    latest_signals = signal_service.latest_signals(portfolio_symbols)
    status: list[dict[str, Any]] = []
    for item in config.portfolio:
        position = positions.get(item.symbol)
        latest = latest_candles.get(item.symbol)
        close = latest["close"] if latest else None
        cost_basis: Decimal | None = None
        market_value: Decimal | None = None
        unrealized: Decimal | None = None
        if position is not None:
            if position.shares > 0 and position.avg_cost is not None:
                cost_basis = position.avg_cost * position.shares
            if close is not None:
                market_value = close * position.shares
                if cost_basis is not None:
                    unrealized = market_value - cost_basis
        status.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "shares": position.shares if position else 0,
                "avg_cost": position.avg_cost if position else None,
                "realized": position.realized if position else Decimal(0),
                "close": close,
                "close_date": latest["trade_date"] if latest else None,
                "market_value": market_value,
                "unrealized": unrealized,
                "unrealized_percent": (unrealized / cost_basis if unrealized is not None and cost_basis else None),
                "signal": latest_signals.get(item.symbol),
            }
        )
    return status
