"""Grid strategy math for the ETF grid extension (pure, standard library only).

Ported from quant-advisor's ``backtest/bt_position.py`` — same inputs must
produce the same levels, signals, and triggers (parity is the acceptance
bar). All prices are :class:`decimal.Decimal`; no framework imports.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from spectres.extensions.etf_grid.core.ledger import OpenLot
from spectres.extensions.etf_grid.types import BlockReason, SignalAction

MA_WINDOW = 60
_FLOOR_EPSILON = Decimal("1e-9")  # guards float-style floor at exact grid boundaries


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
    """One computed daily signal snapshot (mirrors etf_grid_signals)."""

    symbol: str
    trade_date: date
    close: Decimal
    anchor_ma60: Decimal
    level: int
    prev_level: int
    action: SignalAction
    grids: int
    block_reason: BlockReason | None
    next_buy_trigger: Decimal | None
    next_sell_trigger: Decimal | None
    gate_metric_value: Decimal | None
    gate_percentile: Decimal | None
    gate_closed: bool | None


def compute_signal(inp: GridSignalInput, grid_step: Decimal) -> SignalSnapshot:
    """Replicate bt_position.report_symbol's decision logic for one day.

    Level-diff signal: ``diff = prev_level - level``; each dropped grid
    level buys one grid unit, each risen level sells one, executed at the
    next open. Sells are cost-protected: only lots whose
    ``entry x (1 + grid_step)`` is reachable at the current close qualify,
    and the cheapest lot's protection price can raise the next sell
    trigger above the grid boundary.
    """
    ratio = 1 + grid_step
    level = level_of(inp.close, inp.anchor, inp.max_grids, grid_step)
    prev_level = level_of(inp.prev_close, inp.prev_anchor, inp.max_grids, grid_step)
    n_lots = Decimal(inp.shares) * inp.close / inp.per_grid_amount
    n_sig = int(n_lots.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))

    diff = prev_level - level
    action = SignalAction.NONE
    grids = 0
    block_reason: BlockReason | None = None
    if diff > 0:
        n = min(diff, inp.max_grids - n_sig)
        if n > 0 and inp.gate is not None and inp.gate.closed:
            block_reason = BlockReason.GATE_CLOSED
        elif n > 0:
            action = SignalAction.BUY
            grids = n
        else:
            block_reason = BlockReason.MAX_GRIDS_REACHED
    elif diff < 0:
        n_qual = sum(1 for lot in inp.lots if lot.entry_price * ratio <= inp.close)
        n = min(-diff, n_sig, n_qual)
        if n > 0:
            action = SignalAction.SELL
            grids = n
        elif n_sig > 0 and n_qual == 0:
            block_reason = BlockReason.COST_PROTECTION
        else:
            block_reason = BlockReason.NO_POSITION

    next_buy_trigger = inp.anchor * ratio**level if level > -inp.max_grids and n_sig < inp.max_grids else None
    next_sell_trigger = None
    if n_sig > 0:
        grid_trig = inp.anchor * ratio ** (level + 1)
        cost_trig = inp.lots[0].entry_price * ratio
        next_sell_trigger = max(grid_trig, cost_trig)

    return SignalSnapshot(
        symbol=inp.symbol,
        trade_date=inp.trade_date,
        close=inp.close,
        anchor_ma60=inp.anchor,
        level=level,
        prev_level=prev_level,
        action=action,
        grids=grids,
        block_reason=block_reason,
        next_buy_trigger=next_buy_trigger,
        next_sell_trigger=next_sell_trigger,
        gate_metric_value=inp.gate.metric_value if inp.gate else None,
        gate_percentile=inp.gate.percentile if inp.gate else None,
        gate_closed=inp.gate.closed if inp.gate else None,
    )
