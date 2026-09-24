"""Integration tests for the ETF grid services against a real PostgreSQL database."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.core.grid import SignalSnapshot
from spectres.extensions.etf_grid.db import get_engine
from spectres.extensions.etf_grid.models import EtfGridBase, EtfGridCandle, EtfGridSignal, EtfGridTrade, EtfGridValuation
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
    compute_daily_signals,
    get_portfolio_status,
)
from spectres.extensions.etf_grid.types import (
    BlockReason,
    CandleInput,
    Side,
    SignalAction,
    SignalSortField,
    SortDirection,
    SortSpec,
    Source,
    TradeSortField,
    ValuationInput,
)

pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture
def service() -> EtfGridLedgerService:
    """Provide a ledger service over a freshly created etf_grid_trades table."""
    engine = get_engine()
    EtfGridBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session, session.begin():
        session.execute(delete(EtfGridTrade))
    return EtfGridLedgerService(session_factory=session_factory)


@pytest.fixture
def candle_service() -> EtfGridCandleService:
    """Provide a candle service over a freshly created etf_grid_candles table."""
    engine = get_engine()
    EtfGridBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session, session.begin():
        session.execute(delete(EtfGridCandle))
    return EtfGridCandleService(session_factory=session_factory)


class Services:
    """Bundle of all four services over one freshly cleaned database."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Create every service on the shared session factory."""
        self.ledger = EtfGridLedgerService(session_factory=session_factory)
        self.candles = EtfGridCandleService(session_factory=session_factory)
        self.valuation = EtfGridValuationService(session_factory=session_factory)
        self.signals = EtfGridSignalService(session_factory=session_factory)


@pytest.fixture
def services() -> Services:
    """Provide all services over freshly created, emptied extension tables."""
    engine = get_engine()
    EtfGridBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session, session.begin():
        for table in (EtfGridSignal, EtfGridValuation, EtfGridCandle, EtfGridTrade):
            session.execute(delete(table))
    return Services(session_factory)


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


def test_record_trade_persists_computed_amounts(service: EtfGridLedgerService) -> None:
    """A recorded buy round-trips with the computed gross/commission/net amounts."""
    trade = service.record_trade(
        trade_date=date(2026, 9, 8),
        symbol="513120.XSHG",
        side=Side.BUY,
        price=Decimal("1.2950"),
        quantity=7800,
        commission_rate=Decimal("0.001"),
        note="first grid level",
        source=Source.AGENT,
    )
    assert trade["id"] is not None
    assert trade["gross_amount"] == Decimal("10101.00")
    assert trade["commission"] == Decimal("10.10")
    assert trade["net_amount"] == Decimal("10111.10")
    assert trade["source"] == "agent"
    assert trade["created_at"] is not None


def test_record_trade_defaults_source_to_manual(service: EtfGridLedgerService) -> None:
    """Omitting source records the trade as manual."""
    trade = service.record_trade(
        trade_date=date(2026, 9, 8),
        symbol="513120.XSHG",
        side=Side.BUY,
        price=Decimal("1.2950"),
        quantity=7800,
        commission_rate=Decimal("0.001"),
    )
    assert trade["source"] == "manual"


def test_record_trade_normalizes_symbol(service: EtfGridLedgerService) -> None:
    """Lowercase/whitespace symbols are normalized to the canonical full code."""
    trade = service.record_trade(
        trade_date=date(2026, 9, 8),
        symbol="  513120.xshg ",
        side=Side.BUY,
        price=Decimal("1.2950"),
        quantity=7800,
        commission_rate=Decimal("0.001"),
    )
    assert trade["symbol"] == "513120.XSHG"
    assert [t["symbol"] for t in service.list_trades(symbol="513120.XSHG")] == ["513120.XSHG"]


def test_list_trades_normalizes_symbol_filter(service: EtfGridLedgerService) -> None:
    """The read-side symbol filter accepts un-normalized input."""
    service.record_trade(
        trade_date=date(2026, 9, 8),
        symbol="513120.XSHG",
        side=Side.BUY,
        price=Decimal("1.2950"),
        quantity=7800,
        commission_rate=Decimal("0.001"),
    )
    rows = service.list_trades(symbol=" 513120.xshg ")
    assert [t["symbol"] for t in rows] == ["513120.XSHG"]


def test_list_trades_orders_by_symbol_date_id_and_filters(service: EtfGridLedgerService) -> None:
    """list_trades defaults to the (symbol, trade_date, id) replay-canonical order."""
    for symbol, day in [("513330.XSHG", 10), ("513120.XSHG", 8), ("513330.XSHG", 9)]:
        service.record_trade(
            trade_date=date(2026, 9, day),
            symbol=symbol,
            side=Side.BUY,
            price=Decimal("1.0000"),
            quantity=100,
            commission_rate=Decimal("0.001"),
        )
    ordered = [(t["symbol"], t["trade_date"].day) for t in service.list_trades()]
    assert ordered == [("513120.XSHG", 8), ("513330.XSHG", 9), ("513330.XSHG", 10)]
    filtered = service.list_trades(symbol="513330.XSHG")
    assert [(t["symbol"], t["trade_date"].day) for t in filtered] == [("513330.XSHG", 9), ("513330.XSHG", 10)]


def _seed_grid_rows(service: EtfGridLedgerService) -> None:
    """Insert rows whose default order differs from trade_date order."""
    for symbol, day, price in [("513330.XSHG", 8, "1.00"), ("513120.XSHG", 10, "2.00"), ("513330.XSHG", 9, "3.00")]:
        service.record_trade(
            trade_date=date(2026, 9, day),
            symbol=symbol,
            side=Side.BUY,
            price=Decimal(price),
            quantity=100,
            commission_rate=Decimal("0.001"),
        )


def test_list_trades_single_field_descending(service: EtfGridLedgerService) -> None:
    """trade_date DESC returns the rows in global reverse date order."""
    _seed_grid_rows(service)
    rows = service.list_trades(order_by=[SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC)])
    assert [(t["symbol"], t["trade_date"].day) for t in rows] == [("513120.XSHG", 10), ("513330.XSHG", 9), ("513330.XSHG", 8)]


def test_list_trades_multi_field_mixed(service: EtfGridLedgerService) -> None:
    """trade_date DESC + symbol ASC applies both keys in order."""
    _seed_grid_rows(service)
    rows = service.list_trades(
        order_by=[
            SortSpec(TradeSortField.TRADE_DATE, SortDirection.DESC),
            SortSpec(TradeSortField.SYMBOL, SortDirection.ASC),
        ]
    )
    assert [(t["trade_date"].day, t["symbol"]) for t in rows] == [(10, "513120.XSHG"), (9, "513330.XSHG"), (8, "513330.XSHG")]


def test_list_trades_stable_id_suffix(service: EtfGridLedgerService) -> None:
    """Rows sharing the sort key fall back to insertion (id) order."""
    for price in ["1.00", "2.00", "3.00"]:
        service.record_trade(
            trade_date=date(2026, 9, 8),
            symbol="513330.XSHG",
            side=Side.BUY,
            price=Decimal(price),
            quantity=100,
            commission_rate=Decimal("0.001"),
        )
    rows = service.list_trades(order_by=[SortSpec(TradeSortField.TRADE_DATE)])
    assert [t["price"] for t in rows] == [Decimal("1.00"), Decimal("2.00"), Decimal("3.00")]
    assert [t["id"] for t in rows] == sorted(t["id"] for t in rows)


def test_get_positions_replays_each_symbol(service: EtfGridLedgerService) -> None:
    """get_positions replays the ledger per symbol, including sells."""
    service.record_trade(
        trade_date=date(2026, 8, 19),
        symbol="513330.XSHG",
        side=Side.BUY,
        price=Decimal("0.4100"),
        quantity=24300,
        commission_rate=Decimal("0.001"),
        commission=Decimal("9.96"),
        note="opening position backfill",
    )
    service.record_trade(
        trade_date=date(2026, 9, 9),
        symbol="513330.XSHG",
        side=Side.BUY,
        price=Decimal("0.3590"),
        quantity=27700,
        commission_rate=Decimal("0.001"),
        commission=Decimal("9.94"),
    )
    service.record_trade(
        trade_date=date(2026, 9, 11),
        symbol="513120.XSHG",
        side=Side.BUY,
        price=Decimal("1.2300"),
        quantity=8000,
        commission_rate=Decimal("0.001"),
    )
    service.record_trade(
        trade_date=date(2026, 9, 15),
        symbol="513120.XSHG",
        side=Side.SELL,
        price=Decimal("1.3000"),
        quantity=4000,
        commission_rate=Decimal("0.001"),
    )

    positions = service.get_positions()
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
    assert service.get_positions() == {}


def test_session_is_usable_after_record(service: EtfGridLedgerService) -> None:
    """record_trade commits its own transaction and leaves no dangling state."""
    service.record_trade(
        trade_date=date(2026, 9, 8),
        symbol="513120.XSHG",
        side=Side.BUY,
        price=Decimal("1.2950"),
        quantity=7800,
        commission_rate=Decimal("0.001"),
    )
    with Session(get_engine()) as session:
        assert session.query(EtfGridTrade).count() == 1


class TestUpsertCandles:
    """upsert_candles insert and conflict-overwrite paths against real Postgres."""

    def test_insert_then_read_back(self, candle_service: EtfGridCandleService) -> None:
        """New (symbol, trade_date) rows are inserted and readable."""
        written = candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.4000"), _candle("513330.XSHG", 9, "0.4100")])
        assert written == 2
        rows = candle_service.list_candles("513330.XSHG")
        assert [(r["trade_date"].day, r["close"]) for r in rows] == [(8, Decimal("0.4000")), (9, Decimal("0.4100"))]
        assert all(r["fetched_at"] is not None for r in rows)

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
    """list_candles ordering and limit push-down against real Postgres."""

    def test_default_chronological(self, candle_service: EtfGridCandleService) -> None:
        """Default order is trade_date ascending."""
        candle_service.upsert_candles([_candle("513330.XSHG", 9, "0.41"), _candle("513330.XSHG", 8, "0.40")])
        assert [r["trade_date"].day for r in candle_service.list_candles("513330.XSHG")] == [8, 9]

    def test_descending(self, candle_service: EtfGridCandleService) -> None:
        """descending=True returns newest first."""
        candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.40"), _candle("513330.XSHG", 9, "0.41")])
        assert [r["trade_date"].day for r in candle_service.list_candles("513330.XSHG", descending=True)] == [9, 8]

    def test_limit(self, candle_service: EtfGridCandleService) -> None:
        """Limit caps the result, applied after the ordering."""
        candle_service.upsert_candles([_candle("513330.XSHG", day, "0.40") for day in (8, 9, 10)])
        assert [r["trade_date"].day for r in candle_service.list_candles("513330.XSHG", limit=2)] == [8, 9]

    def test_descending_limit_one_returns_latest(self, candle_service: EtfGridCandleService) -> None:
        """Descending + limit=1 yields the single most recent candle."""
        candle_service.upsert_candles([_candle("513330.XSHG", day, "0.40") for day in (8, 9, 10)])
        rows = candle_service.list_candles("513330.XSHG", descending=True, limit=1)
        assert [r["trade_date"].day for r in rows] == [10]

    def test_symbol_isolation(self, candle_service: EtfGridCandleService) -> None:
        """list_candles only returns the requested symbol."""
        candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.40"), _candle("513120.XSHG", 8, "1.20")])
        assert [r["symbol"] for r in candle_service.list_candles("513330.XSHG")] == ["513330.XSHG"]

    def test_symbol_filter_normalizes(self, candle_service: EtfGridCandleService) -> None:
        """list_candles accepts un-normalized symbol input."""
        candle_service.upsert_candles([_candle("513330.XSHG", 8, "0.40")])
        rows = candle_service.list_candles(" 513330.xshg ")
        assert [r["symbol"] for r in rows] == ["513330.XSHG"]


def _snapshot(symbol: str, day: int, action: SignalAction = SignalAction.NONE, grids: int = 0, level: int = 0) -> SignalSnapshot:
    """Build a signal snapshot for 2026-09-<day> with plausible flat values."""
    return SignalSnapshot(
        symbol=symbol,
        trade_date=date(2026, 9, day),
        close=Decimal("1.0000"),
        anchor_ma60=Decimal("1.0000"),
        level=level,
        prev_level=level,
        action=action,
        grids=grids,
        block_reason=BlockReason.NO_POSITION if action is SignalAction.NONE else None,
        next_buy_trigger=Decimal("0.9500"),
        next_sell_trigger=None,
        gate_metric_value=None,
        gate_percentile=None,
        gate_closed=None,
    )


class TestValuationService:
    """Valuation upsert/overwrite and read paths against real Postgres."""

    def test_upsert_read_latest_and_overwrite(self, services: Services) -> None:
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
        latest = services.valuation.latest_valuation()
        assert latest is not None and latest["trade_date"] == date(2026, 9, 2)

        services.valuation.upsert_valuation([ValuationInput(trade_date=date(2026, 9, 2), close=Decimal("5010.00"), pe_ttm=Decimal("20.10"), dyr=Decimal("0.0530"))])
        rows = services.valuation.list_valuation()
        assert len(rows) == 2
        assert rows[1]["close"] == Decimal("5010.00")
        assert rows[1]["dyr"] == Decimal("0.0530")


class TestSignalService:
    """Signal upsert-on-recompute and read paths against real Postgres."""

    def test_upsert_read_and_latest(self, services: Services) -> None:
        """Snapshots round-trip in canonical order; latest_signal reads the newest."""
        services.signals.upsert_signals([_snapshot("513330.XSHG", 2), _snapshot("513330.XSHG", 1, SignalAction.BUY, 2, -3)])
        rows = services.signals.list_signals("513330.XSHG")
        assert [(r["trade_date"].day, r["action"], r["grids"]) for r in rows] == [(1, "buy", 2), (2, "none", 0)]
        latest = services.signals.latest_signal("513330.XSHG")
        assert latest is not None and latest["trade_date"] == date(2026, 9, 2)

    def test_recompute_overwrites_same_day(self, services: Services) -> None:
        """A same-day recomputation overwrites the row (advice, not fact)."""
        services.signals.upsert_signals([_snapshot("513330.XSHG", 1, SignalAction.NONE, 0)])
        first = services.signals.latest_signal("513330.XSHG")
        services.signals.upsert_signals([_snapshot("513330.XSHG", 1, SignalAction.BUY, 3, -3)])
        rows = services.signals.list_signals("513330.XSHG")
        assert len(rows) == 1
        assert rows[0]["action"] == "buy"
        assert rows[0]["grids"] == 3
        assert rows[0]["level"] == -3
        assert first is not None and rows[0]["computed_at"] >= first["computed_at"]

    def test_list_signals_order_by_and_filter(self, services: Services) -> None:
        """SortSpec ordering works with the composite-PK stable suffix."""
        services.signals.upsert_signals(
            [
                _snapshot("513330.XSHG", 1, level=-3),
                _snapshot("513120.XSHG", 1, level=0),
                _snapshot("513330.XSHG", 2, level=-2),
            ]
        )
        rows = services.signals.list_signals(order_by=[SortSpec(SignalSortField.LEVEL, SortDirection.DESC)])
        assert [(r["level"], r["symbol"], r["trade_date"].day) for r in rows] == [
            (0, "513120.XSHG", 1),
            (-2, "513330.XSHG", 2),
            (-3, "513330.XSHG", 1),
        ]


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
        assert signal["action"] == "buy"
        assert signal["grids"] == 3

        persisted = services.signals.latest_signal("513330.XSHG")
        assert persisted is not None
        assert persisted["action"] == "buy"
        assert persisted["grids"] == 3
        assert persisted["computed_at"] is not None

    def test_insufficient_history_is_skipped_not_crashing(self, services: Services) -> None:
        """Symbols without 61 bars land in skipped with a reason."""
        self._seed_candles(services, "513330.XSHG", 10)
        config = EtfGridConfig()  # type: ignore[call-arg]
        result = compute_daily_signals(
            ["513330.XSHG"],
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
            config=config,
            ledger_service=services.ledger,
            candle_service=services.candles,
            valuation_service=services.valuation,
            signal_service=services.signals,
        )
        assert result["skipped"] == {}
        signal = result["signals"]["513530.XSHG"]
        assert signal["action"] == "buy"  # gate open: dyr percentile 1.0 >= 0.2
        assert signal["gate_metric_value"] == Decimal("0.0500")
        assert signal["gate_closed"] is False


class TestGetPortfolioStatus:
    """The presentation summary combines ledger position, market data, and signals."""

    def test_status_shape(self, services: Services) -> None:
        """Every configured symbol reports position + close + latest signal."""
        services.ledger.record_trade(
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
        services.signals.upsert_signals([_snapshot("513120.XSHG", 22, SignalAction.NONE, 0)])
        config = EtfGridConfig()  # type: ignore[call-arg]
        status = get_portfolio_status(
            config=config,
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
        empty = next(r for r in status if r["symbol"] == "513530.XSHG")
        assert empty["shares"] == 0
        assert empty["market_value"] is None
        assert empty["signal"] is None
