"""Unit tests for the ETF grid Agno toolkit (mocked services, no database)."""

import json
import logging
import logging.handlers
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from spectres.config import settings
from spectres.extensions.etf_grid.config import EtfGridConfig, PortfolioItem
from spectres.extensions.etf_grid.service import EtfGridLedgerService
from spectres.extensions.etf_grid.toolkit import EtfGridToolkit
from spectres.extensions.etf_grid.types import Side, Source
from spectres.logging import configure_logging, log_file_for_today

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
    """get_grid_status normalizes service output into the success envelope."""

    def test_decimals_and_dates_normalized(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decimals become strings, dates ISO strings; the payload is JSON-serializable."""
        canned = [{"symbol": "513330.XSHG", "avg_cost": Decimal("0.3724"), "close_date": date(2026, 9, 24), "signal": None}]
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.get_portfolio_status", lambda **kwargs: canned)
        toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
        result = toolkit.get_grid_status()
        assert result["ok"] is True
        data = result["data"]
        assert data[0]["avg_cost"] == "0.3724"
        assert data[0]["close_date"] == "2026-09-24"
        _assert_jsonable(result)


class TestRefreshGridData:
    """refresh_grid_data composes the sync pipeline with signal computation."""

    def test_merges_refresh_and_signals(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """The data payload carries per-source counts/errors plus signals and skipped."""
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
        assert result["ok"] is True
        assert result["data"]["candles"] == {"513330.XSHG": 5}
        assert result["data"]["valuation"] == 2400
        assert result["data"]["signals"] == {"513330.XSHG": {"level": -3}}
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
        assert result["ok"] is True
        assert result["data"]["net_amount"] == "9972.96"
        _assert_jsonable(result)


class TestListGridTrades:
    """list_grid_trades returns newest-first rows capped by limit."""

    def test_limit_and_ordering(self, config: EtfGridConfig) -> None:
        """Rows come back newest-first, sliced to limit, order pushed to the service."""
        ledger = FakeLedger()
        ledger.rows = [{"id": i, "trade_date": date(2026, 9, 1), "net_amount": Decimal("1.00")} for i in range(25)]
        toolkit = EtfGridToolkit(config=config, ledger_service=ledger)
        result = toolkit.list_grid_trades(symbol="513330.XSHG")
        assert result["ok"] is True
        assert len(result["data"]) == 20
        assert ledger.list_kwargs["symbol"] == "513330.XSHG"
        order_by = ledger.list_kwargs["order_by"]
        assert order_by[0].direction.value == "desc"
        assert result["data"][0]["net_amount"] == "1.00"
        _assert_jsonable(result)


class TestErrorContract:
    """Tool failures return the structured error envelope instead of raising."""

    def test_invalid_input_returns_structured_error(self, config: EtfGridConfig) -> None:
        """An unknown side yields ok=False with type/message/trace_id/hint; no service call happens."""
        ledger = FakeLedger()
        toolkit = EtfGridToolkit(config=config, ledger_service=ledger)
        result = toolkit.record_grid_trade(symbol="513330.XSHG", trade_date="2026-08-19", side="hold", price="0.4100", quantity=100, commission_rate="0.001")
        assert result["ok"] is False
        error = result["error"]
        assert error["type"] == "ValueError"
        assert "hold" in error["message"]
        assert error["trace_id"]
        assert error["trace_id"] in error["hint"]
        assert f"logs/runtime-{date.today():%Y-%m-%d}.jsonl" in error["hint"]
        assert ledger.recorded == {}  # validation failed before any service call
        _assert_jsonable(result)

    def test_service_failure_returns_structured_error(self, config: EtfGridConfig) -> None:
        """An exception from the service layer is wrapped the same way."""
        ledger = FakeLedger()

        def _raise(*args: Any, **kwargs: Any) -> Any:
            """Simulate a service-layer failure."""
            raise RuntimeError("db down")

        ledger.list_trades = _raise  # type: ignore[method-assign]
        toolkit = EtfGridToolkit(config=config, ledger_service=ledger)
        result = toolkit.list_grid_trades()
        assert result["ok"] is False
        assert result["error"]["type"] == "RuntimeError"
        assert result["error"]["message"] == "db down"

    def test_error_trace_id_greppable_in_jsonl_log(self, config: EtfGridConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """End-to-end: a failing tool's trace_id finds its ERROR record in the real JSONL file.

        Mirrors exactly what the agent does with its shell tool: run the
        hint's grep against logs/runtime-<today>.jsonl.
        """
        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        monkeypatch.setattr(settings, "log_dir", str(tmp_path))
        try:
            configure_logging(settings)
            toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
            result = toolkit.record_grid_trade(symbol="513330.XSHG", trade_date="2026-08-19", side="hold", price="0.4100", quantity=100, commission_rate="0.001")
            for handler in root.handlers:
                handler.flush()
            trace_id = result["error"]["trace_id"]
            log_file = log_file_for_today(tmp_path)
            matching = [json.loads(line) for line in log_file.read_text().splitlines() if trace_id in line]
            assert len(matching) == 1
            record = matching[0]
            assert record["level"] == "ERROR"
            assert record["event"] == "tool_failed"
            assert record["extension"] == "etf_grid"
            assert record["trace_id"] == trace_id
            assert record["exc_info"]["type"] == "ValueError"
            # The hint references the file the agent actually has to grep.
            assert str(log_file) in result["error"]["hint"]
        finally:
            for handler in list(root.handlers):
                root.removeHandler(handler)
            for handler in handlers:
                root.addHandler(handler)
            root.setLevel(level)


def test_toolkit_registers_four_functions(config: EtfGridConfig) -> None:
    """The toolkit exposes exactly the four planned tool functions."""
    toolkit = EtfGridToolkit(config=config, ledger_service=FakeLedger())
    assert set(toolkit.functions) == {"get_grid_status", "refresh_grid_data", "record_grid_trade", "list_grid_trades"}
