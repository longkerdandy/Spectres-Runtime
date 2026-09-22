"""Unit tests for the ETF grid candle service validation paths."""

from datetime import date
from decimal import Decimal

import pytest

from spectres.extensions.etf_grid.service import EtfGridCandleService
from spectres.extensions.etf_grid.types import CandleInput

pytestmark = pytest.mark.unit


def candle(**overrides: object) -> CandleInput:
    """Build a valid candle input with per-field overrides."""
    values: dict[str, object] = {
        "symbol": "513330",
        "trade_date": date(2026, 9, 22),
        "open": Decimal("0.4000"),
        "high": Decimal("0.4100"),
        "low": Decimal("0.3900"),
        "close": Decimal("0.4050"),
        "volume": 123_456_789,
    }
    return CandleInput(**{**values, **overrides})  # type: ignore[arg-type]


class _FailingSessionFactory:
    """Session factory that must never be called by validation-failure paths."""

    def __call__(self) -> None:
        """Fail loudly if the service touches the database on invalid input."""
        raise AssertionError("session factory must not be touched on validation failure")


def service() -> EtfGridCandleService:
    """Build a service whose session factory fails if ever called."""
    return EtfGridCandleService(session_factory=_FailingSessionFactory())  # type: ignore[arg-type]


class TestUpsertCandlesValidation:
    """upsert_candles rejects invalid input before touching the database."""

    @pytest.mark.parametrize("field", ["open", "high", "low", "close"])
    def test_zero_price_rejected(self, field: str) -> None:
        """A zero price in any OHLC field is rejected."""
        with pytest.raises(ValueError, match="candle prices must be positive"):
            service().upsert_candles([candle(**{field: Decimal("0")})])

    def test_negative_price_rejected(self) -> None:
        """A negative price is rejected."""
        with pytest.raises(ValueError, match="candle prices must be positive"):
            service().upsert_candles([candle(close=Decimal("-0.4050"))])

    def test_negative_volume_rejected(self) -> None:
        """A negative volume is rejected."""
        with pytest.raises(ValueError, match="volume must be non-negative"):
            service().upsert_candles([candle(volume=-1)])

    def test_later_invalid_row_rejects_whole_batch(self) -> None:
        """Validation scans the whole batch; an invalid later row fails fast."""
        with pytest.raises(ValueError, match="candle prices must be positive"):
            service().upsert_candles([candle(), candle(open=Decimal("0"))])

    def test_empty_batch_is_a_noop(self) -> None:
        """An empty batch writes nothing and does not touch the database."""
        assert service().upsert_candles([]) == 0
