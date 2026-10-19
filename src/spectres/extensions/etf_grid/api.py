"""FastAPI router adapter for the ETF grid extension (thin adapter, no business logic).

Mounted under ``/api/v1/extensions/etf-grid`` (runtime-extensions.md §6.4).
Payloads go through ``service.to_jsonable`` so the HTTP surface serializes
identically to the toolkit surface.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from spectres.extensions.etf_grid.config import EtfGridConfig, load_config
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
from spectres.extensions.etf_grid.types import Side, SortDirection, SortSpec, TradeSortField

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
    config = config or load_config()
    ledger = ledger_service or EtfGridLedgerService()
    candles = candle_service or EtfGridCandleService()
    valuation = valuation_service or EtfGridValuationService()
    signals = signal_service or EtfGridSignalService()

    router = APIRouter(prefix="/api/v1/extensions/etf-grid", tags=["etf-grid"])

    @router.get("/status")
    def get_status() -> list[dict[str, Any]]:
        """Portfolio status per symbol: ledger position, latest close/market value, and the latest signal's limit orders."""
        return to_jsonable(get_portfolio_status(config=config, ledger_service=ledger, candle_service=candles, signal_service=signals))

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

    @router.post("/refresh")
    def refresh() -> dict[str, Any]:
        """Composite sync + compute, the schedule-facing route.

        Unlike ``/sync``, the HTTP status participates in the contract
        because the scheduler treats 2xx as success:

        - all data sources failed -> 502 (nothing usable; scheduler retries);
        - signal computation raised -> 500;
        - partial source failure -> 200 with the per-source ``errors``
          carried inside ``sync`` (partial data is still worth computing
          signals over).
        """
        sync_result = sync_market_data(config=config, candle_service=candles, valuation_service=valuation)
        if sync_result["candles"] is None and sync_result["valuation"] is None:
            logger.error("refresh aborted: all data sources failed", extra={"event": "refresh_failed", "errors": sync_result["errors"]})
            raise HTTPException(status_code=502, detail=f"all data sources failed: {sync_result['errors']}")
        try:
            compute_result = compute_daily_signals(
                config=config,
                ledger_service=ledger,
                candle_service=candles,
                valuation_service=valuation,
                signal_service=signals,
            )
        except Exception as exc:
            logger.error("refresh: signal computation failed", exc_info=exc, extra={"event": "refresh_failed"})
            raise
        logger.info("refresh completed", extra={"event": "refresh_completed", "sync_errors": sync_result["errors"]})
        return to_jsonable({"sync": sync_result, "signals": compute_result})

    @router.get("/trades")
    def get_trades(symbol: str | None = None, start: date | None = None, end: date | None = None, limit: int = Query(default=20, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
        """Ledger query: newest trades first, optionally filtered by symbol and trade-date range.

        Returns the pagination envelope ``{"items", "total", "limit", "offset"}``;
        ``total`` counts all matching rows independently of the requested page.
        """
        rows = ledger.list_trades(
            symbol,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
            order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)],
        )
        total = ledger.count_trades(symbol, start=start, end=end)
        return {"items": to_jsonable(rows), "total": total, "limit": limit, "offset": offset}

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
            # RequestValidationError, not HTTPException: AgentOS installs a global
            # HTTPException handler that renders detail via str(exc.detail), which
            # would stringify the list. The RequestValidationError path is FastAPI's
            # native one and keeps the list-of-objects shape, so every 422 from this
            # router shares one contract (loc/msg/type guaranteed; native errors may
            # add input/url). See runtime-extensions.md §7.
            raise RequestValidationError(errors=[{"loc": ("body",), "msg": str(exc), "type": "value_error"}]) from exc
        return to_jsonable(trade)

    return router
