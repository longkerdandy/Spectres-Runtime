"""Unit tests for the ETF grid Agno toolkit (mocked services, no database)."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from spectres.extensions.etf_grid.config import EtfGridConfig, PortfolioItem
from spectres.extensions.etf_grid.service import EtfGridLedgerService
from spectres.extensions.etf_grid.toolkit import EtfGridToolkit
from spectres.extensions.etf_grid.types import Side, Source

pytestmark = pytest.mark.unit


@pytest.fixture
def config() -> EtfGridConfig:
    """A minimal config with one portfolio entry."""
    return EtfGridConfig(
        portfolio=[PortfolioItem(symbol="513330.XSHG", name="恒生互联网ETF", per_grid_amount=10000, max_grids=15)],
        candle_lookback_days=90,
        backfill_start_date=date(2021, 1, 1),
        grid_step=Decimal("0.05"),
    )


class FakeLedger(EtfGridLedgerService):
    """In-memory ledger stand-in recording calls (no database)."""

    def __init__(self) -> None:
        """Set up with an empty call log and canned rows."""
        self.recorded: dict[str, Any] = {}
        self.list_kwargs: dict[str, Any] = {}
        self.rows: list[dict[str, Any]] = []

    def record_trade(self, **kwargs: Any) -> dict[str, Any]:
        """Record the call and return a canned persisted row."""
        self.recorded = kwargs
        return {"id": 1, "symbol": kwargs["symbol"], "net_amount": Decimal("9972.96"), "created_at": None}

    def list_trades(self, symbol: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """Record the call and return canned rows."""
        self.list_kwargs = {"symbol": symbol, **kwargs}
        return self.rows


def _assert_jsonable(value: Any) -> None:
    """Round-trip through json.dumps to prove serializability."""
    json.dumps(value)


class TestGetGridStatus:
    """get_grid_status normalizes service output to JSON-safe structures."""

    def test_decimals_and_dates_normalized(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decimals become strings, dates ISO strings; the payload is JSON-serializable."""
        canned = [{"symbol": "513330.XSHG", "avg_cost": Decimal("0.3724"), "close_date": date(2026, 9, 24), "signal": None}]
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.get_portfolio_status", lambda **kwargs: canned)
        toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
        result = toolkit.get_grid_status()
        assert result[0]["avg_cost"] == "0.3724"
        assert result[0]["close_date"] == "2026-09-24"
        _assert_jsonable(result)


class TestRefreshGridData:
    """refresh_grid_data composes the sync pipeline with signal computation."""

    def test_merges_refresh_and_signals(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """The result carries per-source counts/errors plus signals and skipped."""
        monkeypatch.setattr(
            "spectres.extensions.etf_grid.toolkit.sync_market_data",
            lambda **kwargs: {"candles": {"513330.XSHG": 5}, "valuation": 2400, "errors": {}},
        )
        monkeypatch.setattr(
            "spectres.extensions.etf_grid.toolkit.compute_daily_signals",
            lambda **kwargs: {"signals": {"513330.XSHG": {"level": -3}}, "skipped": {}},
        )
        toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
        result = toolkit.refresh_grid_data()
        assert result["candles"] == {"513330.XSHG": 5}
        assert result["valuation"] == 2400
        assert result["signals"] == {"513330.XSHG": {"level": -3}}
        _assert_jsonable(result)


class TestRecordGridTrade:
    """record_grid_trade translates tool arguments into service calls."""

    def test_arguments_translated(self, config: EtfGridConfig) -> None:
        """String inputs become date/Side/Decimal; source is AGENT; output normalized."""
        ledger = FakeLedger()
        toolkit = EtfGridToolkit(config=config, ledger_service=ledger)
        result = toolkit.record_grid_trade(
            symbol="513330.XSHG",
            trade_date="2026-08-19",
            side="buy",
            price="0.4100",
            quantity=24300,
            commission_rate="0.001",
            note="opening position backfill",
        )
        call = ledger.recorded
        assert call["trade_date"] == date(2026, 8, 19)
        assert call["side"] is Side.BUY
        assert call["price"] == Decimal("0.4100")
        assert call["commission_rate"] == Decimal("0.001")
        assert call["source"] is Source.AGENT
        assert result["net_amount"] == "9972.96"
        _assert_jsonable(result)

    def test_invalid_side_rejected(self, config: EtfGridConfig) -> None:
        """An unknown side fails before any service call."""
        toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
        with pytest.raises(ValueError, match="hold"):
            toolkit.record_grid_trade(symbol="513330.XSHG", trade_date="2026-08-19", side="hold", price="0.4100", quantity=100, commission_rate="0.001")


class TestListGridTrades:
    """list_grid_trades returns newest-first rows capped by limit."""

    def test_limit_and_ordering(self, config: EtfGridConfig) -> None:
        """Rows come back newest-first, sliced to limit, order pushed to the service."""
        ledger = FakeLedger()
        ledger.rows = [{"id": i, "trade_date": date(2026, 9, 1), "net_amount": Decimal("1.00")} for i in range(25)]
        toolkit = EtfGridToolkit(config=config, ledger_service=ledger)
        result = toolkit.list_grid_trades(symbol="513330.XSHG")
        assert len(result) == 20
        assert ledger.list_kwargs["symbol"] == "513330.XSHG"
        order_by = ledger.list_kwargs["order_by"]
        assert order_by[0].direction.value == "desc"
        assert result[0]["net_amount"] == "1.00"
        _assert_jsonable(result)


def test_toolkit_registers_four_functions(config: EtfGridConfig) -> None:
    """The toolkit exposes exactly the four planned tool functions."""
    toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
    assert set(toolkit.functions) == {"get_grid_status", "refresh_grid_data", "record_grid_trade", "list_grid_trades"}
