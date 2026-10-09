"""FastAPI router adapter for the ETF grid extension (thin adapter, no business logic).

Mounted under ``/api/v1/extensions/etf-grid`` (runtime-extensions.md §6.4).
Payloads go through ``service.to_jsonable`` so the HTTP surface serializes
identically to the toolkit surface.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
from spectres.extensions.etf_grid.types import Side, SignalSortField, SortDirection, SortSpec, TradeSortField

logger = logging.getLogger(__name__)


class TradeCreate(BaseModel):
    """Request body for POST /trades, mirroring ``service.record_trade``'s signature."""

    symbol: str
    trade_date: date
    side: Literal["buy", "sell"]
    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)
    commission_rate: Decimal = Field(ge=0)
    note: str | None = None
    commission: Decimal | None = Field(default=None, ge=0)
    net_amount: Decimal | None = Field(default=None, gt=0)


def create_router(
    *,
    config: EtfGridConfig | None = None,
    ledger_service: EtfGridLedgerService | None = None,
    candle_service: EtfGridCandleService | None = None,
    valuation_service: EtfGridValuationService | None = None,
    signal_service: EtfGridSignalService | None = None,
) -> APIRouter:
    """Build the etf_grid API router; services default to shared instances (injectable for tests)."""
    config = config or EtfGridConfig()  # type: ignore[call-arg]  # required fields come from ETF_GRID_* env vars
    ledger = ledger_service or EtfGridLedgerService()
    candles = candle_service or EtfGridCandleService()
    valuation = valuation_service or EtfGridValuationService()
    signals = signal_service or EtfGridSignalService()

    router = APIRouter(prefix="/api/v1/extensions/etf-grid", tags=["etf-grid"])

    @router.get("/status")
    def get_status() -> list[dict[str, Any]]:
        """Portfolio status per symbol: ledger position, latest close/market value, and the latest signal's limit orders."""
        return to_jsonable(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals))

    @router.get("/signals")
    def get_signals(symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Signal history with order lists, newest first; optionally filtered by symbol."""
        rows = signals.list_signals(symbol, order_by=[SortSpec(SignalSortField.TRADE_DATE, SortDirection.DESC)])
        return to_jsonable(rows[:limit])

    @router.post("/signals/compute")
    def compute_signals() -> dict[str, Any]:
        """Recompute daily signals from local data only (no network calls)."""
        return to_jsonable(
            compute_daily_signals(
                config=config,
                ledger_service=ledger,
                candle_service=candles,
                valuation_service=valuation,
                signal_service=signals,
            )
        )

    @router.post("/sync")
    def sync() -> dict[str, Any]:
        """Network refresh (candles from FTShare + valuation from csindex).

        Provider failures are reported per source in the response body
        (``errors``) instead of producing a 500.
        """
        return to_jsonable(sync_market_data(config=config, candle_service=candles, valuation_service=valuation))

    @router.get("/trades")
    def get_trades(symbol: str | None = None, start: date | None = None, end: date | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Ledger query: newest trades first, optionally filtered by symbol and trade-date range."""
        rows = ledger.list_trades(symbol, order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)])
        if start is not None:
            rows = [row for row in rows if row["trade_date"] >= start]
        if end is not None:
            rows = [row for row in rows if row["trade_date"] <= end]
        return to_jsonable(rows[:limit])

    @router.post("/trades", status_code=201)
    def create_trade(body: TradeCreate) -> dict[str, Any]:
        """Record one executed trade; echoes the persisted row with the system-computed amounts."""
        try:
            trade = ledger.record_trade(
                trade_date=body.trade_date,
                symbol=body.symbol,
                side=Side(body.side),
                price=body.price,
                quantity=body.quantity,
                commission_rate=body.commission_rate,
                note=body.note,
                commission=body.commission,
                net_amount=body.net_amount,
            )
        except ValueError as exc:
            logger.warning("trade rejected as invalid; converted to 422", extra={"event": "trade_rejected", "symbol": body.symbol, "error": str(exc)})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return to_jsonable(trade)

    return router
