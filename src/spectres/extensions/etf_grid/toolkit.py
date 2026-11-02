"""Agno toolkit adapter for the ETF grid extension (thin adapter, no business logic).

Tool functions return a JSON-serializable envelope (Decimals as strings,
dates as ISO strings via ``service.to_jsonable``) so the LLM and the Client
always see the same payload shape:

- Success: ``{"ok": True, "data": ...}``
- Failure: ``{"ok": False, "error": {"type", "message", "trace_id", "hint"}}``
  — the tool boundary never raises. The ERROR record behind a failure is
  greppable in the Runtime JSONL log by ``trace_id``; ``hint`` spells out
  the exact lookup for the agent.
"""

import asyncio
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from agno.run import RunContext
from agno.tools.toolkit import Toolkit

from spectres.config import settings
from spectres.extensions.etf_grid.config import EtfGridConfig, load_config
from spectres.extensions.etf_grid.marketdata import sync_market_data
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridInstrumentService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
    compute_daily_signals,
    get_portfolio_status,
    to_jsonable,
)
from spectres.extensions.etf_grid.types import Side, SortDirection, SortSpec, Source, TradeSortField
from spectres.logging import bind_trace, current_trace_id, log_file_for_today, new_trace

logger = logging.getLogger(__name__)


def _tool_error(tool: str, exc: Exception) -> dict[str, Any]:
    """Build the structured error envelope for a failed tool call.

    Binds a fresh trace id when none is active (a tool invocation outside an
    HTTP request still gets a correlatable ERROR record), logs the failure at
    ERROR with ``exc_info``, and returns the contract payload. The hint is
    deliberately concrete: the Team Leader carries ShellTools and can run the
    grep as-is.
    """
    trace_id = current_trace_id()
    if trace_id is None:
        trace_id = new_trace()
        bind_trace(trace_id)
    logger.error("tool call failed", exc_info=exc, extra={"event": "tool_failed", "tool": tool})
    return {
        "ok": False,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc),
            "trace_id": trace_id,
            "hint": f"Investigate with the shell tool, e.g.: grep {trace_id} {log_file_for_today(settings.log_dir)}",
        },
    }


def _run_user_id(run_context: RunContext | None) -> str:
    if run_context is None or not run_context.user_id:
        raise PermissionError("authenticated run user_id is required")
    return run_context.user_id


class EtfGridToolkit(Toolkit):
    """ETF grid tools scoped to the authenticated Agent run owner."""

    def __init__(
        self,
        *,
        config: EtfGridConfig | None = None,
        ledger_service: EtfGridLedgerService | None = None,
        candle_service: EtfGridCandleService | None = None,
        valuation_service: EtfGridValuationService | None = None,
        signal_service: EtfGridSignalService | None = None,
        instrument_service: EtfGridInstrumentService | None = None,
    ) -> None:
        """Create the toolkit with shared services injectable for tests."""
        self._config = config or load_config()
        self._ledger = ledger_service or EtfGridLedgerService()
        self._candles = candle_service or EtfGridCandleService()
        self._valuation = valuation_service or EtfGridValuationService()
        self._signals = signal_service or EtfGridSignalService()
        self._instruments = instrument_service or EtfGridInstrumentService()
        super().__init__(
            name="etf_grid",
            tools=[self.get_grid_status, self.refresh_grid_data, self.record_grid_trade, self.list_grid_trades],
        )

    def get_grid_status(self, run_context: RunContext) -> dict[str, Any]:
        """Get the current user's ETF grid portfolio status.

        Returns private ledger position, cost and P&L combined with shared
        market data and the user's latest signal.
        """
        try:
            data = to_jsonable(
                get_portfolio_status(
                    user_id=_run_user_id(run_context),
                    config=self._config,
                    ledger_service=self._ledger,
                    candle_service=self._candles,
                    signal_service=self._signals,
                    instrument_service=self._instruments,
                )
            )
        except Exception as exc:
            return _tool_error("get_grid_status", exc)
        return {"ok": True, "data": data}

    async def refresh_grid_data(self, run_context: RunContext) -> dict[str, Any]:
        """Refresh shared market data and recompute the current user's signals."""
        try:
            user_id = _run_user_id(run_context)
        except Exception as exc:
            return _tool_error("refresh_grid_data", exc)
        return await asyncio.to_thread(self._refresh_grid_data_sync, user_id)

    def _refresh_grid_data_sync(self, user_id: str) -> dict[str, Any]:
        try:
            refresh = sync_market_data(
                config=self._config,
                candle_service=self._candles,
                valuation_service=self._valuation,
                instrument_service=self._instruments,
            )
            signals = compute_daily_signals(
                user_id=user_id,
                config=self._config,
                ledger_service=self._ledger,
                candle_service=self._candles,
                valuation_service=self._valuation,
                signal_service=self._signals,
                instrument_service=self._instruments,
            )
            data = to_jsonable({**refresh, **signals})
        except Exception as exc:
            return _tool_error("refresh_grid_data", exc)
        return {"ok": True, "data": data}

    def record_grid_trade(
        self,
        run_context: RunContext,
        symbol: str,
        trade_date: str,
        side: str,
        price: str,
        quantity: int,
        commission_rate: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record one executed trade into the current user's append-only ledger.

        Parameters: symbol as FTShare full code (e.g. '513330.XSHG'),
        trade_date as ISO date 'YYYY-MM-DD', side 'buy' or 'sell' (an
        opening-position backfill is a plain 'buy' — put the backfill
        semantics in note), price per share and commission_rate as
        decimal strings to preserve precision (e.g. '0.4100', '0.001'),
        quantity in shares. The system computes gross_amount, commission
        (rounded to cents) and net_amount. On success returns
        ``{"ok": true, "data": {...}}`` echoing the full persisted row so
        the user can verify the computed amounts in chat. On failure
        (including invalid input) returns ``{"ok": false, "error": {...}}``
        — read ``error.hint`` to investigate via the shell tool.
        """
        try:
            user_id = _run_user_id(run_context)
            trade = self._ledger.record_trade(
                user_id=user_id,
                trade_date=date.fromisoformat(trade_date),
                symbol=self._instruments.require_enabled(symbol, config=self._config),
                side=Side(side),
                price=Decimal(price),
                quantity=quantity,
                commission_rate=Decimal(commission_rate),
                note=note,
                source=Source.AGENT,
            )
            data = to_jsonable(trade)
        except Exception as exc:
            return _tool_error("record_grid_trade", exc)
        return {"ok": True, "data": data}

    def list_grid_trades(self, run_context: RunContext, symbol: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List the current user's recent ETF grid trades, newest first."""
        try:
            rows = self._ledger.list_trades(
                symbol,
                user_id=_run_user_id(run_context),
                order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)],
            )
            data = to_jsonable(rows[:limit])
        except Exception as exc:
            return _tool_error("list_grid_trades", exc)
        return {"ok": True, "data": data}
