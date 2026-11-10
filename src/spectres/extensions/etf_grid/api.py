"""FastAPI router adapter for the ETF grid extension (thin adapter, no business logic).

Mounted under ``/api/v1/extensions/etf-grid``.
Payloads go through ``service.to_jsonable`` so the HTTP surface serializes
identically to the toolkit surface.
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError

from spectres.extensions.etf_grid.auth import require_user_id, require_user_or_internal
from spectres.extensions.etf_grid.config import EtfGridConfig, load_config, require_portfolio_symbol
from spectres.extensions.etf_grid.marketdata import sync_market_data
from spectres.extensions.etf_grid.schemas import MarketDataSyncResponse, PortfolioStatusResponse, SignalComputationResponse, TradeCreate, TradeListResponse, TradeResponse
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


def create_router(
    *,
    config: EtfGridConfig | None = None,
    ledger_service: EtfGridLedgerService,
    candle_service: EtfGridCandleService,
    valuation_service: EtfGridValuationService,
    signal_service: EtfGridSignalService,
) -> APIRouter:
    """Build the etf_grid API router with injectable services."""
    config = config or load_config()
    ledger = ledger_service
    candles = candle_service
    valuation = valuation_service
    signals = signal_service

    router = APIRouter(prefix="/api/v1/extensions/etf-grid", tags=["etf-grid"])

    @router.get("/status", response_model=list[PortfolioStatusResponse])
    def get_status(request: Request) -> list[dict[str, Any]]:
        user_id = require_user_id(request)
        return to_jsonable(
            get_portfolio_status(
                user_id=user_id,
                config=config,
                ledger_service=ledger,
                candle_service=candles,
                signal_service=signals,
            )
        )

    @router.post("/signals/compute", response_model=SignalComputationResponse)
    def compute_signals(request: Request) -> dict[str, Any]:
        user_id = require_user_id(request)
        return to_jsonable(
            compute_daily_signals(
                user_id=user_id,
                config=config,
                ledger_service=ledger,
                candle_service=candles,
                valuation_service=valuation,
                signal_service=signals,
            )
        )

    @router.post("/sync", response_model=MarketDataSyncResponse)
    def sync(request: Request) -> dict[str, Any]:
        require_user_or_internal(request)
        return to_jsonable(sync_market_data(config=config, candle_service=candles, valuation_service=valuation))

    @router.get("/trades", response_model=TradeListResponse)
    def get_trades(
        request: Request,
        symbol: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = Query(default=20, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        user_id = require_user_id(request)
        rows = ledger.list_trades(
            symbol,
            user_id=user_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
            order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)],
        )
        total = ledger.count_trades(symbol, user_id=user_id, start=start, end=end)
        return {"items": to_jsonable(rows), "total": total, "limit": limit, "offset": offset}

    @router.post("/trades", status_code=201, response_model=TradeResponse)
    def create_trade(body: TradeCreate, request: Request) -> dict[str, Any]:
        user_id = require_user_id(request)
        try:
            symbol = require_portfolio_symbol(config, body.symbol)
            trade = ledger.record_trade(
                user_id=user_id,
                trade_date=body.trade_date,
                symbol=symbol,
                side=Side(body.side),
                price=body.price,
                quantity=body.quantity,
                commission_rate=body.commission_rate,
                note=body.note,
                commission=body.commission,
                net_amount=body.net_amount,
            )
        except ValueError as exc:
            safe_symbol = body.symbol.replace("\r", "").replace("\n", "")
            logger.warning("trade rejected as invalid; converted to 422", extra={"event": "trade_rejected", "user_id": user_id, "symbol": safe_symbol, "error": str(exc)})
            raise RequestValidationError(errors=[{"loc": ("body",), "msg": str(exc), "type": "value_error"}]) from exc
        return to_jsonable(trade)

    return router
