"""Unit tests for the ETF grid Agno toolkit (mocked services, no database)."""

import json
import logging
import logging.handlers
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from agno.run import RunContext

from spectres.config import settings
from spectres.extensions.etf_grid.config import EtfGridConfig, PortfolioItem
from spectres.extensions.etf_grid.service import EtfGridCandleService, EtfGridLedgerService, EtfGridSignalService, EtfGridValuationService
from spectres.extensions.etf_grid.toolkit import EtfGridToolkit
from spectres.extensions.etf_grid.types import Side, Source
from spectres.logging import configure_logging, log_file_for_today

pytestmark = pytest.mark.unit


@pytest.fixture
def config() -> EtfGridConfig:
    """A minimal config with one portfolio entry."""
    return EtfGridConfig(
        portfolio=[PortfolioItem(symbol="513330.XSHG", name="恒生互联网ETF", grid_step=Decimal("0.05"), per_grid_amount=10000, max_grids=15)],
        candle_lookback_days=90,
        backfill_start_date=date(2021, 1, 1),
        sync_schedule_enabled=True,
        sync_cron="0 9 * * 1,5",
        sync_timezone="Asia/Shanghai",
        sync_max_retries=2,
        sync_retry_delay_seconds=300,
    )


def _context(user_id: str = "alice") -> RunContext:
    return RunContext(run_id="run", session_id="session", user_id=user_id)


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
        """Record the call and emulate the service's SQL limit."""
        self.list_kwargs = {"symbol": symbol, **kwargs}
        limit = kwargs.get("limit")
        return self.rows[:limit] if limit is not None else self.rows


def _make_toolkit(config: EtfGridConfig, ledger: EtfGridLedgerService | None = None) -> EtfGridToolkit:
    return EtfGridToolkit(
        config=config,
        ledger_service=ledger or FakeLedger(),
        candle_service=MagicMock(spec=EtfGridCandleService),
        valuation_service=MagicMock(spec=EtfGridValuationService),
        signal_service=MagicMock(spec=EtfGridSignalService),
    )


def _assert_jsonable(value: Any) -> None:
    """Round-trip through json.dumps to prove serializability."""
    json.dumps(value)


class TestGetGridStatus:
    """get_grid_status normalizes service output into the success envelope."""

    def test_decimals_and_dates_normalized(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decimals become strings, dates ISO strings; the payload is JSON-serializable."""
        canned = [{"symbol": "513330.XSHG", "avg_cost": Decimal("0.3724"), "close_date": date(2026, 9, 24), "signal": None}]
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.get_portfolio_status", lambda **kwargs: canned)
        toolkit = _make_toolkit(config)
        result = toolkit.get_grid_status(_context())
        assert result["ok"] is True
        data = result["data"]
        assert data[0]["avg_cost"] == "0.3724"
        assert data[0]["close_date"] == "2026-09-24"
        _assert_jsonable(result)


class TestSyncGridData:
    """sync_grid_data performs only shared-data synchronization."""

    async def test_sync_runs_off_event_loop_without_computing(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """The provider pipeline runs in a worker and never calls signal computation."""
        thread_ids: list[int] = []

        def fake_sync(**kwargs: Any) -> dict[str, Any]:
            thread_ids.append(threading.get_ident())
            return {"candles": {"513330.XSHG": 5}, "valuation": 2400, "errors": {}}

        compute = MagicMock()
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.sync_market_data", fake_sync)
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.compute_daily_signals", compute)
        toolkit = _make_toolkit(config)
        result = await toolkit.sync_grid_data(_context())
        assert result == {"ok": True, "data": {"candles": {"513330.XSHG": 5}, "valuation": 2400, "errors": {}}}
        compute.assert_not_called()
        assert len(thread_ids) == 1
        assert thread_ids[0] != threading.get_ident()
        _assert_jsonable(result)

    async def test_missing_identity_fails_before_sync(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shared sync still requires an authenticated run owner."""
        sync = MagicMock()
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.sync_market_data", sync)
        result = await _make_toolkit(config).sync_grid_data(_context(user_id=""))
        assert result["ok"] is False
        assert result["error"]["type"] == "PermissionError"
        sync.assert_not_called()


class TestComputeGridSignals:
    """compute_grid_signals uses only the verified run owner and persisted data."""

    def test_compute_uses_run_owner_without_sync(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """Compute uses the run context and never calls the provider pipeline."""
        compute = MagicMock(return_value={"signals": {"513330.XSHG": {"level": -3}}, "skipped": {}})
        sync = MagicMock()
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.compute_daily_signals", compute)
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.sync_market_data", sync)
        result = _make_toolkit(config).compute_grid_signals(_context())
        assert result == {"ok": True, "data": {"signals": {"513330.XSHG": {"level": -3}}, "skipped": {}}}
        assert compute.call_args.kwargs["user_id"] == "alice"
        sync.assert_not_called()

    def test_each_run_uses_its_own_owner(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """Separate runs cannot share or override ownership."""
        owners: list[str] = []

        def compute(**kwargs: Any) -> dict[str, Any]:
            owners.append(kwargs["user_id"])
            return {"signals": {}, "skipped": {}}

        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.compute_daily_signals", compute)
        toolkit = _make_toolkit(config)
        toolkit.compute_grid_signals(_context("alice"))
        toolkit.compute_grid_signals(_context("bob"))
        assert owners == ["alice", "bob"]

    def test_missing_identity_fails_before_compute(self, config: EtfGridConfig, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unowned run cannot recompute private signals."""
        compute = MagicMock()
        monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.compute_daily_signals", compute)
        result = _make_toolkit(config).compute_grid_signals(_context(user_id=""))
        assert result["ok"] is False
        assert result["error"]["type"] == "PermissionError"
        compute.assert_not_called()


class TestRecordGridTrade:
    """record_grid_trade translates tool arguments into service calls."""

    def test_arguments_translated(self, config: EtfGridConfig) -> None:
        """String inputs become date/Side/Decimal; source is AGENT; output normalized."""
        ledger = FakeLedger()
        toolkit = _make_toolkit(config, ledger)
        result = toolkit.record_grid_trade(
            run_context=_context(),
            symbol="513330.XSHG",
            trade_date="2026-08-19",
            side="buy",
            price="0.4100",
            quantity=24300,
            commission_rate="0.001",
            note="opening position backfill",
        )
        call = ledger.recorded
        assert call["user_id"] == "alice"
        assert call["trade_date"] == date(2026, 8, 19)
        assert call["side"] is Side.BUY
        assert call["price"] == Decimal("0.4100")
        assert call["commission_rate"] == Decimal("0.001")
        assert call["source"] is Source.AGENT
        assert result["ok"] is True
        assert result["data"]["net_amount"] == "9972.96"
        _assert_jsonable(result)


class TestListGridTrades:
    """list_grid_trades returns newest-first rows capped in SQL by limit."""

    def test_limit_and_ordering(self, config: EtfGridConfig) -> None:
        """Limit and order are pushed to the service instead of slicing all rows."""
        ledger = FakeLedger()
        ledger.rows = [{"id": i, "trade_date": date(2026, 9, 1), "net_amount": Decimal("1.00")} for i in range(25)]
        toolkit = _make_toolkit(config, ledger)
        result = toolkit.list_grid_trades(_context(), symbol="513330.XSHG")
        assert result["ok"] is True
        assert len(result["data"]) == 20
        assert ledger.list_kwargs["symbol"] == "513330.XSHG"
        assert ledger.list_kwargs["user_id"] == "alice"
        assert ledger.list_kwargs["limit"] == 20
        order_by = ledger.list_kwargs["order_by"]
        assert order_by[0].direction.value == "desc"
        _assert_jsonable(result)

    @pytest.mark.parametrize("limit", [0, -1, 201])
    def test_invalid_limit_fails_without_query(self, config: EtfGridConfig, limit: int) -> None:
        """Out-of-range limits return a structured error without reading the ledger."""
        ledger = FakeLedger()
        result = _make_toolkit(config, ledger).list_grid_trades(_context(), limit=limit)
        assert result["ok"] is False
        assert result["error"]["type"] == "ValueError"
        assert "between 1 and 200" in result["error"]["message"]
        assert ledger.list_kwargs == {}


class TestErrorContract:
    """Tool failures return the structured error envelope instead of raising."""

    def test_invalid_input_returns_structured_error(self, config: EtfGridConfig) -> None:
        """An unknown side yields ok=False with type/message/trace_id/hint; no service call happens."""
        ledger = FakeLedger()
        toolkit = _make_toolkit(config, ledger)
        result = toolkit.record_grid_trade(run_context=_context(), symbol="513330.XSHG", trade_date="2026-08-19", side="hold", price="0.4100", quantity=100, commission_rate="0.001")
        assert result["ok"] is False
        error = result["error"]
        assert error["type"] == "ValueError"
        assert "hold" in error["message"]
        assert error["trace_id"]
        assert error["trace_id"] in error["hint"]
        assert f"logs/runtime-{date.today():%Y-%m-%d}.jsonl" in error["hint"]
        assert ledger.recorded == {}
        _assert_jsonable(result)

    def test_missing_run_identity_fails_closed(self, config: EtfGridConfig) -> None:
        """A tool without an authenticated run owner cannot read the ledger."""
        ledger = FakeLedger()
        result = _make_toolkit(config, ledger).list_grid_trades(_context(user_id=""))
        assert result["ok"] is False
        assert result["error"]["type"] == "PermissionError"
        assert ledger.list_kwargs == {}

    def test_service_failure_returns_structured_error(self, config: EtfGridConfig) -> None:
        """An exception from the service layer is wrapped the same way."""
        ledger = FakeLedger()

        def _raise(*args: Any, **kwargs: Any) -> Any:
            """Simulate a service-layer failure."""
            raise RuntimeError("db down")

        ledger.list_trades = _raise  # type: ignore[method-assign]
        result = _make_toolkit(config, ledger).list_grid_trades(_context())
        assert result["ok"] is False
        assert result["error"]["type"] == "RuntimeError"
        assert result["error"]["message"] == "db down"

    def test_error_trace_id_greppable_in_jsonl_log(self, config: EtfGridConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """End-to-end: a failing tool's trace_id finds its ERROR record in the real JSONL file."""
        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        monkeypatch.setattr(settings, "log_dir", str(tmp_path))
        try:
            configure_logging(settings)
            toolkit = _make_toolkit(config)
            result = toolkit.record_grid_trade(run_context=_context(), symbol="513330.XSHG", trade_date="2026-08-19", side="hold", price="0.4100", quantity=100, commission_rate="0.001")
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
            assert str(log_file) in result["error"]["hint"]
        finally:
            for handler in list(root.handlers):
                root.removeHandler(handler)
            for handler in handlers:
                root.addHandler(handler)
            root.setLevel(level)


def test_toolkit_registers_five_functions(config: EtfGridConfig) -> None:
    """The toolkit exposes five independent tools across sync and async registries."""
    toolkit = _make_toolkit(config)
    assert set(toolkit.functions) == {"get_grid_status", "compute_grid_signals", "record_grid_trade", "list_grid_trades"}
    assert set(toolkit.async_functions) == {"sync_grid_data"}
    record = toolkit.functions["record_grid_trade"]
    record.process_entrypoint()
    assert {"symbol", "trade_date", "side", "price", "quantity", "commission_rate"} <= set(record.parameters["properties"])
    assert "run_context" not in record.parameters["properties"]
    for function in (toolkit.async_functions["sync_grid_data"], toolkit.functions["compute_grid_signals"]):
        function.process_entrypoint()
        assert function.parameters["properties"] == {}
