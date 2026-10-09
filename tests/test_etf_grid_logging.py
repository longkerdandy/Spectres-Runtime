"""Unit tests for etf_grid logging instrumentation (caplog over mocked I/O, no database)."""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectres.config import settings
from spectres.extensions.base import ExtensionContext
from spectres.extensions.etf_grid import extension as etf_grid_extension
from spectres.extensions.etf_grid.api import create_router
from spectres.extensions.etf_grid.config import EtfGridConfig, GateConfig, PortfolioItem
from spectres.extensions.etf_grid.csindex import MAX_ATTEMPTS, fetch_index_perf
from spectres.extensions.etf_grid.marketdata import sync_market_data
from spectres.extensions.etf_grid.models import EtfGridBase
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
    compute_daily_signals,
)
from spectres.extensions.etf_grid.types import Side, Source

pytestmark = pytest.mark.unit


@pytest.fixture
def config() -> EtfGridConfig:
    """A minimal config with one gated portfolio entry and no FTShare key."""
    return EtfGridConfig(
        ftshare_api_key=None,  # no key: the candles source fails at call time
        portfolio=[
            PortfolioItem(
                symbol="513530.XSHG",
                name="港股通红利ETF",
                per_grid_amount=10000,
                max_grids=7,
                gate=GateConfig(index_code="930914", metric="dyr", threshold=0.2, block_when="below"),
            )
        ],
        candle_lookback_days=90,
        backfill_start_date=date(2021, 1, 1),
        grid_step=Decimal("0.05"),
    )


def _records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    """Return captured records carrying the given structured event name."""
    return [record for record in caplog.records if getattr(record, "event", None) == event]


class TestExtensionRegisterLogging:
    """register() logs one INFO audit record on success."""

    def test_register_logs_symbols_and_contributions(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """The extension_registered record carries symbols and surface counts."""
        monkeypatch.setattr(EtfGridBase.metadata, "create_all", lambda *args, **kwargs: None)
        monkeypatch.setattr("spectres.extensions.etf_grid.service.get_session_factory", lambda: MagicMock())
        ctx = ExtensionContext(settings=settings, db=MagicMock())
        with caplog.at_level(logging.INFO, logger="spectres.extensions.etf_grid.extension"):
            contribution = etf_grid_extension.register(ctx)
        records = _records(caplog, "extension_registered")
        assert len(records) == 1
        record = records[0]
        assert record.levelname == "INFO"
        assert record.__dict__["symbols"] == ["513330.XSHG", "513120.XSHG", "513530.XSHG"]  # .env.test portfolio
        assert record.__dict__["toolkits"] == len(contribution.toolkits) == 1
        assert record.__dict__["routers"] == len(contribution.routers) == 1


class TestCsindexRetryLogging:
    """fetch_index_perf logs every retry at WARNING and the final failure at ERROR."""

    def test_retries_and_final_failure_logged(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """All attempts failing yields MAX_ATTEMPTS WARNINGs plus one ERROR before RuntimeError."""

        class FailingConnection:
            """HTTPSConnection stand-in whose request always fails."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                """Accept and ignore the real constructor arguments."""

            def request(self, *args: Any, **kwargs: Any) -> None:
                """Simulate a network failure."""
                raise OSError("connection refused")

            def close(self) -> None:
                """No-op."""

        monkeypatch.setattr("http.client.HTTPSConnection", FailingConnection)
        monkeypatch.setattr("spectres.extensions.etf_grid.csindex.time.sleep", lambda seconds: None)
        with caplog.at_level(logging.WARNING, logger="spectres.extensions.etf_grid.csindex"), pytest.raises(RuntimeError, match="failed after retries"):
            fetch_index_perf("930914")
        retries = _records(caplog, "csindex_retry")
        assert [record.__dict__["attempt"] for record in retries] == list(range(1, MAX_ATTEMPTS + 1))
        assert all(record.levelname == "WARNING" for record in retries)
        assert all("OSError" in record.__dict__["error"] for record in retries)
        failures = _records(caplog, "csindex_fetch_failed")
        assert len(failures) == 1
        assert failures[0].levelname == "ERROR"


class TestSyncMarketDataLogging:
    """sync_market_data logs per-source failures with exc_info plus an INFO summary."""

    def test_candles_failure_logged_with_exc_info(self, config: EtfGridConfig, caplog: pytest.LogCaptureFixture) -> None:
        """A missing API key surfaces as an ERROR with the traceback attached, not just str(exc)."""

        def fetcher(code: str) -> list[dict[str, Any]]:
            """Serve one synthetic valuation row so only the candles source fails."""
            row: dict[str, Any] = {"tradeDate": "20240102", "close": 1000.0}
            if code == "930914":
                row["peg"] = 20.0
            return [row]

        valuation = MagicMock(spec=EtfGridValuationService)
        valuation.upsert_valuation.return_value = 1
        with caplog.at_level(logging.INFO, logger="spectres.extensions.etf_grid.marketdata"):
            result = sync_market_data(config=config, candle_service=MagicMock(spec=EtfGridCandleService), valuation_service=valuation, fetcher=fetcher)
        assert "ETF_GRID_FTSHARE_API_KEY is required" in result["errors"]["candles"]
        assert result["valuation"] == 1

        failures = _records(caplog, "sync_source_failed")
        assert len(failures) == 1
        assert failures[0].levelname == "ERROR"
        assert failures[0].__dict__["source"] == "candles"
        assert failures[0].exc_info is not None and failures[0].exc_info[0] is ValueError

        summaries = _records(caplog, "sync_completed")
        assert len(summaries) == 1
        assert summaries[0].levelname == "INFO"
        assert summaries[0].__dict__["errors"] == result["errors"]


class TestTradeRecordedAudit:
    """Every successful record_trade emits a trade_recorded audit record."""

    def test_audit_record_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """The INFO record carries symbol/side/quantity/price/net_amount."""
        session_factory = MagicMock()
        ledger = EtfGridLedgerService(session_factory=session_factory)
        with caplog.at_level(logging.INFO, logger="spectres.extensions.etf_grid.service"):
            ledger.record_trade(
                trade_date=date(2026, 8, 19),
                symbol="513330.XSHG",
                side=Side.BUY,
                price=Decimal("0.4100"),
                quantity=24300,
                commission_rate=Decimal("0.001"),
                source=Source.AGENT,
            )
        records = _records(caplog, "trade_recorded")
        assert len(records) == 1
        record = records[0]
        assert record.levelname == "INFO"
        assert record.__dict__["symbol"] == "513330.XSHG"
        assert record.__dict__["side"] == "buy"
        assert record.__dict__["quantity"] == 24300
        assert record.__dict__["price"] == "0.4100"
        assert record.__dict__["net_amount"] == "9972.96"


class _FakeCandleService(EtfGridCandleService):
    """In-memory candle stand-in returning canned rows (no database)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """Set up with canned candles."""
        self._rows = rows

    def list_candles(self, symbol: str, *, descending: bool = False, limit: int | None = None) -> list[dict[str, Any]]:
        """Return the canned rows."""
        return self._rows


class _FakeValuationService(EtfGridValuationService):
    """In-memory valuation stand-in returning canned rows (no database)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """Set up with canned valuation rows."""
        self._rows = rows

    def list_valuation(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return the canned rows."""
        return self._rows


class _FakeLedgerService(EtfGridLedgerService):
    """In-memory ledger stand-in with no positions (no database)."""

    def __init__(self) -> None:
        """No state needed."""

    def get_positions(self) -> dict[str, Any]:
        """Return no positions."""
        return {}


class TestSignalSkipLogging:
    """compute_daily_signals logs gate skips at DEBUG."""

    def test_gate_skip_logged_at_debug(self, config: EtfGridConfig, caplog: pytest.LogCaptureFixture) -> None:
        """A gated symbol with an empty valuation series is skipped with a DEBUG record."""
        candles = [{"trade_date": date(2026, 1, 1) + timedelta(days=i), "close": Decimal("1.0000")} for i in range(62)]
        with caplog.at_level(logging.DEBUG, logger="spectres.extensions.etf_grid.service"):
            result = compute_daily_signals(
                config=config,
                ledger_service=_FakeLedgerService(),
                candle_service=_FakeCandleService(candles),
                valuation_service=_FakeValuationService([]),
                signal_service=MagicMock(spec=EtfGridSignalService),
            )
        assert result["skipped"] == {"513530.XSHG": "no_valuation_data"}
        records = _records(caplog, "signal_skipped")
        assert len(records) == 1
        assert records[0].levelname == "DEBUG"
        assert records[0].__dict__["symbol"] == "513530.XSHG"
        assert records[0].__dict__["reason"] == "no_valuation_data"


class TestApiRejectionLogging:
    """ValueError-to-422 conversions are logged at WARNING."""

    def test_invalid_trade_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A service-level validation failure produces a trade_rejected WARNING and HTTP 422."""
        ledger = MagicMock(spec=EtfGridLedgerService)
        ledger.record_trade.side_effect = ValueError("price must be positive, got 0")
        app = FastAPI()
        app.include_router(
            create_router(
                ledger_service=ledger,
                candle_service=MagicMock(spec=EtfGridCandleService),
                valuation_service=MagicMock(spec=EtfGridValuationService),
                signal_service=MagicMock(spec=EtfGridSignalService),
            )
        )
        client = TestClient(app, raise_server_exceptions=False)
        body = {
            "symbol": "513330.XSHG",
            "trade_date": "2026-08-19",
            "side": "buy",
            "price": "0.4100",
            "quantity": 100,
            "commission_rate": "0.001",
        }
        with caplog.at_level(logging.WARNING, logger="spectres.extensions.etf_grid.api"):
            response = client.post("/api/v1/extensions/etf-grid/trades", json=body)
        assert response.status_code == 422
        records = _records(caplog, "trade_rejected")
        assert len(records) == 1
        assert records[0].levelname == "WARNING"
        assert records[0].__dict__["symbol"] == "513330.XSHG"
