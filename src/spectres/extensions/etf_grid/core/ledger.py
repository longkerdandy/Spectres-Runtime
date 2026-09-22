"""Trades ledger replay and trade amount computation for the ETF grid extension.

Ported from quant-advisor's ``backtest/bt_position.py`` (``replay_ledger``).
All arithmetic uses :class:`decimal.Decimal`; this module must stay free of
SQLAlchemy/pandas imports so it can be unit-tested in isolation.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from spectres.extensions.etf_grid.types import Side

MONEY_QUANTUM = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    """Round a monetary value to cents using ROUND_HALF_UP."""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TradeAmounts:
    """Derived monetary amounts for one ledger trade."""

    gross_amount: Decimal
    commission: Decimal
    net_amount: Decimal


def compute_trade_amounts(
    side: Side,
    price: Decimal,
    quantity: int,
    commission_rate: Decimal,
    commission: Decimal | None = None,
    net_amount: Decimal | None = None,
) -> TradeAmounts:
    """Compute gross/commission/net amounts for a trade.

    Rules: ``gross = price x quantity``; ``commission`` defaults to
    ``ROUND_HALF_UP(gross x commission_rate, 0.01)`` but can be overridden
    (e.g. broker minimum commissions); ``net = gross + commission`` for buys
    and ``gross - commission`` for sells, unless overridden.
    """
    gross_amount = quantize_money(price * quantity)
    if commission is None:
        commission = quantize_money(gross_amount * commission_rate)
    if net_amount is None:
        net_amount = gross_amount - commission if side is Side.SELL else gross_amount + commission
    return TradeAmounts(gross_amount=gross_amount, commission=commission, net_amount=net_amount)


@dataclass(frozen=True)
class LedgerTrade:
    """A single ledger entry, in replay (chronological) order."""

    trade_date: date
    side: Side
    quantity: int
    net_amount: Decimal


@dataclass(frozen=True)
class OpenLot:
    """One still-open purchase lot, paired cheapest-entry-first on sells."""

    entry_price: Decimal
    shares: int


@dataclass(frozen=True)
class Position:
    """Replayed position for one symbol."""

    shares: int
    avg_cost: Decimal | None
    realized: Decimal
    lots: tuple[OpenLot, ...]


@dataclass
class _MutableLot:
    entry_price: Decimal
    shares: int


def replay_ledger(trades: Iterable[LedgerTrade]) -> Position:
    """Replay an append-only ledger into the current position.

    Moving weighted-average cost: sells carry at the running average cost,
    where the cost basis of a buy is its ``net_amount`` (mathematically
    equal to the original script's ``price x shares + fee``). The open-lot
    queue is kept sorted by entry price ascending — the grid pairing order
    (on a rebound, the cheapest lot reaches its protected sell price —
    cost x (1 + grid step) — first; the step comes from strategy config).

    Args:
        trades: Ledger entries in chronological order.

    Returns:
        The replayed position (shares, average cost, realized P&L, open lots).

    Raises:
        ValueError: If a sell exceeds the held shares or the side is unknown.
    """
    shares = 0
    cost = Decimal(0)  # total cost basis of open shares
    realized = Decimal(0)
    lots: list[_MutableLot] = []
    for trade in trades:
        n = trade.quantity
        if trade.side is Side.BUY:
            cost += trade.net_amount
            shares += n
            lots.append(_MutableLot(entry_price=trade.net_amount / n, shares=n))
            lots.sort(key=lambda lot: lot.entry_price)
        elif trade.side is Side.SELL:
            if n > shares:
                raise ValueError(f"{trade.trade_date}: sell of {n} shares exceeds current holding of {shares} shares")
            avg = cost / shares
            realized += trade.net_amount - avg * n
            cost -= avg * n
            shares -= n
            left = n
            while left:  # consume cheapest-entry lots first
                if lots[0].shares <= left:
                    left -= lots.pop(0).shares
                else:
                    lots[0].shares -= left
                    left = 0
        else:
            raise ValueError(f"unknown trade side {trade.side!r}")
    avg_cost = cost / shares if shares else None
    return Position(
        shares=shares,
        avg_cost=avg_cost,
        realized=realized,
        lots=tuple(OpenLot(entry_price=lot.entry_price, shares=lot.shares) for lot in lots),
    )
