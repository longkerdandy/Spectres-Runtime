"""Shared enums and value objects for the ETF grid extension (standard library only)."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]+\.[A-Z]+")


def normalize_symbol(raw: str) -> str:
    """Normalize (strip + upper) and loosely validate an FTShare-style symbol.

    Only the ``<code>.<exchange>`` structure is enforced — the suffix value
    itself is deliberately unrestricted (beyond XSHG/XSHE, other exchanges
    may appear in the future).

    Raises:
        ValueError: If the symbol has no ``.SUFFIX`` form.
    """
    symbol = raw.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError(f"symbol must be FTShare-style '<code>.<exchange>', e.g. '513330.XSHG', got {raw!r}")
    return symbol


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


@dataclass(frozen=True)
class CandleInput:
    """One daily candle to upsert.

    Provider-agnostic: the marketdata layer translates FTShare bars into
    this shape; the service layer never sees provider specifics. ``symbol``
    is an FTShare-style full code (e.g. ``513330.XSHG``); the service
    normalizes (strip + upper) and validates it on write.
    """

    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
