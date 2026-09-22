"""Integration tests for the ETF grid ledger service against a real PostgreSQL database."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from spectres.extensions.etf_grid.db import get_engine
from spectres.extensions.etf_grid.models import EtfGridBase, EtfGridCandle, EtfGridTrade
from spectres.extensions.etf_grid.service import EtfGridCandleService, EtfGridLedgerService
from spectres.extensions.etf_grid.types import (
    CandleInput,
    Side,
    SortDirection,
    SortSpec,
    Source,
    TradeSortField,
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
