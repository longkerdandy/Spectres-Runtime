"""Shared enums and value objects for the ETF grid extension (standard library only)."""

from dataclasses import dataclass
from enum import StrEnum


class Side(StrEnum):
    """Trade side in the ledger."""

    BUY = "buy"
    SELL = "sell"


class Source(StrEnum):
    """Provenance of a ledger record."""

    MANUAL = "manual"
    AGENT = "agent"


class TradeSortField(StrEnum):
    """Ledger columns that list_trades can sort by (whitelist)."""

    ID = "id"
    TRADE_DATE = "trade_date"
    SYMBOL = "symbol"
    SIDE = "side"
    PRICE = "price"
    QUANTITY = "quantity"
    GROSS_AMOUNT = "gross_amount"
    COMMISSION = "commission"
    NET_AMOUNT = "net_amount"
    CREATED_AT = "created_at"


class SortDirection(StrEnum):
    """Sort direction for a SortSpec."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class SortSpec:
    """One sort key: a whitelisted field plus a direction (asc by default)."""

    field: TradeSortField
    direction: SortDirection = SortDirection.ASC
