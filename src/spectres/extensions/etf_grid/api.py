"""FastAPI router adapter for the ETF grid extension (thin adapter, no business logic).

Mounted under ``/api/v1/extensions/etf-grid``.
Payloads go through ``service.to_jsonable`` so the HTTP surface serializes
identically to the toolkit surface.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from spectres.extensions.etf_grid.auth import require_admin_or_internal, require_user_id, require_user_or_internal
from spectres.extensions.etf_grid.config import EtfGridConfig, load_config, require_portfolio_symbol
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
    """Build the etf_grid API router with injectable services."""
    config = config or load_config()
    ledger = ledger_service or EtfGridLedgerService()
    candles = candle_service or EtfGridCandleService()
    valuation = valuation_service or EtfGridValuationService()
    signals = signal_service or EtfGridSignalService()

    router = APIRouter(prefix="/api/v1/extensions/etf-grid", tags=["etf-grid"])

    @router.get("/status")
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

    @router.post("/signals/compute")
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

    @router.post("/sync")
    def sync(request: Request) -> dict[str, Any]:
        require_user_or_internal(request)
        return to_jsonable(sync_market_data(config=config, candle_service=candles, valuation_service=valuation))

    @router.post("/refresh")
    def refresh(request: Request) -> dict[str, Any]:
        require_admin_or_internal(request)
        sync_result = sync_market_data(config=config, candle_service=candles, valuation_service=valuation)
        if sync_result["candles"] is None and sync_result["valuation"] is None:
            logger.error("refresh aborted: all data sources failed", extra={"event": "refresh_failed", "errors": sync_result["errors"]})
            raise HTTPException(status_code=502, detail=f"all data sources failed: {sync_result['errors']}")
        computed_users = 0
        errors: dict[str, str] = {}
        for user_id in ledger.list_user_ids():
            try:
                compute_daily_signals(
                    user_id=user_id,
                    config=config,
                    ledger_service=ledger,
                    candle_service=candles,
                    valuation_service=valuation,
                    signal_service=signals,
                )
                computed_users += 1
            except Exception as exc:
                errors[user_id] = f"{type(exc).__name__}: {exc}"
                logger.error("refresh: user signal computation failed", exc_info=exc, extra={"event": "refresh_user_failed", "user_id": user_id})
        logger.info(
            "refresh completed",
            extra={"event": "refresh_completed", "sync_errors": sync_result["errors"], "computed_users": computed_users, "user_errors": errors},
        )
        return to_jsonable({"sync": sync_result, "signals": {"computed_users": computed_users, "errors": errors}})

    @router.get("/trades")
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

    @router.post("/trades", status_code=201)
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
