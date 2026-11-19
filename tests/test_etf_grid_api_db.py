"""ETF Grid REST endpoints against real Postgres and Extension registration."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from spectres.config import settings
from spectres.db.postgres import get_postgres_db
from spectres.extensions.base import ExtensionContext
from spectres.extensions.etf_grid import extension as etf_grid_extension
from spectres.extensions.etf_grid.api import create_router
from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
)
from spectres.extensions.etf_grid.types import CandleInput, Side
from tests.support import add_test_identity, migrated_extension_session_factory

pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Provide a session factory over migrated ETF Grid tables."""
    return migrated_extension_session_factory("etf_grid")


@pytest.fixture
def api_client(session_factory: sessionmaker[Session]) -> TestClient:
    """A minimal FastAPI app mounting only the etf_grid router over real services."""
    app = FastAPI()
    add_test_identity(app)
    app.include_router(
        create_router(
            config=EtfGridConfig(),  # type: ignore[call-arg]  # required fields come from .env.test
            ledger_service=EtfGridLedgerService(session_factory=session_factory),
            candle_service=EtfGridCandleService(session_factory=session_factory),
            valuation_service=EtfGridValuationService(session_factory=session_factory),
            signal_service=EtfGridSignalService(session_factory=session_factory),
        )
    )
    return TestClient(app)


@pytest.fixture
def seeded(api_client: TestClient, session_factory: sessionmaker[Session]) -> TestClient:
    """The api_client with one trade and 61 signal-ready candles seeded."""
    EtfGridLedgerService(session_factory=session_factory).record_trade(
        user_id="alice", trade_date=date(2026, 8, 19), symbol="513330.XSHG", side=Side.BUY, price=Decimal("0.4100"), quantity=24300, commission_rate=Decimal("0.001"), commission=Decimal("9.96")
    )
    start = date(2026, 1, 1)
    EtfGridCandleService(session_factory=session_factory).upsert_candles(
        [
            CandleInput(
                symbol="513330.XSHG",
                trade_date=start + timedelta(days=i),
                open=Decimal("1.0000"),
                high=Decimal("1.0000"),
                low=Decimal("1.0000"),
                close=Decimal("0.9000") if i == 60 else Decimal("1.0000"),
                volume=1000,
            )
            for i in range(61)
        ]
    )
    return api_client


def test_get_status(seeded: TestClient) -> None:
    """GET /status returns the normalized portfolio payload."""
    response = seeded.get("/api/v1/extensions/etf-grid/status")
    assert response.status_code == 200
    rows = response.json()
    row = next(r for r in rows if r["symbol"] == "513330.XSHG")
    assert row["shares"] == 24300
    assert row["avg_cost"] == str(Decimal("9972.96") / 24300)
    assert row["close"] == "0.9000"
    # Unrealized P&L: close x shares - avg_cost x shares, stringified.
    avg_cost = Decimal("9972.96") / 24300
    unrealized = Decimal("0.9000") * 24300 - avg_cost * 24300
    assert row["unrealized"] == str(unrealized)
    assert row["unrealized_percent"] == str(unrealized / (avg_cost * 24300))
    # No position and no candles: both fields are null, not zero.
    for other in ("513120.XSHG", "513530.XSHG"):
        row = next(r for r in rows if r["symbol"] == other)
        assert row["unrealized"] is None
        assert row["unrealized_percent"] is None


def test_post_trades_and_get_trades(seeded: TestClient) -> None:
    """POST /trades echoes computed amounts; GET /trades filters by symbol and date range."""
    response = seeded.post(
        "/api/v1/extensions/etf-grid/trades",
        json={"symbol": "513330.XSHG", "trade_date": "2026-09-09", "side": "buy", "price": "0.3590", "quantity": 27700, "commission_rate": "0.001"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["gross_amount"] == "9944.30"
    assert body["commission"] == "9.94"
    assert body["net_amount"] == "9954.24"

    response = seeded.get("/api/v1/extensions/etf-grid/trades", params={"symbol": "513330.XSHG", "start": "2026-09-01", "end": "2026-09-30"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["trade_date"] == "2026-09-09"

    response = seeded.get("/api/v1/extensions/etf-grid/trades", params={"limit": 1})
    body = response.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2


def test_get_trades_pagination_windowing(seeded: TestClient) -> None:
    """offset/limit page through the full result set; total is the post-filter count."""
    seeded.post(
        "/api/v1/extensions/etf-grid/trades",
        json={"symbol": "513330.XSHG", "trade_date": "2026-09-09", "side": "buy", "price": "0.3590", "quantity": 27700, "commission_rate": "0.001"},
    )
    # Newest first: page 1 is the 2026-09-09 trade, page 2 the seeded 2026-08-19 one.
    page1 = seeded.get("/api/v1/extensions/etf-grid/trades", params={"limit": 1, "offset": 0}).json()
    page2 = seeded.get("/api/v1/extensions/etf-grid/trades", params={"limit": 1, "offset": 1}).json()
    assert page1["total"] == 2 and page2["total"] == 2
    assert page1["items"][0]["trade_date"] == "2026-09-09"
    assert page2["items"][0]["trade_date"] == "2026-08-19"
    # Filters apply before counting: the date range excludes the seeded trade.
    filtered = seeded.get("/api/v1/extensions/etf-grid/trades", params={"start": "2026-09-01", "end": "2026-09-30", "limit": 1}).json()
    assert filtered["total"] == 1
    # Past the end: empty page, real total.
    beyond = seeded.get("/api/v1/extensions/etf-grid/trades", params={"offset": 5}).json()
    assert beyond["items"] == [] and beyond["total"] == 2


def test_post_trades_domain_rejection_uses_validation_shape(api_client: TestClient) -> None:
    """A service-level rejection (unknown symbol) returns the canonical one-item 422 detail."""
    response = api_client.post(
        "/api/v1/extensions/etf-grid/trades",
        json={"symbol": "513330", "trade_date": "2026-09-09", "side": "buy", "price": "0.3590", "quantity": 100, "commission_rate": "0.001"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1
    assert detail[0]["loc"] == ["body"]
    assert detail[0]["type"] == "value_error"
    assert detail[0]["msg"]


def test_post_signals_compute(seeded: TestClient) -> None:
    """POST /signals/compute computes from local data and persists the snapshot."""
    response = seeded.post("/api/v1/extensions/etf-grid/signals/compute")
    assert response.status_code == 200
    body = response.json()
    signal = body["signals"]["513330.XSHG"]
    assert signal["level"] == -3
    triggered = next(o for o in signal["orders"] if o["kind"] == "triggered")
    assert triggered["side"] == "buy"
    assert triggered["grids"] == 3


def test_two_user_portfolios_and_ledgers_are_isolated(seeded: TestClient) -> None:
    """Caller identity, not a payload user_id, determines ledger ownership."""
    bob_headers = {"x-test-user": "bob"}
    bob_status = seeded.get("/api/v1/extensions/etf-grid/status", headers=bob_headers)
    bob_row = next(row for row in bob_status.json() if row["symbol"] == "513330.XSHG")
    assert bob_row["shares"] == 0
    assert seeded.get("/api/v1/extensions/etf-grid/trades", headers=bob_headers).json()["total"] == 0

    created = seeded.post(
        "/api/v1/extensions/etf-grid/trades",
        headers=bob_headers,
        json={
            "user_id": "alice",
            "symbol": "513330.XSHG",
            "trade_date": "2026-09-09",
            "side": "buy",
            "price": "0.3590",
            "quantity": 1000,
            "commission_rate": "0.001",
        },
    )
    assert created.status_code == 201
    assert created.json()["user_id"] == "bob"
    assert seeded.get("/api/v1/extensions/etf-grid/trades", headers=bob_headers).json()["total"] == 1
    assert seeded.get("/api/v1/extensions/etf-grid/trades").json()["total"] == 1

    bob_row = next(row for row in seeded.get("/api/v1/extensions/etf-grid/status", headers=bob_headers).json() if row["symbol"] == "513330.XSHG")
    alice_row = next(row for row in seeded.get("/api/v1/extensions/etf-grid/status").json() if row["symbol"] == "513330.XSHG")
    assert bob_row["shares"] == 1000
    assert alice_row["shares"] == 24300


def test_register_creates_tables_idempotently() -> None:
    """register() is idempotent and declares the extension surfaces."""
    ctx = ExtensionContext(settings=settings, db=get_postgres_db())
    first = etf_grid_extension.register(ctx)
    second = etf_grid_extension.register(ctx)
    for contribution in (first, second):
        assert len(contribution.toolkits) == 1
        assert contribution.toolkits[0].name == "etf_grid"
        assert len(contribution.routers) == 1
        assert contribution.routers[0].prefix == "/api/v1/extensions/etf-grid"
        assert len(contribution.schedules) == 1
        spec = contribution.schedules[0]
        assert spec.name == "ETF Grid Daily Sync"
        assert spec.cron == "0 9 * * 1,5"
        assert spec.timezone == "Asia/Shanghai"
        assert spec.endpoint == "/workflows/etf_grid_data_sync/runs"
        assert spec.payload == {"message": "Run scheduled ETF Grid shared-data synchronization"}
        assert spec.enabled is True
        assert [workflow.id for workflow in contribution.workflows] == ["etf_grid_data_sync", "etf_grid_recompute"]


def test_register_injects_same_services_into_all_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST, Toolkit, and Workflow factories receive one registration-scoped service set."""
    from spectres.extensions.etf_grid.toolkit import EtfGridToolkit
    from spectres.extensions.etf_grid.workflows import create_workflows

    calls: dict[str, dict[str, Any]] = {}

    def capture(name: str, factory: Any) -> Any:
        def wrapped(**kwargs: Any) -> Any:
            calls[name] = kwargs
            return factory(**kwargs)

        return wrapped

    monkeypatch.setattr("spectres.extensions.etf_grid.api.create_router", capture("router", create_router))
    monkeypatch.setattr("spectres.extensions.etf_grid.toolkit.EtfGridToolkit", capture("toolkit", EtfGridToolkit))
    monkeypatch.setattr("spectres.extensions.etf_grid.workflows.create_workflows", capture("workflows", create_workflows))

    etf_grid_extension.register(ExtensionContext(settings=settings, db=get_postgres_db()))

    assert set(calls) == {"router", "toolkit", "workflows"}
    service_names = ("ledger_service", "candle_service", "valuation_service", "signal_service")
    for adapter in ("toolkit", "workflows"):
        for service_name in service_names:
            assert calls[adapter][service_name] is calls["router"][service_name]
