"""Unit tests for the ETF grid market data sync orchestration (mocked client/service)."""

import os
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.marketdata import CST, MAX_WINDOW_DAYS, bar_to_candle, sync_candles
from spectres.extensions.etf_grid.service import EtfGridCandleService
from spectres.extensions.etf_grid.types import CandleInput

pytestmark = pytest.mark.unit


def _ts_ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    """Build a UTC epoch-millis timestamp."""
    return int(datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp() * 1000)


def _bar(ts_ms: int, close: str = "0.4100", volume: object = 123_456_789) -> dict[str, Any]:
    """Build a fake FTShare bar row."""
    price = float(close)
    return {"ts_millis_open": ts_ms, "open": price, "high": price, "low": price, "close": price, "volume": volume}


class TestBarToCandle:
    """FTShare bar rows translate into quantized CST-dated CandleInputs."""

    def test_basic_translation(self) -> None:
        """Fields map through; prices quantize to 4 decimals, volume to int."""
        candle = bar_to_candle("513330.XSHG", _bar(_ts_ms(2026, 9, 22, 9, 30), close="0.4123", volume=1.5e8))
        assert candle.trade_date == date(2026, 9, 22)
        assert candle.close == Decimal("0.4123")
        assert candle.volume == 150_000_000

    def test_price_quantized_to_four_decimals(self) -> None:
        """Extra provider precision is rounded to the historical CSV precision."""
        candle = bar_to_candle("513330.XSHG", _bar(_ts_ms(2026, 9, 22), close="0.41234"))
        assert candle.close == Decimal("0.4123")
        candle = bar_to_candle("513330.XSHG", _bar(_ts_ms(2026, 9, 22), close="0.41236"))
        assert candle.close == Decimal("0.4124")

    def test_cst_date_boundary(self) -> None:
        """ts_millis_open is interpreted in CST: 16:00 UTC flips the date."""
        # 2026-09-21 16:00 UTC == 2026-09-22 00:00 CST
        candle = bar_to_candle("513330.XSHG", _bar(_ts_ms(2026, 9, 21, 16, 0)))
        assert candle.trade_date == date(2026, 9, 22)
        # One second earlier still belongs to 2026-09-21 CST
        candle = bar_to_candle("513330.XSHG", _bar(_ts_ms(2026, 9, 21, 15, 59, 59)))
        assert candle.trade_date == date(2026, 9, 21)


class MockClient:
    """Records etf_candlesticks calls and returns canned bars."""

    def __init__(self, bars: list[dict[str, Any]]) -> None:
        """Set up with the canned bars to return."""
        self.bars = bars
        self.calls: list[dict[str, Any]] = []

    def etf_candlesticks(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Record the call and return the canned bars."""
        self.calls.append(kwargs)
        return self.bars


class FakeCandleService(EtfGridCandleService):
    """In-memory stand-in recording upsert batches (no database)."""

    def __init__(self, latest: date | None) -> None:
        """Set up with an optional latest stored trade_date."""
        self._latest = latest
        self.batches: list[list[CandleInput]] = []

    def list_candles(
        self,
        symbol: str,
        *,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return only the latest stored date (all the sync window logic reads)."""
        return [{"trade_date": self._latest}] if self._latest else []

    def upsert_candles(self, candles: Sequence[CandleInput]) -> int:
        """Record the batch and report its size."""
        self.batches.append(list(candles))
        return len(candles)


class TestSyncCandles:
    """sync_candles orchestration: window computation, call params, translation."""

    def test_missing_api_key_fails_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing key raises a clear ValueError only when sync is invoked."""
        monkeypatch.delenv("ETF_GRID_FTSHARE_API_KEY", raising=False)
        monkeypatch.delenv("FTSHARE_API_KEY", raising=False)
        config = EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="ETF_GRID_FTSHARE_API_KEY is required"):
            sync_candles(["513330.XSHG"], config=config, candle_service=FakeCandleService(None))

    def test_backfill_window_when_empty(self) -> None:
        """A symbol with no local data fetches from backfill_start_date."""
        client = MockClient([_bar(_ts_ms(2026, 9, 22))])
        service = FakeCandleService(latest=None)
        result = sync_candles(["513330.XSHG"], client=client, candle_service=service)

        call = client.calls[0]
        expected_since_ms = int(datetime(2021, 1, 1, tzinfo=CST).timestamp() * 1000)
        assert call["symbol"] == "513330.XSHG"
        assert call["interval_unit"] == "Day"
        assert call["adjust_kind"] == "forward"
        assert call["since_ts_millis"] == expected_since_ms
        assert call["as_dataframe"] is False
        assert call["until_ts_millis"] > expected_since_ms

        assert service.batches == [
            [
                CandleInput(
                    symbol="513330.XSHG",
                    trade_date=date(2026, 9, 22),
                    open=Decimal("0.4100"),
                    high=Decimal("0.4100"),
                    low=Decimal("0.4100"),
                    close=Decimal("0.4100"),
                    volume=123_456_789,
                )
            ]
        ]
        assert result == {"513330.XSHG": 1}

    def test_self_healing_window_when_data_exists(self) -> None:
        """An existing symbol refetches latest_date - candle_lookback_days."""
        client = MockClient([])
        service = FakeCandleService(latest=date(2026, 9, 22))
        config = EtfGridConfig(candle_lookback_days=90)
        result = sync_candles(["513330.XSHG"], client=client, candle_service=service, config=config)

        expected_since_ms = int(datetime(2026, 6, 24, tzinfo=CST).timestamp() * 1000)  # 2026-09-22 minus 90 days
        assert client.calls[0]["since_ts_millis"] == expected_since_ms
        assert service.batches == []  # no bars -> no upsert call
        assert result == {"513330.XSHG": 0}

    def test_symbols_default_to_configured_portfolio(self) -> None:
        """symbols=None syncs every symbol in the configured portfolio."""
        client = MockClient([])
        service = FakeCandleService(latest=None)
        result = sync_candles(client=client, candle_service=service)
        assert {call["symbol"] for call in client.calls} == {"513330.XSHG", "513120.XSHG", "513530.XSHG"}
        assert set(result) == {"513330.XSHG", "513120.XSHG", "513530.XSHG"}

    def test_backfill_chunks_into_sub_year_windows(self) -> None:
        """Long backfills are split into contiguous <=12-month chunks (FTShare server limit)."""
        client = MockClient([])
        service = FakeCandleService(latest=None)
        sync_candles(["513330.XSHG"], client=client, candle_service=service)

        assert len(client.calls) > 1
        for call in client.calls:
            assert call["until_ts_millis"] - call["since_ts_millis"] <= MAX_WINDOW_DAYS * 86_400_000
        assert client.calls[0]["since_ts_millis"] == int(datetime(2021, 1, 1, tzinfo=CST).timestamp() * 1000)
        for prev, nxt in zip(client.calls, client.calls[1:], strict=False):
            assert nxt["since_ts_millis"] == prev["until_ts_millis"]

    def test_symbol_normalized_before_fetch(self) -> None:
        """Lowercase symbols are normalized before hitting client and service."""
        client = MockClient([_bar(_ts_ms(2026, 9, 22))])
        service = FakeCandleService(latest=None)
        result = sync_candles(["513330.xshg"], client=client, candle_service=service)
        assert client.calls[0]["symbol"] == "513330.XSHG"
        assert service.batches[0][0].symbol == "513330.XSHG"
        assert result == {"513330.XSHG": 1}


@pytest.mark.skipif(os.environ.get("FTSHARE_RUN_INTEGRATION") != "1", reason="live FTShare call; set FTSHARE_RUN_INTEGRATION=1 to enable")
def test_live_ftshare_fetch() -> None:
    """Live smoke: the real SDK fetches recent daily bars for one symbol."""
    import ftshare as ft

    config = EtfGridConfig(_env_file=None)  # type: ignore[call-arg]
    if not config.ftshare_api_key:
        pytest.skip("no FTSHARE API key configured")
    client = ft.market_api(api_key=config.ftshare_api_key)
    bars = client.etf_candlesticks(
        symbol="513330.XSHG",
        interval_unit="Day",
        adjust_kind="forward",
        since_ts_millis=int((datetime.now(CST) - timedelta(days=30)).timestamp() * 1000),
        until_ts_millis=int(datetime.now(CST).timestamp() * 1000),
        limit=3,
        as_dataframe=False,
    )
    assert bars, "expected at least one bar"
    assert {"ts_millis_open", "open", "high", "low", "close", "volume"} <= set(bars[-1])
