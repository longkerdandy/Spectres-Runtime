"""Unit tests for the ETF grid strategy math (core/grid.py)."""

from datetime import date
from decimal import Decimal

import pytest

from spectres.extensions.etf_grid.core.grid import (
    GateState,
    GridSignalInput,
    compute_signal,
    gate_state,
    level_of,
    moving_average,
)
from spectres.extensions.etf_grid.core.ledger import OpenLot
from spectres.extensions.etf_grid.types import BlockReason, SignalAction

pytestmark = pytest.mark.unit

STEP = Decimal("0.05")
RATIO = Decimal("1.05")


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
    """Level-diff decision logic ported from report_symbol."""

    def test_no_level_change_is_none_without_block(self) -> None:
        """Diff == 0 -> action none, grids 0, no block reason."""
        signal = compute_signal(_inp(), STEP)
        assert signal.action is SignalAction.NONE
        assert signal.grids == 0
        assert signal.block_reason is None

    def test_drop_buys_diff_grids(self) -> None:
        """Falling 3 levels with an empty book buys 3 grids."""
        signal = compute_signal(_inp(close=Decimal("0.9000")), STEP)
        assert signal.level == -3
        assert signal.prev_level == 0
        assert signal.action is SignalAction.BUY
        assert signal.grids == 3
        assert signal.next_buy_trigger == Decimal("1.0000") * RATIO**-3
        assert signal.next_sell_trigger is None  # no position

    def test_gate_closed_blocks_buy(self) -> None:
        """A closed gate turns a would-be buy into none + gate_closed."""
        gate = GateState(metric_value=Decimal("0.01"), percentile=Decimal("0.1"), closed=True)
        signal = compute_signal(_inp(close=Decimal("0.9000"), gate=gate), STEP)
        assert signal.action is SignalAction.NONE
        assert signal.grids == 0
        assert signal.block_reason is BlockReason.GATE_CLOSED
        assert signal.gate_metric_value == Decimal("0.01")
        assert signal.gate_percentile == Decimal("0.1")
        assert signal.gate_closed is True

    def test_max_grids_reached_blocks_buy(self) -> None:
        """A full book (n_sig == max_grids) blocks further buys."""
        # 111200 shares x 0.90 / 10000 = 10.008 -> n_sig = 10 == max_grids
        lots = (OpenLot(entry_price=Decimal("1.0000"), shares=111200),)
        signal = compute_signal(_inp(close=Decimal("0.9000"), shares=111200, lots=lots), STEP)
        assert signal.action is SignalAction.NONE
        assert signal.block_reason is BlockReason.MAX_GRIDS_REACHED
        assert signal.next_buy_trigger is None

    def test_rise_sells_qualified_grids(self) -> None:
        """Rising 3 levels sells min(diff, n_sig, qualified lots)."""
        lots = (OpenLot(entry_price=Decimal("1.0000"), shares=100000),)
        signal = compute_signal(_inp(close=Decimal("1.1600"), shares=100000, lots=lots), STEP)
        assert signal.level == 3
        assert signal.action is SignalAction.SELL
        # n_qual = 1 (one lot, entry x 1.05 = 1.05 <= 1.16) caps the sale
        assert signal.grids == 1
        # next sell trigger: grid boundary 1.05^4 vs cost 1.05 -> grid wins
        assert signal.next_sell_trigger == RATIO**4

    def test_cost_protection_blocks_sell(self) -> None:
        """No lot qualifies under cost protection -> none + cost_protection."""
        lots = (OpenLot(entry_price=Decimal("1.1100"), shares=100000),)
        signal = compute_signal(_inp(close=Decimal("1.1600"), shares=100000, lots=lots), STEP)
        assert signal.action is SignalAction.NONE
        assert signal.block_reason is BlockReason.COST_PROTECTION
        # Protection blocks the sale today, but at level 3 the grid boundary
        # 1.05^4 = 1.21550625 still exceeds the lot's 1.1655 protection price
        assert signal.next_sell_trigger == RATIO**4

    def test_no_position_blocks_sell(self) -> None:
        """A rise with an empty book -> none + no_position."""
        signal = compute_signal(_inp(close=Decimal("1.1600")), STEP)
        assert signal.action is SignalAction.NONE
        assert signal.block_reason is BlockReason.NO_POSITION
        assert signal.next_sell_trigger is None

    def test_cheapest_lot_drives_sell_trigger(self) -> None:
        """The cheapest lot's cost x (1+step) can raise the sell trigger above the grid boundary."""
        lots = (OpenLot(entry_price=Decimal("1.0100"), shares=100000),)
        signal = compute_signal(_inp(close=Decimal("1.0000"), shares=100000, lots=lots), STEP)
        # grid boundary 1.05^1 = 1.05 < cheapest cost 1.01 x 1.05 = 1.0605 -> cost wins
        assert signal.next_sell_trigger == Decimal("1.0100") * RATIO

    def test_gate_fields_none_without_gate(self) -> None:
        """Gateless symbols persist NULL gate fields."""
        signal = compute_signal(_inp(), STEP)
        assert signal.gate_metric_value is None
        assert signal.gate_percentile is None
        assert signal.gate_closed is None
