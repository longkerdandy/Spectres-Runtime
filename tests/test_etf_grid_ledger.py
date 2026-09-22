"""Unit tests for the ETF grid trades ledger core and service validation."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint

from spectres.extensions.etf_grid.core.ledger import (
    LedgerTrade,
    OpenLot,
    compute_trade_amounts,
    replay_ledger,
)
from spectres.extensions.etf_grid.models import EtfGridBase
from spectres.extensions.etf_grid.service import _SORTABLE_COLUMNS, EtfGridLedgerService, _order_clauses
from spectres.extensions.etf_grid.types import Side, SortDirection, SortSpec, TradeSortField

pytestmark = pytest.mark.unit


def trade(day: int, side: Side, quantity: int, net: str) -> LedgerTrade:
    """Build a ledger trade for 2026-09-<day>."""
    return LedgerTrade(trade_date=date(2026, 9, day), side=side, quantity=quantity, net_amount=Decimal(net))


class TestComputeTradeAmounts:
    """Amount rules: gross = price x qty, commission ROUND_HALF_UP to cents."""

    def test_buy_amounts_match_historical_csv_row(self) -> None:
        """Buy amounts reproduce the historical 513120 CSV row."""
        amounts = compute_trade_amounts(Side.BUY, Decimal("1.2950"), 7800, Decimal("0.001"))
        assert amounts.gross_amount == Decimal("10101.00")
        assert amounts.commission == Decimal("10.10")
        assert amounts.net_amount == Decimal("10111.10")

    def test_commission_rounds_half_up(self) -> None:
        """Commission quantizes to cents with ROUND_HALF_UP, never float noise."""
        # 9963.00 x 0.001 = 9.963 -> 9.96 (third decimal below 5)
        amounts = compute_trade_amounts(Side.BUY, Decimal("9963.00"), 1, Decimal("0.001"))
        assert amounts.commission == Decimal("9.96")
        # 9965.00 x 0.001 = 9.965 -> 9.97 with ROUND_HALF_UP; a float pipeline
        # (9.964999...) or banker's rounding would produce 9.96
        amounts = compute_trade_amounts(Side.BUY, Decimal("9965.00"), 1, Decimal("0.001"))
        assert amounts.commission == Decimal("9.97")

    def test_sell_net_subtracts_commission(self) -> None:
        """Sell net amount is gross minus commission."""
        amounts = compute_trade_amounts(Side.SELL, Decimal("2.0000"), 100, Decimal("0.01"))
        assert amounts.gross_amount == Decimal("200.00")
        assert amounts.commission == Decimal("2.00")
        assert amounts.net_amount == Decimal("198.00")

    def test_commission_override_wins_over_rate(self) -> None:
        """An explicit commission overrides the rate-derived one."""
        amounts = compute_trade_amounts(Side.BUY, Decimal("1.0000"), 100, Decimal("0.001"), commission=Decimal("5.00"))
        assert amounts.commission == Decimal("5.00")
        assert amounts.net_amount == Decimal("105.00")

    def test_net_amount_override_wins(self) -> None:
        """An explicit net amount overrides the derived one."""
        amounts = compute_trade_amounts(Side.SELL, Decimal("1.0000"), 100, Decimal("0.001"), net_amount=Decimal("95.00"))
        assert amounts.commission == Decimal("0.10")
        assert amounts.net_amount == Decimal("95.00")


class TestReplayLedger:
    """Replay semantics ported from quant-advisor's replay_ledger."""

    def test_buys_accumulate_shares_cost_and_lots(self) -> None:
        """Every buy enters the cost basis and the lot queue at full weight."""
        position = replay_ledger(
            [
                trade(1, Side.BUY, 100, "100.00"),
                trade(2, Side.BUY, 100, "200.00"),
            ]
        )
        assert position.shares == 200
        assert position.avg_cost == Decimal("1.5")
        assert position.realized == Decimal(0)
        # Lots are kept sorted by entry price ascending (grid pairing order).
        assert position.lots == (
            OpenLot(entry_price=Decimal("1.00"), shares=100),
            OpenLot(entry_price=Decimal("2.00"), shares=100),
        )

    def test_lots_sorted_by_entry_price_not_insertion_order(self) -> None:
        """The lot queue is sorted by entry price ascending, not arrival order."""
        position = replay_ledger(
            [
                trade(1, Side.BUY, 100, "200.00"),
                trade(2, Side.BUY, 100, "100.00"),
            ]
        )
        assert [lot.entry_price for lot in position.lots] == [Decimal("1.00"), Decimal("2.00")]

    def test_sell_uses_weighted_average_cost(self) -> None:
        """Sells carry at the running weighted-average cost."""
        position = replay_ledger(
            [
                trade(1, Side.BUY, 100, "100.00"),
                trade(2, Side.BUY, 100, "200.00"),
                trade(3, Side.SELL, 50, "150.00"),
            ]
        )
        assert position.shares == 150
        assert position.avg_cost == Decimal("1.5")
        assert position.realized == Decimal("75.00")

    def test_sell_consumes_cheapest_lot_first(self) -> None:
        """The cheapest-entry lot is consumed first on a sell."""
        position = replay_ledger(
            [
                trade(1, Side.BUY, 100, "200.00"),
                trade(2, Side.BUY, 100, "100.00"),
                trade(3, Side.SELL, 150, "300.00"),
            ]
        )
        # The 100-share cheap lot is fully consumed, then 50 of the expensive one.
        assert position.lots == (OpenLot(entry_price=Decimal("2.00"), shares=50),)

    def test_sell_all_resets_average_cost(self) -> None:
        """A flat position has no average cost and no open lots."""
        position = replay_ledger(
            [
                trade(1, Side.BUY, 100, "100.00"),
                trade(2, Side.SELL, 100, "120.00"),
            ]
        )
        assert position.shares == 0
        assert position.avg_cost is None
        assert position.lots == ()
        assert position.realized == Decimal("20.00")

    def test_sell_exceeding_holding_raises(self) -> None:
        """Selling more than the current holding is rejected."""
        with pytest.raises(ValueError, match="exceeds current holding"):
            replay_ledger([trade(1, Side.BUY, 100, "100.00"), trade(2, Side.SELL, 101, "101.00")])

    def test_unknown_side_raises(self) -> None:
        """An unknown side is rejected at replay time (runtime robustness)."""
        with pytest.raises(ValueError, match="unknown trade side"):
            replay_ledger([trade(1, "hold", 100, "100.00")])  # type: ignore[arg-type]

    def test_real_csv_513330_ledger(self) -> None:
        """The historical 513330 rows (init mapped to buy) replay to the original position."""
        position = replay_ledger(
            [
                trade(19, Side.BUY, 24300, "9972.96"),
                trade(9, Side.BUY, 27700, "9954.24"),
                trade(10, Side.BUY, 28000, "9865.86"),
            ]
        )
        assert position.shares == 80000
        assert position.avg_cost == Decimal("0.37241325")
        assert position.realized == Decimal(0)
        assert [lot.shares for lot in position.lots] == [28000, 27700, 24300]
        assert position.lots[0].entry_price == Decimal("9865.86") / 28000


class TestModelConstraints:
    """The table DDL derives its side CHECK from the Side enum."""

    def test_side_check_constraint_matches_side_enum(self) -> None:
        """The CHECK constraint allows exactly the Side enum values (buy, sell)."""
        table = EtfGridBase.metadata.tables["etf_grid_trades"]
        constraint = next(c for c in table.constraints if isinstance(c, CheckConstraint))
        assert str(constraint.sqltext) == "side IN ('buy', 'sell')"


def _rendered(order_by: list[SortSpec] | None) -> list[str]:
    """Render ORDER BY clauses as SQL strings for assertion."""
    return [str(clause) for clause in _order_clauses(order_by)]


class TestListTradesOrdering:
    """list_trades translates SortSpec items into whitelisted ORDER BY clauses."""

    def test_default_order_is_replay_canonical(self) -> None:
        """None keeps the (symbol ASC, trade_date ASC, id ASC) replay order."""
        assert _rendered(None) == [
            "etf_grid_trades.symbol ASC",
            "etf_grid_trades.trade_date ASC",
            "etf_grid_trades.id ASC",
        ]

    def test_single_field_descending(self) -> None:
        """A single DESC key is followed by the id ASC stable suffix."""
        assert _rendered([SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)]) == [
            "etf_grid_trades.trade_date DESC",
            "etf_grid_trades.id ASC",
        ]

    def test_multi_field_mixed_directions(self) -> None:
        """Mixed-direction keys keep their relative order plus the id suffix."""
        assert _rendered(
            [
                SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC),
                SortSpec(TradeSortField.SYMBOL, SortDirection.ASC),
            ]
        ) == [
            "etf_grid_trades.trade_date DESC",
            "etf_grid_trades.symbol ASC",
            "etf_grid_trades.id ASC",
        ]

    def test_explicit_id_key_is_respected_not_duplicated(self) -> None:
        """A caller-provided id key suppresses the automatic stable suffix."""
        assert _rendered([SortSpec(TradeSortField.ID, SortDirection.DESC)]) == ["etf_grid_trades.id DESC"]

    def test_whitelist_covers_every_sort_field(self) -> None:
        """Every TradeSortField member resolves to a column (no bare strings)."""
        assert set(_SORTABLE_COLUMNS) == set(TradeSortField)


class _FailingSessionFactory:
    """Session factory that must never be called by validation-failure paths."""

    def __call__(self) -> None:
        """Fail loudly if the service touches the database on invalid input."""
        raise AssertionError("session factory must not be touched on validation failure")


class TestRecordTradeValidation:
    """record_trade rejects invalid numeric input before touching the database."""

    def service(self) -> EtfGridLedgerService:
        """Build a service whose session factory fails if ever called."""
        return EtfGridLedgerService(session_factory=_FailingSessionFactory())  # type: ignore[arg-type]

    def valid_kwargs(self) -> dict[str, object]:
        """Return a baseline of valid record_trade arguments."""
        return {
            "trade_date": date(2026, 9, 22),
            "symbol": "513330",
            "side": Side.BUY,
            "price": Decimal("0.4100"),
            "quantity": 24300,
            "commission_rate": Decimal("0.001"),
        }

    def test_non_positive_price(self) -> None:
        """A zero price is rejected."""
        with pytest.raises(ValueError, match="price must be positive"):
            self.service().record_trade(**{**self.valid_kwargs(), "price": Decimal("0")})  # type: ignore[arg-type]

    def test_non_positive_quantity(self) -> None:
        """A zero quantity is rejected."""
        with pytest.raises(ValueError, match="quantity must be positive"):
            self.service().record_trade(**{**self.valid_kwargs(), "quantity": 0})  # type: ignore[arg-type]

    def test_negative_commission_rate(self) -> None:
        """A negative commission rate is rejected."""
        with pytest.raises(ValueError, match="commission_rate must be non-negative"):
            self.service().record_trade(
                **{**self.valid_kwargs(), "commission_rate": Decimal("-0.001")}  # type: ignore[arg-type]
            )

    def test_negative_commission_override(self) -> None:
        """A negative commission override is rejected."""
        with pytest.raises(ValueError, match="commission must be non-negative"):
            self.service().record_trade(
                **{**self.valid_kwargs(), "commission": Decimal("-1")}  # type: ignore[arg-type]
            )

    def test_non_positive_net_amount_override(self) -> None:
        """A non-positive net amount override is rejected."""
        with pytest.raises(ValueError, match="net_amount must be positive"):
            self.service().record_trade(
                **{**self.valid_kwargs(), "net_amount": Decimal("0")}  # type: ignore[arg-type]
            )
