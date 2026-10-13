"""Tests for the ETF grid API router: request model (unit) and endpoints (db integration)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from spectres.config import settings
from spectres.db.postgres import get_postgres_db
from spectres.extensions.base import ExtensionContext
from spectres.extensions.etf_grid import extension as etf_grid_extension
from spectres.extensions.etf_grid.api import TradeCreate, create_router
from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.models import EtfGridBase, EtfGridCandle, EtfGridSignal, EtfGridTrade, EtfGridValuation
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
)
from spectres.extensions.etf_grid.types import CandleInput, Side


@pytest.mark.unit
class TestTradeCreateModel:
    """The POST /trades request model mirrors record_trade's signature."""

    def test_valid_body(self) -> None:
        """A well-formed body parses with typed fields."""
        body = TradeCreate(symbol="513330.XSHG", trade_date=date(2026, 8, 19), side="buy", price=Decimal("0.4100"), quantity=24300, commission_rate=Decimal("0.001"))
        assert body.price == Decimal("0.4100")
        assert body.note is None
        assert body.commission is None

    def test_negative_price_rejected(self) -> None:
        """Non-positive prices fail validation (422 at the endpoint)."""
        with pytest.raises(ValidationError):
            TradeCreate(symbol="513330.XSHG", trade_date=date(2026, 8, 19), side="buy", price=Decimal("0"), quantity=100, commission_rate=Decimal("0.001"))

    def test_invalid_side_rejected(self) -> None:
        """Sides outside buy/sell fail validation."""
        with pytest.raises(ValidationError):
            TradeCreate(symbol="513330.XSHG", trade_date=date(2026, 8, 19), side="hold", price=Decimal("0.4100"), quantity=100, commission_rate=Decimal("0.001"))  # type: ignore[arg-type]


@pytest.fixture
def api_client() -> TestClient:
    """A minimal FastAPI app mounting only the etf_grid router over cleaned tables."""
    engine = get_postgres_db().db_engine
    EtfGridBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session, session.begin():
        for table in (EtfGridSignal, EtfGridValuation, EtfGridCandle, EtfGridTrade):
            session.execute(delete(table))
    config = EtfGridConfig()  # type: ignore[call-arg]  # required fields come from .env.test
    app = FastAPI()
    app.include_router(
        create_router(
            config=config,
            ledger_service=EtfGridLedgerService(session_factory=session_factory),
            candle_service=EtfGridCandleService(session_factory=session_factory),
            valuation_service=EtfGridValuationService(session_factory=session_factory),
            signal_service=EtfGridSignalService(session_factory=session_factory),
        )
    )
    return TestClient(app)


@pytest.fixture
def seeded(api_client: TestClient) -> TestClient:
    """The api_client with one trade, one candle, and 61 signal-ready candles seeded."""
    session_factory = sessionmaker(bind=get_postgres_db().db_engine)
    ledger = EtfGridLedgerService(session_factory=session_factory)
    candles = EtfGridCandleService(session_factory=session_factory)
    ledger.record_trade(trade_date=date(2026, 8, 19), symbol="513330.XSHG", side=Side.BUY, price=Decimal("0.4100"), quantity=24300, commission_rate=Decimal("0.001"), commission=Decimal("9.96"))
    start = date(2026, 1, 1)
    candles.upsert_candles(
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


@pytest.mark.integration
@pytest.mark.db
class TestEtfGridApi:
    """All six endpoints via TestClient against real Postgres."""

    def test_get_status(self, seeded: TestClient) -> None:
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

    def test_post_trades_and_get_trades(self, seeded: TestClient) -> None:
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

    def test_get_trades_pagination_windowing(self, seeded: TestClient) -> None:
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

    def test_list_endpoints_reject_invalid_pagination_params(self, api_client: TestClient) -> None:
        """limit=0 / negative limit / negative offset are 422 with the canonical detail list."""
        for params in ({"limit": 0}, {"limit": -1}, {"limit": 201}, {"offset": -1}):
            for path in ("trades", "signals"):
                response = api_client.get(f"/api/v1/extensions/etf-grid/{path}", params=params)
                assert response.status_code == 422, f"{path} {params}"
                detail = response.json()["detail"]
                assert isinstance(detail, list) and detail, detail
                assert all({"loc", "msg", "type"} <= set(item) for item in detail)

    def test_post_trades_validation_errors(self, api_client: TestClient) -> None:
        """Pydantic and domain rejections share one 422 shape: detail is a list of {loc, msg, type} objects."""
        # Pydantic body rejection (negative price).
        response = api_client.post(
            "/api/v1/extensions/etf-grid/trades",
            json={"symbol": "513330.XSHG", "trade_date": "2026-09-09", "side": "buy", "price": "-1", "quantity": 100, "commission_rate": "0.001"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, list) and detail
        assert all({"loc", "msg", "type"} <= set(item) for item in detail)

        # Domain rejection (unknown symbol) — same shape, single element at loc ["body"].
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

    def test_post_signals_compute_and_get_signals(self, seeded: TestClient) -> None:
        """POST /signals/compute computes from local data; GET /signals reads history back."""
        response = seeded.post("/api/v1/extensions/etf-grid/signals/compute")
        assert response.status_code == 200
        body = response.json()
        signal = body["signals"]["513330.XSHG"]
        assert signal["level"] == -3
        triggered = next(o for o in signal["orders"] if o["kind"] == "triggered")
        assert triggered["side"] == "buy"
        assert triggered["grids"] == 3

        response = seeded.get("/api/v1/extensions/etf-grid/signals", params={"symbol": "513330.XSHG"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["level"] == -3
        assert body["items"][0]["computed_at"] is not None

        # offset windows over the same envelope.
        page = seeded.get("/api/v1/extensions/etf-grid/signals", params={"symbol": "513330.XSHG", "limit": 1, "offset": 1}).json()
        assert page["items"] == [] and page["total"] == 1

    def test_post_sync_never_500s_on_provider_failure(self, api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """POST /sync reports per-source errors in the body instead of failing."""
        monkeypatch.setattr(
            "spectres.extensions.etf_grid.api.sync_market_data",
            lambda **kwargs: {"candles": None, "valuation": None, "errors": {"candles": "boom", "valuation": "boom"}},
        )
        response = api_client.post("/api/v1/extensions/etf-grid/sync")
        assert response.status_code == 200
        assert response.json()["errors"] == {"candles": "boom", "valuation": "boom"}

    def test_register_creates_tables_idempotently(self) -> None:
        """register() is idempotent and returns the toolkit + router contribution."""
        ctx = ExtensionContext(settings=settings, db=get_postgres_db())
        first = etf_grid_extension.register(ctx)
        second = etf_grid_extension.register(ctx)
        for contribution in (first, second):
            assert len(contribution.toolkits) == 1
            assert contribution.toolkits[0].name == "etf_grid"
            assert len(contribution.routers) == 1
            assert contribution.routers[0].prefix == "/api/v1/extensions/etf-grid"
