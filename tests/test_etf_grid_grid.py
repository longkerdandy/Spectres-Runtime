"""Unit tests for the ETF grid strategy math (core/grid.py)."""

from datetime import date
from decimal import Decimal

import pytest

from spectres.extensions.etf_grid.core.grid import (
    GateState,
    GridSignalInput,
    _tick_round,
    compute_signal,
    gate_state,
    level_of,
    moving_average,
)
from spectres.extensions.etf_grid.core.ledger import OpenLot
from spectres.extensions.etf_grid.types import BlockReason, OrderAdvice

pytestmark = pytest.mark.unit

STEP = Decimal("0.05")
RATIO = Decimal("1.05")


class TestTickRound:
    """Direction-aware tick rounding: never loosens the trigger condition."""

    def test_buy_rounds_down(self) -> None:
        """A buy limit never exceeds the raw boundary."""
        assert _tick_round(Decimal("1.2155"), "buy") == Decimal("1.215")

    def test_sell_rounds_up(self) -> None:
        """A sell limit never undercuts the raw boundary."""
        assert _tick_round(Decimal("1.2155"), "sell") == Decimal("1.216")

    def test_on_tick_unchanged(self) -> None:
        """Prices already on the 0.001 grid pass through."""
        assert _tick_round(Decimal("1.05"), "buy") == Decimal("1.050")
        assert _tick_round(Decimal("1.05"), "sell") == Decimal("1.050")


class TestMovingAverage:
    """MA60 semantics match pandas rolling(60).mean()."""

    def test_fewer_than_window_returns_none(self) -> None:
        """59 values cannot produce an MA60."""
        assert moving_average([Decimal(1)] * 59) is None

    def test_exact_window(self) -> None:
        """Exactly 60 values average all of them."""
        assert moving_average([Decimal(1), Decimal(2)] * 30) == Decimal("1.5")

    def test_uses_only_the_last_window_values(self) -> None:
        """Values before the window do not count."""
        values = [Decimal(100)] * 10 + [Decimal(1)] * 60
        assert moving_average(values) == Decimal(1)


class TestLevelOf:
    """Log-step grid levels vs the anchor, clamped to +/- cap."""

    def test_close_at_anchor_is_level_zero(self) -> None:
        """Close == base -> level 0."""
        assert level_of(Decimal("1.0000"), Decimal("1.0000"), 10, STEP) == 0

    def test_exact_grid_boundary_rounds_up(self) -> None:
        """Close == base x 1.05 exactly -> level +1 (epsilon guards the floor)."""
        assert level_of(Decimal("1.0500"), Decimal("1.0000"), 10, STEP) == 1

    def test_just_below_boundary_stays(self) -> None:
        """A hair below the boundary is still level 0."""
        assert level_of(Decimal("1.0499"), Decimal("1.0000"), 10, STEP) == 0

    def test_multiple_levels_up_and_down(self) -> None:
        """Close = base x 1.05^3 -> +3; close = base / 1.05 -> -1."""
        assert level_of(Decimal("1.157625"), Decimal("1.0000"), 10, STEP) == 3
        assert level_of(Decimal("1.0000") / RATIO, Decimal("1.0000"), 10, STEP) == -1

    def test_clamped_to_cap(self) -> None:
        """Levels never exceed +/- cap."""
        assert level_of(Decimal("2.0000"), Decimal("1.0000"), 2, STEP) == 2
        assert level_of(Decimal("0.1000"), Decimal("1.0000"), 2, STEP) == -2

    def test_invalid_anchor_is_level_zero(self) -> None:
        """A non-positive anchor yields level 0 (original's NaN guard)."""
        assert level_of(Decimal("1.0000"), Decimal("0"), 10, STEP) == 0
        assert level_of(Decimal("1.0000"), Decimal("-1"), 10, STEP) == 0


class TestGateState:
    """Percentile computation and both block directions."""

    def test_percentile_is_share_at_or_below_current(self) -> None:
        """Percentile = count(values <= current) / count."""
        state = gate_state([Decimal("0.04"), Decimal("0.05"), Decimal("0.03")], Decimal("0.20"), "below")
        assert state is not None
        assert state.metric_value == Decimal("0.03")
        assert state.percentile == Decimal(1) / 3

    def test_below_direction_closes_on_low_percentile(self) -> None:
        """block_when=below: percentile < threshold closes the gate (dyr)."""
        state = gate_state([Decimal("0.05")] * 5 + [Decimal("0.01")], Decimal("0.20"), "below")
        assert state is not None and state.closed
        state = gate_state([Decimal("0.01")] * 5 + [Decimal("0.05")], Decimal("0.20"), "below")
        assert state is not None and not state.closed

    def test_above_direction_closes_on_high_percentile(self) -> None:
        """block_when=above: percentile > threshold closes the gate (pe_ttm)."""
        state = gate_state([Decimal("10")] * 5 + [Decimal("20")], Decimal("0.80"), "above")
        assert state is not None and state.closed
        state = gate_state([Decimal("20")] * 5 + [Decimal("10")], Decimal("0.80"), "above")
        assert state is not None and not state.closed

    def test_threshold_boundary_is_not_closed(self) -> None:
        """Percentile == threshold exactly stays open (strict comparison)."""
        state = gate_state([Decimal("2"), Decimal("2"), Decimal("2"), Decimal("2"), Decimal("1")], Decimal("0.20"), "below")
        assert state is not None
        assert state.percentile == Decimal("0.2")
        assert not state.closed

    def test_empty_series_returns_none(self) -> None:
        """No usable metric values -> no gate state."""
        assert gate_state([], Decimal("0.20"), "below") is None


def _inp(**overrides: object) -> GridSignalInput:
    """Build a signal input with a flat anchor/level-0 baseline."""
    values: dict[str, object] = {
        "symbol": "513330.XSHG",
        "trade_date": date(2026, 9, 24),
        "close": Decimal("1.0000"),
        "prev_close": Decimal("1.0000"),
        "anchor": Decimal("1.0000"),
        "prev_anchor": Decimal("1.0000"),
        "shares": 0,
        "lots": (),
        "per_grid_amount": 10000,
        "max_grids": 10,
        "gate": None,
    }
    return GridSignalInput(**{**values, **overrides})  # type: ignore[arg-type]


class TestComputeSignal:
    """Level-diff decision logic with limit-order output (report_symbol port)."""

    def test_no_level_change_has_only_pending_orders(self) -> None:
        """Diff == 0 -> no triggered order, no block reason, pending orders remain."""
        signal = compute_signal(_inp(), STEP)
        assert signal.block_reason is None
        assert [(o.side, o.kind) for o in signal.orders] == [("buy", "pending")]

    def test_drop_aggregates_one_triggered_buy(self) -> None:
        """Falling 3 levels with an empty book -> ONE triggered buy for 3 grids."""
        signal = compute_signal(_inp(close=Decimal("0.9000")), STEP)
        assert signal.level == -3
        assert signal.prev_level == 0
        assert len(signal.orders) == 2
        triggered, pending = signal.orders
        # Triggered: aggregated 3 grids, limit at the highest crossed boundary
        # anchor x ratio^prev_level = 1.0 x 1.05^0 = 1.0000
        assert triggered.side == "buy"
        assert triggered.kind == "triggered"
        assert triggered.grids == 3
        assert triggered.limit_price == Decimal("1.0000")
        assert triggered.shares_est == 30000  # 3 x lot_shares(1.00) = 3 x 10000
        assert triggered.note is None
        # Pending buy: current level's lower boundary 1.0 x 1.05^-3
        assert pending.side == "buy"
        assert pending.kind == "pending"
        assert pending.grids == 1
        assert pending.limit_price == Decimal("0.863")  # 1.05^-3 = 0.86384 -> buy rounds DOWN
        assert pending.shares_est == 11600  # round(10000 / 0.863 / 100) x 100
        assert pending.note is None

    def test_gate_closed_keeps_pending_buy_with_note(self) -> None:
        """A closed gate blocks the triggered buy but the pending buy stays visible."""
        gate = GateState(metric_value=Decimal("0.01"), percentile=Decimal("0.1"), closed=True)
        signal = compute_signal(_inp(close=Decimal("0.9000"), gate=gate), STEP)
        assert signal.block_reason is BlockReason.GATE_CLOSED
        assert [(o.side, o.kind) for o in signal.orders] == [("buy", "pending")]
        assert signal.orders[0].note == "gate_closed"
        assert signal.gate_metric_value == Decimal("0.01")
        assert signal.gate_percentile == Decimal("0.1")
        assert signal.gate_closed is True

    def test_max_grids_reached_blocks_buy(self) -> None:
        """A full book (n_sig == max_grids) blocks further buys and the pending buy."""
        # 111200 shares x 0.90 / 10000 = 10.008 -> n_sig = 10 == max_grids
        lots = (OpenLot(entry_price=Decimal("1.0000"), shares=111200),)
        signal = compute_signal(_inp(close=Decimal("0.9000"), shares=111200, lots=lots), STEP)
        assert signal.block_reason is BlockReason.MAX_GRIDS_REACHED
        assert [(o.side, o.kind) for o in signal.orders] == [("sell", "pending")]
        pending_sell = signal.orders[0]
        # max(anchor x 1.05^-2 = 0.9070, cheapest cost 1.00 x 1.05 = 1.05) -> cost wins
        assert pending_sell.limit_price == Decimal("1.0000") * RATIO
        assert pending_sell.note == "cost_protection"

    def test_rise_sells_qualified_grids(self) -> None:
        """Rising 3 levels sells min(diff, n_sig, qualified lots) at the lowest crossed boundary."""
        lots = (OpenLot(entry_price=Decimal("1.0000"), shares=100000),)
        signal = compute_signal(_inp(close=Decimal("1.1600"), shares=100000, lots=lots), STEP)
        assert signal.level == 3
        triggered = signal.orders[0]
        assert triggered.side == "sell"
        assert triggered.kind == "triggered"
        # n_qual = 1 (one lot, entry x 1.05 = 1.05 <= 1.16) caps the sale
        assert triggered.grids == 1
        # max(anchor x 1.05^(0+1) = 1.05, sold-lot cost 1.00 x 1.05 = 1.05) -> tie, no note
        assert triggered.limit_price == RATIO
        assert triggered.note is None
        assert triggered.shares_est == 9500  # lot_shares(1.05) = round(95.238) x 100
        # Pending sell: grid boundary 1.05^4 = 1.21551 vs cost 1.05 -> grid wins, sell rounds UP to 1.216
        assert signal.orders[1] == OrderAdvice(side="sell", limit_price=Decimal("1.216"), grids=1, shares_est=8200, kind="pending", note=None)

    def test_triggered_sell_shares_capped_by_holdings(self) -> None:
        """shares_est never exceeds actual holdings (original's min(n x lot_shares, shares))."""
        lots = (
            OpenLot(entry_price=Decimal("0.9000"), shares=5000),
            OpenLot(entry_price=Decimal("1.0000"), shares=5000),
            OpenLot(entry_price=Decimal("1.1000"), shares=5000),
        )
        # n_sig = round(15000 x 1.16 / 10000) = 2; n_qual = 3 -> n = 2
        signal = compute_signal(_inp(close=Decimal("1.1600"), shares=15000, lots=lots), STEP)
        triggered = signal.orders[0]
        assert triggered.grids == 2
        # sold lots are the 2 cheapest; most expensive of them is 1.00 -> cost limit 1.05
        assert triggered.limit_price == RATIO
        assert triggered.shares_est == 15000  # 2 x 9500 = 19000 capped at 15000

    def test_cost_protection_blocks_sell(self) -> None:
        """No lot qualifies under cost protection -> no triggered sell + cost_protection."""
        lots = (OpenLot(entry_price=Decimal("1.1100"), shares=100000),)
        signal = compute_signal(_inp(close=Decimal("1.1600"), shares=100000, lots=lots), STEP)
        assert signal.block_reason is BlockReason.COST_PROTECTION
        assert [(o.side, o.kind) for o in signal.orders] == [("sell", "pending")]
        # At level 3 the grid boundary 1.05^4 = 1.21551 exceeds the lot's 1.1655 -> sell rounds UP
        assert signal.orders[0].limit_price == Decimal("1.216")
        assert signal.orders[0].note is None

    def test_no_position_blocks_sell(self) -> None:
        """A rise with an empty book -> no sell orders + no_position."""
        signal = compute_signal(_inp(close=Decimal("1.1600")), STEP)
        assert signal.block_reason is BlockReason.NO_POSITION
        assert [(o.side, o.kind) for o in signal.orders] == [("buy", "pending")]
        assert signal.orders[0].limit_price == Decimal("1.157")  # 1.05^3 = 1.15763 -> buy rounds DOWN

    def test_cheapest_lot_drives_pending_sell_limit(self) -> None:
        """The cheapest lot's cost x (1+step) can raise the pending sell limit."""
        lots = (OpenLot(entry_price=Decimal("1.0100"), shares=100000),)
        signal = compute_signal(_inp(close=Decimal("1.0000"), shares=100000, lots=lots), STEP)
        # grid boundary 1.05^1 = 1.05 < cheapest cost 1.01 x 1.05 = 1.0605 -> cost wins, sell rounds UP
        assert [(o.side, o.kind) for o in signal.orders] == [("sell", "pending")]
        assert signal.orders[0].limit_price == Decimal("1.061")
        assert signal.orders[0].note == "cost_protection"

    def test_gate_fields_none_without_gate(self) -> None:
        """Gateless symbols persist NULL gate fields."""
        signal = compute_signal(_inp(), STEP)
        assert signal.gate_metric_value is None
        assert signal.gate_percentile is None
        assert signal.gate_closed is None
