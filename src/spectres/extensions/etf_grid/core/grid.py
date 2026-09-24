"""Grid strategy math for the ETF grid extension (pure, standard library only).

Ported from quant-advisor's ``backtest/bt_position.py`` — same inputs must
produce the same levels, signals, and triggers (parity is the acceptance
bar). All prices are :class:`decimal.Decimal`; no framework imports.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_UP, Decimal

from spectres.extensions.etf_grid.core.ledger import OpenLot
from spectres.extensions.etf_grid.types import BlockReason, OrderAdvice

MA_WINDOW = 60
ROUND_LOT = 100  # ETF minimum trading unit (shares)
_FLOOR_EPSILON = Decimal("1e-9")  # guards float-style floor at exact grid boundaries
PRICE_TICK = Decimal("0.001")  # A-share ETF minimum price increment


def _tick_round(price: Decimal, side: str) -> Decimal:
    """Round a limit price to the tick grid without loosening the trigger.

    Buy limits round DOWN (a lower bid never exceeds the intended
    boundary), sell limits round UP — the stored limit is directly
    placeable at the exchange.
    """
    return price.quantize(PRICE_TICK, rounding=ROUND_DOWN if side == "buy" else ROUND_UP)


def moving_average(values: Sequence[Decimal], window: int = MA_WINDOW) -> Decimal | None:
    """Mean of the last ``window`` values; None when fewer values exist.

    Equivalent to pandas ``rolling(window).mean()`` on the close series.
    """
    if len(values) < window:
        return None
    return sum(values[-window:], Decimal(0)) / window


def level_of(close: Decimal, base: Decimal, cap: int, grid_step: Decimal) -> int:
    """Grid level of ``close`` vs anchor ``base``, clamped to +/- ``cap``.

    Log-step levels: ``floor(log(close / base) / log(1 + grid_step))`` with
    the original's 1e-9 epsilon guarding the floor at exact boundaries.
    Returns 0 when the anchor is invalid (<= 0), matching the original's
    NaN/non-positive guard.
    """
    if base <= 0:
        return 0
    ratio = 1 + grid_step
    raw = (close / base).ln() / ratio.ln() + _FLOOR_EPSILON
    level = int(raw.to_integral_value(rounding=ROUND_FLOOR))
    return max(-cap, min(cap, level))


@dataclass(frozen=True)
class GateState:
    """Valuation gate state for one symbol at the latest valuation row."""

    metric_value: Decimal
    percentile: Decimal
    closed: bool


def gate_state(values: Sequence[Decimal], threshold: Decimal, block_when: str) -> GateState | None:
    """Compute the valuation gate state from the metric series.

    ``values`` is the full metric history with NULLs already removed,
    oldest first. Percentile = share of values <= the current value.
    ``block_when='below'`` closes the gate when the percentile is under the
    threshold (dividend yield: low yield = expensive); ``'above'`` closes
    it when over (PE: high PE = expensive). Returns None for an empty
    series.
    """
    if not values:
        return None
    current = values[-1]
    percentile = Decimal(sum(1 for v in values if v <= current)) / len(values)
    closed = percentile < threshold if block_when == "below" else percentile > threshold
    return GateState(metric_value=current, percentile=percentile, closed=closed)


@dataclass(frozen=True)
class GridSignalInput:
    """Everything needed to compute one symbol's daily signal."""

    symbol: str
    trade_date: date
    close: Decimal
    prev_close: Decimal
    anchor: Decimal
    prev_anchor: Decimal
    shares: int
    lots: tuple[OpenLot, ...]
    per_grid_amount: int
    max_grids: int
    gate: GateState | None


@dataclass(frozen=True)
class SignalSnapshot:
    """One computed daily signal snapshot (mirrors etf_grid_signals).

    The snapshot carries the grid state (levels, anchor, block reason,
    gate fields) plus the advised limit orders. Execution model: limit
    orders at grid boundaries instead of the backtest's next-open fills —
    an owner-approved deviation from the backtest convention.
    """

    symbol: str
    trade_date: date
    close: Decimal
    anchor_ma60: Decimal
    level: int
    prev_level: int
    orders: tuple[OrderAdvice, ...]
    block_reason: BlockReason | None
    gate_metric_value: Decimal | None
    gate_percentile: Decimal | None
    gate_closed: bool | None


def lot_shares(price: Decimal, per_grid_amount: int) -> int:
    """Estimated shares per grid at ``price``, rounded to round lots of 100.

    The original's ``round(per_grid_amount / price / ROUND_LOT) * ROUND_LOT``
    (Python ``round`` = ROUND_HALF_EVEN, mirrored here on Decimal).
    """
    lots = (Decimal(per_grid_amount) / price / ROUND_LOT).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return int(lots) * ROUND_LOT


def compute_signal(inp: GridSignalInput, grid_step: Decimal) -> SignalSnapshot:
    """Replicate bt_position.report_symbol's decision logic for one day.

    The diff/block_reason logic is identical to the original: each dropped
    grid level buys one grid unit, each risen level sells one; sells are
    cost-protected (only lots whose ``entry x (1 + grid_step)`` is reachable
    at the current close qualify). The output is a limit-order list instead
    of next-open advice (owner-approved execution-model deviation):

    - Triggered buy (diff > 0, gate open): one aggregated order for all
      ``n = min(diff, max_grids - n_sig)`` grids, limit at the HIGHEST
      crossed boundary ``anchor x ratio**prev_level``.
    - Pending buy: 1 grid at the current level's lower boundary
      ``anchor x ratio**level``, while ``level > -max_grids`` and
      ``n_sig < max_grids``; kept visible with ``note='gate_closed'``
      when the gate blocks it.
    - Triggered sell (diff < 0): the ``n = min(-diff, n_sig, n_qual)``
      cheapest qualifying lots, limit at the LOWEST crossed boundary
      ``anchor x ratio**(prev_level+1)`` raised to the most expensive sold
      lot's protection price when that dominates (note='cost_protection').
    - Pending sell: 1 grid at ``max(anchor x ratio**(level+1),
      cheapest_lot x ratio)`` while ``n_sig > 0`` (note='cost_protection'
      when the cost term dominates, same as the original's note).

    Orders are emitted triggered-first, then pending buy, then pending sell.
    All limit prices are tick-rounded (0.001) direction-aware — buy limits
    down, sell limits up — so the stored price is directly placeable and
    the rounding can never loosen the trigger condition.
    """
    ratio = 1 + grid_step
    level = level_of(inp.close, inp.anchor, inp.max_grids, grid_step)
    prev_level = level_of(inp.prev_close, inp.prev_anchor, inp.max_grids, grid_step)
    n_lots = Decimal(inp.shares) * inp.close / inp.per_grid_amount
    n_sig = int(n_lots.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
    gate_closed = inp.gate is not None and inp.gate.closed

    diff = prev_level - level
    block_reason: BlockReason | None = None
    orders: list[OrderAdvice] = []
    if diff > 0:
        n = min(diff, inp.max_grids - n_sig)
        if n > 0 and gate_closed:
            block_reason = BlockReason.GATE_CLOSED
        elif n > 0:
            limit = _tick_round(inp.anchor * ratio**prev_level, "buy")
            orders.append(OrderAdvice(side="buy", limit_price=limit, grids=n, shares_est=n * lot_shares(limit, inp.per_grid_amount), kind="triggered", note=None))
        else:
            block_reason = BlockReason.MAX_GRIDS_REACHED
    elif diff < 0:
        n_qual = sum(1 for lot in inp.lots if lot.entry_price * ratio <= inp.close)
        n = min(-diff, n_sig, n_qual)
        if n > 0:
            grid_limit = inp.anchor * ratio ** (prev_level + 1)
            cost_limit = inp.lots[n - 1].entry_price * ratio  # most expensive of the n cheapest qualifying lots
            limit = _tick_round(max(grid_limit, cost_limit), "sell")
            orders.append(
                OrderAdvice(
                    side="sell",
                    limit_price=limit,
                    grids=n,
                    shares_est=min(n * lot_shares(limit, inp.per_grid_amount), inp.shares),
                    kind="triggered",
                    note="cost_protection" if cost_limit > grid_limit else None,
                )
            )
        elif n_sig > 0 and n_qual == 0:
            block_reason = BlockReason.COST_PROTECTION
        else:
            block_reason = BlockReason.NO_POSITION

    if level > -inp.max_grids and n_sig < inp.max_grids:
        limit = _tick_round(inp.anchor * ratio**level, "buy")
        orders.append(
            OrderAdvice(
                side="buy",
                limit_price=limit,
                grids=1,
                shares_est=lot_shares(limit, inp.per_grid_amount),
                kind="pending",
                note="gate_closed" if gate_closed else None,
            )
        )
    if n_sig > 0:
        grid_limit = inp.anchor * ratio ** (level + 1)
        cost_limit = inp.lots[0].entry_price * ratio
        limit = _tick_round(max(grid_limit, cost_limit), "sell")
        orders.append(
            OrderAdvice(
                side="sell",
                limit_price=limit,
                grids=1,
                shares_est=min(lot_shares(limit, inp.per_grid_amount), inp.shares),
                kind="pending",
                note="cost_protection" if cost_limit > grid_limit else None,
            )
        )

    return SignalSnapshot(
        symbol=inp.symbol,
        trade_date=inp.trade_date,
        close=inp.close,
        anchor_ma60=inp.anchor,
        level=level,
        prev_level=prev_level,
        orders=tuple(orders),
        block_reason=block_reason,
        gate_metric_value=inp.gate.metric_value if inp.gate else None,
        gate_percentile=inp.gate.percentile if inp.gate else None,
        gate_closed=inp.gate.closed if inp.gate else None,
    )
