"""FastAPI request and response contracts for the ETF Grid extension."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TradeCreate(BaseModel):
    """Request body for POST /trades, mirroring the Ledger service inputs."""

    symbol: str
    trade_date: date
    side: Literal["buy", "sell"]
    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)
    commission_rate: Decimal = Field(ge=0)
    note: str | None = None
    commission: Decimal | None = Field(default=None, ge=0)
    net_amount: Decimal | None = Field(default=None, gt=0)


class TradeResponse(BaseModel):
    """One persisted trade in the owner's append-only ledger."""

    id: int
    user_id: str
    trade_date: str
    symbol: str
    side: str
    price: str
    quantity: int
    gross_amount: str
    commission_rate: str
    commission: str
    net_amount: str
    source: str
    note: str | None
    created_at: str


class TradeListResponse(BaseModel):
    """One filtered page of the current owner's trades."""

    items: list[TradeResponse]
    total: int
    limit: int
    offset: int


class OrderAdviceResponse(BaseModel):
    """One advised limit order in a computed signal."""

    side: str
    limit_price: str
    grids: int
    shares_est: int
    kind: str
    note: str | None


class SignalSnapshotResponse(BaseModel):
    """One newly computed signal returned by the compute operation."""

    user_id: str
    symbol: str
    trade_date: str
    close: str
    anchor_ma60: str
    level: int
    prev_level: int
    orders: list[OrderAdviceResponse]
    block_reason: str | None
    gate_metric_value: str | None
    gate_percentile: str | None
    gate_closed: bool | None


class StoredSignalResponse(SignalSnapshotResponse):
    """One persisted signal with its storage timestamp."""

    computed_at: str


class SignalComputationResponse(BaseModel):
    """Current-user signal results and per-symbol skip reasons."""

    signals: dict[str, SignalSnapshotResponse]
    skipped: dict[str, str]


class PortfolioStatusResponse(BaseModel):
    """One configured symbol in the current owner's portfolio status."""

    symbol: str
    name: str
    shares: int
    avg_cost: str | None
    realized: str
    close: str | None
    close_date: str | None
    market_value: str | None
    unrealized: str | None
    unrealized_percent: str | None
    signal: StoredSignalResponse | None


class MarketDataSyncResponse(BaseModel):
    """Shared-data synchronization counts and per-source failures."""

    candles: dict[str, int] | None
    valuation: int | None
    errors: dict[str, str]
