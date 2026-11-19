"""Service-level tests for etf_grid portfolio status derivation."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.core.ledger import Position
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    get_portfolio_status,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def config() -> EtfGridConfig:
    """Portfolio config from .env.test (513330 / 513120 / 513530)."""
    return EtfGridConfig()  # type: ignore[call-arg]  # required fields come from .env.test


def _status_row(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    """Return the status row for one symbol."""
    return next(row for row in rows if row["symbol"] == symbol)


class _FakeLedgerService(EtfGridLedgerService):
    """In-memory ledger stand-in returning canned positions (no database)."""

    def __init__(self, positions: dict[str, Position]) -> None:
        """Set up with canned positions."""
        self._positions = positions

    def get_positions(self, *, user_id: str) -> dict[str, Position]:
        """Return the canned positions."""
        return self._positions


class _FakeCandleService(EtfGridCandleService):
    """In-memory candle stand-in counting latest_candles calls (no database)."""

    def __init__(self, latest: dict[str, dict[str, Any]]) -> None:
        """Set up with canned latest rows."""
        self._latest = latest
        self.calls = 0

    def latest_candles(self, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Return the canned latest rows."""
        self.calls += 1
        return self._latest


class _FakeSignalService(EtfGridSignalService):
    """In-memory signal stand-in counting latest_signals calls (no database)."""

    def __init__(self, latest: dict[str, dict[str, Any]]) -> None:
        """Set up with canned latest rows."""
        self._latest = latest
        self.calls = 0

    def latest_signals(self, symbols: Sequence[str], *, user_id: str) -> dict[str, dict[str, Any]]:
        """Return the canned latest rows."""
        self.calls += 1
        return self._latest


class TestGetPortfolioStatusBulkQueries:
    """get_portfolio_status folds per-symbol latest-row lookups into one bulk query each."""

    def test_bulk_queries_and_derived_fields(self, config: EtfGridConfig) -> None:
        """Each bulk method is called once; derived P&L fields match hand computation."""
        positions = {"513330.XSHG": Position(shares=1000, avg_cost=Decimal("0.5000"), realized=Decimal("2.00"), lots=())}
        candles = _FakeCandleService({"513330.XSHG": {"trade_date": date(2026, 9, 2), "close": Decimal("0.6000")}})
        signals = _FakeSignalService({"513330.XSHG": {"level": -3}})
        status = get_portfolio_status(user_id="alice", ledger_service=_FakeLedgerService(positions), candle_service=candles, signal_service=signals, config=config)
        assert candles.calls == 1
        assert signals.calls == 1
        row = _status_row(status, "513330.XSHG")
        assert row["shares"] == 1000
        assert row["close"] == Decimal("0.6000")
        assert row["close_date"] == date(2026, 9, 2)
        assert row["market_value"] == Decimal("600.0000")
        assert row["unrealized"] == Decimal("100.0000")
        assert row["unrealized_percent"] == Decimal("100.0000") / Decimal("500.0000")
        assert row["signal"] == {"level": -3}

    def test_none_branches(self, config: EtfGridConfig) -> None:
        """No position/candle/signal yields zero shares and None market fields."""
        status = get_portfolio_status(
            user_id="alice",
            ledger_service=_FakeLedgerService({}),
            candle_service=_FakeCandleService({}),
            signal_service=_FakeSignalService({}),
            config=config,
        )
        row = _status_row(status, "513330.XSHG")
        assert row["shares"] == 0
        assert row["avg_cost"] is None
        assert row["realized"] == Decimal(0)
        assert row["close"] is None
        assert row["close_date"] is None
        assert row["market_value"] is None
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None
        assert row["signal"] is None


def _row(config: EtfGridConfig, position: Position | None, close: str | None) -> dict[str, Any]:
    """Derive the 513330 status row from one optional position and close."""
    positions = {} if position is None else {"513330.XSHG": position}
    latest = {} if close is None else {"513330.XSHG": {"trade_date": date(2026, 9, 2), "close": Decimal(close)}}
    status = get_portfolio_status(
        user_id="alice",
        ledger_service=_FakeLedgerService(positions),
        candle_service=_FakeCandleService(latest),
        signal_service=_FakeSignalService({}),
        config=config,
    )
    return _status_row(status, "513330.XSHG")


class TestUnrealizedDerivation:
    """unrealized / unrealized_percent derivation and null branches."""

    @pytest.mark.parametrize(("close", "expected"), [("0.6000", Decimal("100.0000")), ("0.4000", Decimal("-100.0000"))])
    def test_profit_and_loss(self, config: EtfGridConfig, close: str, expected: Decimal) -> None:
        """Unrealized is market value minus cost basis for both signs."""
        row = _row(config, Position(shares=1000, avg_cost=Decimal("0.5000"), realized=Decimal(0), lots=()), close)
        assert row["unrealized"] == expected
        assert row["unrealized_percent"] == expected / Decimal("500.0000")

    def test_null_without_position(self, config: EtfGridConfig) -> None:
        """A symbol with candles but no position reports no unrealized P&L."""
        row = _row(config, None, "1.0000")
        assert row["shares"] == 0
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None

    def test_null_without_close(self, config: EtfGridConfig) -> None:
        """A position without candles has no market value or unrealized P&L."""
        row = _row(config, Position(shares=1000, avg_cost=Decimal("0.5000"), realized=Decimal(0), lots=()), None)
        assert row["shares"] == 1000
        assert row["market_value"] is None
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None

    def test_null_percent_on_zero_cost_basis(self, config: EtfGridConfig) -> None:
        """A zero cost basis yields unrealized but never a fabricated percent."""
        row = _row(config, Position(shares=100, avg_cost=Decimal(0), realized=Decimal(0), lots=()), "1.0000")
        assert row["unrealized"] == Decimal("100.0000")
        assert row["unrealized_percent"] is None

    def test_fully_sold_position_has_no_unrealized(self, config: EtfGridConfig) -> None:
        """A closed position keeps realized P&L, values at zero, and reports no unrealized P&L."""
        row = _row(config, Position(shares=0, avg_cost=None, realized=Decimal("12.34"), lots=()), "1.0000")
        assert row["shares"] == 0
        assert row["realized"] == Decimal("12.34")
        assert row["market_value"] == Decimal(0)
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None


def _untouchable_session_factory() -> None:
    """Fail if a service reaches the database."""
    raise AssertionError("database must not be touched without an owner")


@pytest.mark.parametrize(
    "call",
    [
        lambda ledger, signals: ledger.list_trades(user_id=""),
        lambda ledger, signals: ledger.count_trades(user_id=""),
        lambda ledger, signals: ledger.get_positions(user_id=""),
        lambda ledger, signals: ledger.record_trade(user_id="", trade_date=date(2026, 9, 8), symbol="513330.XSHG", side="buy", price=Decimal("1"), quantity=100, commission_rate=Decimal("0.001")),
        lambda ledger, signals: signals.latest_signal("513330.XSHG", user_id=""),
        lambda ledger, signals: signals.upsert_signals([], user_id=""),
        lambda ledger, signals: get_portfolio_status(user_id="", ledger_service=ledger, candle_service=_FakeCandleService({}), signal_service=signals),
    ],
    ids=["list_trades", "count_trades", "get_positions", "record_trade", "latest_signal", "upsert_signals", "portfolio_status"],
)
def test_private_service_calls_fail_closed_without_owner(call: Any) -> None:
    """Every owner-scoped service call rejects an empty user_id before any database access."""
    ledger = EtfGridLedgerService(session_factory=_untouchable_session_factory)  # type: ignore[arg-type]
    signals = EtfGridSignalService(session_factory=_untouchable_session_factory)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="user_id is required"):
        call(ledger, signals)
