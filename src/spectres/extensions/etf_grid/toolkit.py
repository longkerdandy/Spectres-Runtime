"""Agno toolkit adapter for the ETF grid extension (thin adapter, no business logic).

Tool functions return JSON-serializable structures (Decimals as strings,
dates as ISO strings via ``service.to_jsonable``) so the LLM and the
Client always see the same payload shape.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from agno.tools.toolkit import Toolkit

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.marketdata import sync_market_data
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
    compute_daily_signals,
    get_portfolio_status,
    to_jsonable,
)
from spectres.extensions.etf_grid.types import Side, SortDirection, SortSpec, Source, TradeSortField


class EtfGridToolkit(Toolkit):
    """ETF grid tools for the Team Leader: status, refresh, trade recording, ledger queries."""

    def __init__(
        self,
        *,
        config: EtfGridConfig | None = None,
        ledger_service: EtfGridLedgerService | None = None,
        candle_service: EtfGridCandleService | None = None,
        valuation_service: EtfGridValuationService | None = None,
        signal_service: EtfGridSignalService | None = None,
    ) -> None:
        """Create the toolkit; services default to the shared instances (injectable for tests)."""
        self._config = config or EtfGridConfig()  # type: ignore[call-arg]  # required fields come from ETF_GRID_* env vars
        self._ledger = ledger_service or EtfGridLedgerService()
        self._candles = candle_service or EtfGridCandleService()
        self._valuation = valuation_service or EtfGridValuationService()
        self._signals = signal_service or EtfGridSignalService()
        super().__init__(
            name="etf_grid",
            tools=[self.get_grid_status, self.refresh_grid_data, self.record_grid_trade, self.list_grid_trades],
        )

    def get_grid_status(self) -> list[dict[str, Any]]:
        """Get the current ETF grid portfolio status.

        One entry per tracked symbol: ledger position (shares, average
        cost, realized P&L), latest close and market value, and the
        latest signal's advised limit orders (side, limit_price, grids,
        estimated shares, kind). Prices in orders are limit prices for
        intraday order placement; shares are estimates rounded to lots
        of 100. Read-only.
        """
        return to_jsonable(
            get_portfolio_status(
                config=self._config,
                ledger_service=self._ledger,
                candle_service=self._candles,
                signal_service=self._signals,
            )
        )

    def refresh_grid_data(self) -> dict[str, Any]:
        """Refresh all ETF grid data and recompute today's signals.

        Runs the full 3-step pipeline: (1) sync daily candles from
        FTShare, (2) sync the 930914 index valuation series from
        csindex, (3) recompute grid signals and limit-order advice from
        local data. Returns per-source row counts, the computed signals
        with their order lists, skipped symbols, and per-source errors
        (one source failing does not abort the others). Step 1 requires
        ETF_GRID_FTSHARE_API_KEY; if it is missing, the candles source
        reports an error while the rest still runs.
        """
        refresh = sync_market_data(config=self._config, candle_service=self._candles, valuation_service=self._valuation)
        signals = compute_daily_signals(
            config=self._config,
            ledger_service=self._ledger,
            candle_service=self._candles,
            valuation_service=self._valuation,
            signal_service=self._signals,
        )
        return to_jsonable({**refresh, **signals})

    def record_grid_trade(
        self,
        symbol: str,
        trade_date: str,
        side: str,
        price: str,
        quantity: int,
        commission_rate: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Record one executed ETF grid trade into the append-only ledger.

        Parameters: symbol as FTShare full code (e.g. '513330.XSHG'),
        trade_date as ISO date 'YYYY-MM-DD', side 'buy' or 'sell' (an
        opening-position backfill is a plain 'buy' — put the backfill
        semantics in note), price per share and commission_rate as
        decimal strings to preserve precision (e.g. '0.4100', '0.001'),
        quantity in shares. The system computes gross_amount, commission
        (rounded to cents) and net_amount; the response echoes the full
        persisted row so the user can verify the computed amounts in
        chat.
        """
        trade = self._ledger.record_trade(
            trade_date=date.fromisoformat(trade_date),
            symbol=symbol,
            side=Side(side),
            price=Decimal(price),
            quantity=quantity,
            commission_rate=Decimal(commission_rate),
            note=note,
            source=Source.AGENT,
        )
        return to_jsonable(trade)

    def list_grid_trades(self, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List recent ETF grid ledger trades, newest first.

        Optionally filter by symbol (FTShare full code). Each row
        carries trade_date, side, price, quantity and the
        system-computed gross_amount/commission/net_amount. limit
        defaults to 20.
        """
        rows = self._ledger.list_trades(symbol, order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)])
        return to_jsonable(rows[:limit])
