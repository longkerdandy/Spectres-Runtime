"""Integration tests for the ETF grid services against a real PostgreSQL database."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from spectres.db.postgres import get_postgres_db
from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.core.grid import SignalSnapshot
from spectres.extensions.etf_grid.models import EtfGridTrade
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
    compute_daily_signals,
    get_portfolio_status,
)
from spectres.extensions.etf_grid.types import (
    CandleInput,
    OrderAdvice,
    Side,
    SortDirection,
    SortSpec,
    Source,
    TradeSortField,
    ValuationInput,
)
from tests.support import migrated_extension_session_factory

pytestmark = [pytest.mark.integration, pytest.mark.db]


class Services:
    """Bundle of all four services sharing one session factory."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Create every service on the shared session factory."""
        self.ledger = EtfGridLedgerService(session_factory=session_factory)
        self.candles = EtfGridCandleService(session_factory=session_factory)
        self.valuation = EtfGridValuationService(session_factory=session_factory)
        self.signals = EtfGridSignalService(session_factory=session_factory)


@pytest.fixture
def services() -> Services:
    """Provide all services over migrated ETF Grid tables."""
    return Services(migrated_extension_session_factory("etf_grid"))


@pytest.fixture
def service(services: Services) -> EtfGridLedgerService:
    """Provide the ledger service."""
    return services.ledger


@pytest.fixture
def candle_service(services: Services) -> EtfGridCandleService:
    """Provide the candle service."""
    return services.candles


def _candle(symbol: str, day: int, close: str, volume: int = 1000) -> CandleInput:
    """Build a candle for 2026-09-<day> with flat OHLC around the close."""
    price = Decimal(close)
    return CandleInput(
        symbol=symbol,
        trade_date=date(2026, 9, day),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
    )


def _record(service: EtfGridLedgerService, **overrides: Any) -> dict[str, Any]:
    """Record a trade from a valid baseline with selected fields overridden."""
    values: dict[str, Any] = {
        "user_id": "alice",
        "trade_date": date(2026, 9, 8),
        "symbol": "513120.XSHG",
        "side": Side.BUY,
        "price": Decimal("1.2950"),
        "quantity": 7800,
        "commission_rate": Decimal("0.001"),
    }
    return service.record_trade(**(values | overrides))


def test_record_trade_persists_computed_amounts(service: EtfGridLedgerService) -> None:
    """A recorded buy is committed with the computed gross/commission/net amounts."""
    trade = _record(service, note="first grid level", source=Source.AGENT)
    assert trade["id"] is not None
    assert trade["gross_amount"] == Decimal("10101.00")
    assert trade["commission"] == Decimal("10.10")
    assert trade["net_amount"] == Decimal("10111.10")
    assert trade["source"] == "agent"
    assert trade["created_at"] is not None
    with Session(get_postgres_db().db_engine) as session:
        assert session.query(EtfGridTrade).count() == 1


def test_record_trade_defaults_and_symbol_normalization(service: EtfGridLedgerService) -> None:
    """Source defaults to manual and both write and read paths normalize symbols."""
    trade = _record(service, symbol="  513120.xshg ")
    assert trade["source"] == "manual"
    assert trade["symbol"] == "513120.XSHG"
    assert [t["symbol"] for t in service.list_trades(user_id="alice", symbol=" 513120.xshg ")] == ["513120.XSHG"]


def test_list_trades_orders_by_symbol_date_id_and_filters(service: EtfGridLedgerService) -> None:
    """list_trades defaults to the (symbol, trade_date, id) replay-canonical order."""
    for symbol, day in [("513330.XSHG", 10), ("513120.XSHG", 8), ("513330.XSHG", 9)]:
        _record(service, symbol=symbol, trade_date=date(2026, 9, day), price=Decimal("1.0000"), quantity=100)
    ordered = [(t["symbol"], t["trade_date"].day) for t in service.list_trades(user_id="alice")]
    assert ordered == [("513120.XSHG", 8), ("513330.XSHG", 9), ("513330.XSHG", 10)]
    filtered = service.list_trades(user_id="alice", symbol="513330.XSHG")
    assert [(t["symbol"], t["trade_date"].day) for t in filtered] == [("513330.XSHG", 9), ("513330.XSHG", 10)]


def test_list_trades_single_field_descending(service: EtfGridLedgerService) -> None:
    """trade_date DESC returns rows in global reverse date order."""
    for symbol, day in [("513330.XSHG", 8), ("513120.XSHG", 10), ("513330.XSHG", 9)]:
        _record(service, symbol=symbol, trade_date=date(2026, 9, day), quantity=100)
    rows = service.list_trades(user_id="alice", order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)])
    assert [(row["symbol"], row["trade_date"].day) for row in rows] == [("513120.XSHG", 10), ("513330.XSHG", 9), ("513330.XSHG", 8)]


def test_list_trades_multi_field_mixed(service: EtfGridLedgerService) -> None:
    """trade_date DESC + symbol ASC applies both keys in order."""
    for symbol, day in [("513330.XSHG", 8), ("513120.XSHG", 10), ("513330.XSHG", 9), ("513120.XSHG", 9)]:
        _record(service, symbol=symbol, trade_date=date(2026, 9, day), quantity=100)
    rows = service.list_trades(
        user_id="alice",
        order_by=[
            SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC),
            SortSpec(TradeSortField.SYMBOL, SortDirection.ASC),
        ],
    )
    assert [(t["trade_date"].day, t["symbol"]) for t in rows] == [(10, "513120.XSHG"), (9, "513120.XSHG"), (9, "513330.XSHG"), (8, "513330.XSHG")]


def test_list_trades_stable_id_suffix(service: EtfGridLedgerService) -> None:
    """Rows sharing the sort key fall back to insertion (id) order."""
    for price in ["1.00", "2.00", "3.00"]:
        _record(service, symbol="513330.XSHG", price=Decimal(price), quantity=100)
    rows = service.list_trades(user_id="alice", order_by=[SortSpec(TradeSortField.TRADE_DATE)])
    assert [t["price"] for t in rows] == [Decimal("1.00"), Decimal("2.00"), Decimal("3.00")]
    assert [t["id"] for t in rows] == sorted(t["id"] for t in rows)


def test_get_positions_replays_each_symbol(service: EtfGridLedgerService) -> None:
    """get_positions replays the ledger per symbol, including sells."""
    _record(service, trade_date=date(2026, 8, 19), symbol="513330.XSHG", price=Decimal("0.4100"), quantity=24300, commission=Decimal("9.96"))
    _record(service, trade_date=date(2026, 9, 9), symbol="513330.XSHG", price=Decimal("0.3590"), quantity=27700, commission=Decimal("9.94"))
    _record(service, trade_date=date(2026, 9, 11), price=Decimal("1.2300"), quantity=8000)
    _record(service, trade_date=date(2026, 9, 15), side=Side.SELL, price=Decimal("1.3000"), quantity=4000)

    positions = service.get_positions(user_id="alice")
    assert set(positions) == {"513120.XSHG", "513330.XSHG"}

    pos_513330 = positions["513330.XSHG"]
    assert pos_513330.shares == 52000
    assert pos_513330.avg_cost == (Decimal("9972.96") + Decimal("9954.24")) / 52000
    assert [lot.shares for lot in pos_513330.lots] == [27700, 24300]

    pos_513120 = positions["513120.XSHG"]
    assert pos_513120.shares == 4000
    assert pos_513120.avg_cost == Decimal("1.23123")
    # realized = net_sell - avg_cost x 4000 = (5200 - 5.20) - 1.23123 x 4000
    assert pos_513120.realized == Decimal("5194.80") - Decimal("1.23123") * 4000


def test_get_positions_empty(service: EtfGridLedgerService) -> None:
    """An empty ledger yields no positions."""
    assert service.get_positions(user_id="alice") == {}
    assert service.get_position("513120.XSHG", user_id="alice") is None


def test_ledger_and_positions_are_owner_scoped(service: EtfGridLedgerService) -> None:
    """The same symbol has independent ledgers and positions for two users."""
    for user_id, quantity in (("alice", 100), ("bob", 250)):
        _record(service, user_id=user_id, price=Decimal("1.0000"), quantity=quantity)

    assert service.count_trades(user_id="alice") == 1
    assert service.count_trades(user_id="bob") == 1
    assert service.list_trades(user_id="alice")[0]["quantity"] == 100
    assert service.list_trades(user_id="bob")[0]["quantity"] == 250
    assert service.get_position("513120.XSHG", user_id="alice").shares == 100  # type: ignore[union-attr]
    assert service.get_position("513120.XSHG", user_id="bob").shares == 250  # type: ignore[union-attr]
    assert service.get_positions(user_id="carol") == {}


class TestUpsertCandles:
    """upsert_candles insert and conflict-overwrite paths against real Postgres."""

    def test_insert_then_read_back(self, candle_service: EtfGridCandleService) -> None:
        """New (symbol, trade_date) rows are inserted and readable."""
        written = candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.4000"), _candle("513330.XSHG", 9, "0.4100")])
        assert written == 2
        rows = candle_service.list_candles("513330.XSHG")
        assert [(r["trade_date"].day, r["close"]) for r in rows] == [(8, Decimal("0.4000")), (9, Decimal("0.4100"))]
        assert all(r["fetched_at"] is not None for r in rows)

    def test_empty_batch_writes_nothing(self, candle_service: EtfGridCandleService) -> None:
        """An empty batch is a no-op that reports zero rows."""
        assert candle_service.upsert_candles([]) == 0
        assert candle_service.list_candles("513330.XSHG") == []

    def test_zero_volume_is_accepted_and_persisted(self, candle_service: EtfGridCandleService) -> None:
        """Zero volume is a valid boundary and round-trips through real storage."""
        assert candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.4000", volume=0)]) == 1
        rows = candle_service.list_candles("513330.XSHG")
        assert [row["volume"] for row in rows] == [0]

    def test_conflict_overwrites_ohlcv_and_refreshes_fetched_at(self, candle_service: EtfGridCandleService) -> None:
        """A second write of the same key overwrites OHLCV (qfq self-healing)."""
        candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.4000", volume=1000)])
        first = candle_service.list_candles("513330.XSHG")[0]

        candle_service.upsert_candles(
            [
                CandleInput(
                    symbol="513330.XSHG",
                    trade_date=date(2026, 9, 8),
                    open=Decimal("0.3500"),
                    high=Decimal("0.3600"),
                    low=Decimal("0.3400"),
                    close=Decimal("0.3550"),
                    volume=2000,
                )
            ]
        )
        rows = candle_service.list_candles("513330.XSHG")
        assert len(rows) == 1
        second = rows[0]
        assert second["open"] == Decimal("0.3500")
        assert second["high"] == Decimal("0.3600")
        assert second["low"] == Decimal("0.3400")
        assert second["close"] == Decimal("0.3550")
        assert second["volume"] == 2000
        # PostgreSQL now() is transaction time, so a later transaction can
        # tie at best; the overwrite above is the strict part of the check.
        assert second["fetched_at"] >= first["fetched_at"]


class TestListCandles:
    """list_candles ordering, limit push-down, and symbol filtering against real Postgres."""

    @pytest.mark.parametrize(
        ("descending", "limit", "expected_days"),
        [
            (False, None, [8, 9, 10]),
            (True, None, [10, 9, 8]),
            (False, 2, [8, 9]),
            (True, 1, [10]),
        ],
    )
    def test_ordering_and_limit(self, candle_service: EtfGridCandleService, descending: bool, limit: int | None, expected_days: list[int]) -> None:
        """Rows are chronological by default; limit applies after the requested ordering."""
        candle_service.upsert_candles([_candle("513330.XSHG", day, "0.40") for day in (9, 10, 8)])
        rows = candle_service.list_candles("513330.XSHG", descending=descending, limit=limit)
        assert [r["trade_date"].day for r in rows] == expected_days

    def test_symbol_filter_is_isolated_and_normalized(self, candle_service: EtfGridCandleService) -> None:
        """list_candles accepts un-normalized input and returns only the requested symbol."""
        candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.40"), _candle("513120.XSHG", 8, "1.20")])
        assert [r["symbol"] for r in candle_service.list_candles(" 513330.xshg ")] == ["513330.XSHG"]


def _snapshot(symbol: str, day: int, orders: tuple[OrderAdvice, ...] = (), level: int = 0) -> SignalSnapshot:
    """Build a signal snapshot for 2026-09-<day> with plausible flat values."""
    return SignalSnapshot(
        symbol=symbol,
        trade_date=date(2026, 9, day),
        close=Decimal("1.0000"),
        anchor_ma60=Decimal("1.0000"),
        level=level,
        prev_level=level,
        orders=orders,
        block_reason=None,
        gate_metric_value=None,
        gate_percentile=None,
        gate_closed=None,
    )


_BUY_ORDER = OrderAdvice(side="buy", limit_price=Decimal("0.9500"), grids=3, shares_est=30000, kind="triggered", note=None)


class TestValuationService:
    """Valuation upsert/overwrite and read paths against real Postgres."""

    def test_upsert_read_and_overwrite(self, services: Services) -> None:
        """Rows round-trip ascending; re-upserting a date overwrites it."""
        services.valuation.upsert_valuation(
            [
                ValuationInput(trade_date=date(2026, 9, 2), close=Decimal("5000.00"), pe_ttm=Decimal("20.00"), dyr=None),
                ValuationInput(trade_date=date(2026, 9, 1), close=Decimal("4990.00"), pe_ttm=Decimal("19.90"), dyr=Decimal("0.0532")),
            ]
        )
        rows = services.valuation.list_valuation()
        assert [r["trade_date"].day for r in rows] == [1, 2]
        assert rows[0]["dyr"] == Decimal("0.0532")
        assert rows[1]["dyr"] is None

        services.valuation.upsert_valuation([ValuationInput(trade_date=date(2026, 9, 2), close=Decimal("5010.00"), pe_ttm=Decimal("20.10"), dyr=Decimal("0.0530"))])
        rows = services.valuation.list_valuation()
        assert len(rows) == 2
        assert rows[1]["close"] == Decimal("5010.00")
        assert rows[1]["dyr"] == Decimal("0.0530")


class TestSignalService:
    """Signal upsert-on-recompute and read paths against real Postgres."""

    def test_upsert_read_and_latest(self, services: Services) -> None:
        """Snapshots round-trip through latest_signal; JSONB orders survive as strings."""
        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513330.XSHG", 1, orders=(_BUY_ORDER,), level=-3)])
        latest = services.signals.latest_signal(user_id="alice", symbol="513330.XSHG")
        # JSONB roundtrip: Decimals are stored as strings
        assert latest is not None and latest["orders"] == [{"side": "buy", "limit_price": "0.9500", "grids": 3, "shares_est": 30000, "kind": "triggered", "note": None}]
        assert latest["level"] == -3
        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513330.XSHG", 2)])
        latest = services.signals.latest_signal(user_id="alice", symbol="513330.XSHG")
        assert latest is not None and latest["trade_date"] == date(2026, 9, 2)
        assert latest["level"] == 0

    def test_recompute_overwrites_same_day(self, services: Services) -> None:
        """A same-day recomputation overwrites the row (advice, not fact)."""
        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513330.XSHG", 1)])
        first = services.signals.latest_signal(user_id="alice", symbol="513330.XSHG")
        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513330.XSHG", 1, orders=(_BUY_ORDER,), level=-3)])
        row = services.signals.latest_signal(user_id="alice", symbol="513330.XSHG")
        assert row is not None
        assert len(row["orders"]) == 1
        assert row["orders"][0]["grids"] == 3
        assert row["level"] == -3
        assert first is not None and row["computed_at"] >= first["computed_at"]

    def test_same_day_snapshots_coexist_for_two_users(self, services: Services) -> None:
        """Owner is part of both the upsert key and latest-signal reads."""
        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513330.XSHG", 1, level=-3)])
        services.signals.upsert_signals(user_id="bob", snapshots=[_snapshot("513330.XSHG", 1, level=2)])
        alice = services.signals.latest_signal(user_id="alice", symbol="513330.XSHG")
        bob = services.signals.latest_signal(user_id="bob", symbol="513330.XSHG")
        assert alice is not None and alice["level"] == -3
        assert bob is not None and bob["level"] == 2

        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513330.XSHG", 1, level=-2)])
        bob_after = services.signals.latest_signal(user_id="bob", symbol="513330.XSHG")
        assert bob_after is not None and bob_after["level"] == 2


class TestComputeDailySignals:
    """End-to-end signal computation against seeded candles/trades."""

    def _seed_candles(self, services: Services, symbol: str, count: int, last_close: str = "0.9000") -> None:
        """Seed `count` consecutive candles, flat 1.0000 except the final close."""
        start = date(2026, 1, 1)
        services.candles.upsert_candles(
            [
                CandleInput(
                    symbol=symbol,
                    trade_date=start + timedelta(days=i),
                    open=Decimal("1.0000"),
                    high=Decimal("1.0000"),
                    low=Decimal("1.0000"),
                    close=Decimal(last_close) if i == count - 1 else Decimal("1.0000"),
                    volume=1000,
                )
                for i in range(count)
            ]
        )

    def test_buy_signal_end_to_end(self, services: Services) -> None:
        """A 3-level drop on sufficient history computes and persists a buy signal."""
        self._seed_candles(services, "513330.XSHG", 61)
        config = EtfGridConfig()  # type: ignore[call-arg]  # required fields come from .env.test
        result = compute_daily_signals(
            ["513330.XSHG"],
            user_id="alice",
            config=config,
            ledger_service=services.ledger,
            candle_service=services.candles,
            valuation_service=services.valuation,
            signal_service=services.signals,
        )
        assert result["skipped"] == {}
        signal = result["signals"]["513330.XSHG"]
        assert signal["level"] == -3
        assert signal["prev_level"] == 0
        triggered = next(o for o in signal["orders"] if o["kind"] == "triggered")
        assert triggered["side"] == "buy"
        assert triggered["grids"] == 3
        pending_buy = next(o for o in signal["orders"] if o["kind"] == "pending" and o["side"] == "buy")
        assert pending_buy["grids"] == 1

        persisted = services.signals.latest_signal(user_id="alice", symbol="513330.XSHG")
        assert persisted is not None
        assert len(persisted["orders"]) == 2  # triggered buy + pending buy
        assert persisted["orders"][0]["kind"] == "triggered"
        assert persisted["orders"][0]["grids"] == 3
        assert persisted["computed_at"] is not None

    def test_insufficient_history_is_skipped_not_crashing(self, services: Services) -> None:
        """Symbols without 61 bars land in skipped with a reason."""
        self._seed_candles(services, "513330.XSHG", 10)
        config = EtfGridConfig()  # type: ignore[call-arg]
        result = compute_daily_signals(
            ["513330.XSHG"],
            user_id="alice",
            config=config,
            ledger_service=services.ledger,
            candle_service=services.candles,
            valuation_service=services.valuation,
            signal_service=services.signals,
        )
        assert result["signals"] == {}
        assert result["skipped"] == {"513330.XSHG": "insufficient_candles"}

    def test_gated_symbol_without_valuation_data_is_skipped(self, services: Services) -> None:
        """A configured gate with an empty valuation table skips the symbol."""
        self._seed_candles(services, "513530.XSHG", 61)
        config = EtfGridConfig()  # type: ignore[call-arg]
        result = compute_daily_signals(
            ["513530.XSHG"],
            user_id="alice",
            config=config,
            ledger_service=services.ledger,
            candle_service=services.candles,
            valuation_service=services.valuation,
            signal_service=services.signals,
        )
        assert result["skipped"] == {"513530.XSHG": "no_valuation_data"}

    def test_gated_symbol_with_valuation_data_computes(self, services: Services) -> None:
        """With a valuation series the gate fields persist on the snapshot."""
        self._seed_candles(services, "513530.XSHG", 61)
        services.valuation.upsert_valuation(
            [
                ValuationInput(
                    trade_date=date(2026, 1, 1) + timedelta(days=i),
                    close=Decimal("5000.00"),
                    pe_ttm=Decimal("20.00"),
                    dyr=Decimal("0.0500"),
                )
                for i in range(60)
            ]
        )
        config = EtfGridConfig()  # type: ignore[call-arg]
        result = compute_daily_signals(
            ["513530.XSHG"],
            user_id="alice",
            config=config,
            ledger_service=services.ledger,
            candle_service=services.candles,
            valuation_service=services.valuation,
            signal_service=services.signals,
        )
        assert result["skipped"] == {}
        signal = result["signals"]["513530.XSHG"]
        triggered = next(o for o in signal["orders"] if o["kind"] == "triggered")
        assert triggered["side"] == "buy"  # gate open: dyr percentile 1.0 >= 0.2
        assert signal["gate_metric_value"] == Decimal("0.0500")
        assert signal["gate_closed"] is False


class TestGetPortfolioStatus:
    """The presentation summary combines ledger position, market data, and signals."""

    def test_status_shape(self, services: Services) -> None:
        """Every configured symbol reports position + close + latest signal."""
        services.ledger.record_trade(
            user_id="alice",
            trade_date=date(2026, 9, 8),
            symbol="513120.XSHG",
            side=Side.BUY,
            price=Decimal("1.2300"),
            quantity=8000,
            commission_rate=Decimal("0.001"),
        )
        services.candles.upsert_candles(
            [
                CandleInput(
                    symbol="513120.XSHG",
                    trade_date=date(2026, 9, 22),
                    open=Decimal("1.3000"),
                    high=Decimal("1.3000"),
                    low=Decimal("1.3000"),
                    close=Decimal("1.3000"),
                    volume=1000,
                )
            ]
        )
        services.signals.upsert_signals(user_id="alice", snapshots=[_snapshot("513120.XSHG", 22, orders=(_BUY_ORDER,))])
        status = get_portfolio_status(
            user_id="alice",
            ledger_service=services.ledger,
            candle_service=services.candles,
            signal_service=services.signals,
        )
        assert {row["symbol"] for row in status} == {"513330.XSHG", "513120.XSHG", "513530.XSHG"}
        row = next(r for r in status if r["symbol"] == "513120.XSHG")
        assert row["shares"] == 8000
        assert row["avg_cost"] == Decimal("1.23123")
        assert row["close"] == Decimal("1.3000")
        assert row["market_value"] == Decimal("1.3000") * 8000
        assert row["signal"]["trade_date"] == date(2026, 9, 22)
        assert row["signal"]["orders"][0]["side"] == "buy"
        empty = next(r for r in status if r["symbol"] == "513530.XSHG")
        assert empty["shares"] == 0
        assert empty["market_value"] is None
        assert empty["signal"] is None
