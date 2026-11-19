"""Unit tests for the ETF Grid REST adapter with service doubles."""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from spectres.extensions.etf_grid.api import create_router
from spectres.extensions.etf_grid.config import EtfGridConfig
from spectres.extensions.etf_grid.schemas import TradeCreate
from spectres.extensions.etf_grid.service import (
    EtfGridCandleService,
    EtfGridLedgerService,
    EtfGridSignalService,
    EtfGridValuationService,
)
from tests.support import add_test_identity

pytestmark = pytest.mark.unit

_VALID_TRADE: dict[str, Any] = {"symbol": "513330.XSHG", "trade_date": "2026-09-09", "side": "buy", "price": "0.3590", "quantity": 100, "commission_rate": "0.001"}


def _router(**overrides: Any) -> APIRouter:
    """Build a router with explicit service doubles for adapter-only tests."""
    kwargs: dict[str, Any] = {
        "config": EtfGridConfig(),  # type: ignore[call-arg]  # required fields come from .env.test
        "ledger_service": MagicMock(spec=EtfGridLedgerService),
        "candle_service": MagicMock(spec=EtfGridCandleService),
        "valuation_service": MagicMock(spec=EtfGridValuationService),
        "signal_service": MagicMock(spec=EtfGridSignalService),
    }
    kwargs.update(overrides)
    return create_router(**kwargs)


def _client(**overrides: Any) -> TestClient:
    """Build a test client with injected identity and service doubles."""
    app = FastAPI()
    add_test_identity(app)
    app.include_router(_router(**overrides))
    return TestClient(app)


@pytest.mark.parametrize(
    "override",
    [
        {"price": "0"},
        {"price": "-1"},
        {"quantity": 0},
        {"quantity": 1.5},
        {"commission_rate": "-0.001"},
        {"commission": "-1"},
        {"net_amount": "0"},
        {"side": "hold"},
    ],
)
def test_trade_create_rejects_invalid_values(override: dict[str, Any]) -> None:
    """Out-of-range numbers and unknown sides fail request-model validation."""
    with pytest.raises(ValidationError):
        TradeCreate.model_validate(_VALID_TRADE | override)


def test_trade_create_accepts_valid_body() -> None:
    """A well-formed body parses with typed fields and optional defaults."""
    body = TradeCreate.model_validate(_VALID_TRADE)
    assert body.price == Decimal("0.3590")
    assert body.note is None
    assert body.commission is None


def test_trade_create_accepts_zero_commission() -> None:
    """Zero commission and commission rate are valid boundaries."""
    body = TradeCreate.model_validate(_VALID_TRADE | {"commission_rate": "0", "commission": "0"})
    assert body.commission == Decimal(0)
    assert body.note is None


def test_post_trades_body_validation_does_not_reach_service() -> None:
    """Pydantic rejections use the canonical detail list and never call the ledger."""
    ledger = MagicMock(spec=EtfGridLedgerService)
    response = _client(ledger_service=ledger).post("/api/v1/extensions/etf-grid/trades", json=_VALID_TRADE | {"price": "-1"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert all({"loc", "msg", "type"} <= set(item) for item in detail)
    ledger.record_trade.assert_not_called()


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"limit": 201}, {"offset": -1}])
def test_get_trades_rejects_invalid_pagination(params: dict[str, int]) -> None:
    """Out-of-range limit/offset values are 422 with the canonical detail list."""
    response = _client().get("/api/v1/extensions/etf-grid/trades", params=params)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert all({"loc", "msg", "type"} <= set(item) for item in detail)


@pytest.mark.parametrize(("method", "path"), [("get", "/status"), ("get", "/trades"), ("post", "/trades"), ("post", "/signals/compute"), ("post", "/sync")])
def test_routes_require_identity(method: str, path: str) -> None:
    """Every route rejects a request without an authenticated user."""
    response = _client().request(method, f"/api/v1/extensions/etf-grid{path}", headers={"x-test-user": ""}, json=_VALID_TRADE if method == "post" else None)
    assert response.status_code == 403


def test_post_sync_allows_users_and_reports_provider_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /sync allows ordinary and internal callers and reports per-source errors in the body."""
    monkeypatch.setattr(
        "spectres.extensions.etf_grid.api.sync_market_data",
        lambda **kwargs: {"candles": None, "valuation": None, "errors": {"candles": "boom", "valuation": "boom"}},
    )
    client = _client()
    response = client.post("/api/v1/extensions/etf-grid/sync")
    assert response.status_code == 200
    assert response.json()["errors"] == {"candles": "boom", "valuation": "boom"}
    assert client.post("/api/v1/extensions/etf-grid/sync", headers={"x-test-internal": "true"}).status_code == 200


def test_get_trades_delegates_sql_filters_pagination_and_count() -> None:
    """The endpoint returns the service page directly instead of slicing a full result set."""
    ledger = MagicMock()
    ledger.list_trades.return_value = [
        {
            "id": 2,
            "user_id": "alice",
            "trade_date": date(2026, 9, 9),
            "symbol": "513330.XSHG",
            "side": "buy",
            "price": "0.3590",
            "quantity": 100,
            "gross_amount": "35.90",
            "commission_rate": "0.001",
            "commission": "0.04",
            "net_amount": "35.94",
            "source": "manual",
            "note": None,
            "created_at": "2026-09-09T10:00:00+00:00",
        }
    ]
    ledger.count_trades.return_value = 7
    client = _client(ledger_service=ledger)

    response = client.get(
        "/api/v1/extensions/etf-grid/trades",
        params={"symbol": "513330.XSHG", "start": "2026-09-01", "end": "2026-09-30", "limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == 2
    assert body["items"][0]["trade_date"] == "2026-09-09"
    assert body["items"][0]["net_amount"] == "35.94"
    assert body["total"] == 7
    assert body["limit"] == 1
    assert body["offset"] == 1
    ledger.list_trades.assert_called_once()
    args, kwargs = ledger.list_trades.call_args
    assert args == ("513330.XSHG",)
    assert kwargs["user_id"] == "alice"
    assert kwargs["start"] == date(2026, 9, 1)
    assert kwargs["end"] == date(2026, 9, 30)
    assert kwargs["limit"] == 1
    assert kwargs["offset"] == 1
    assert len(kwargs["order_by"]) == 1
    assert kwargs["order_by"][0].field.value == "trade_date"
    assert kwargs["order_by"][0].direction.value == "desc"
    ledger.count_trades.assert_called_once_with("513330.XSHG", user_id="alice", start=date(2026, 9, 1), end=date(2026, 9, 30))


def test_surviving_operations_declare_response_schemas() -> None:
    """OpenAPI contains five typed operations and no composite refresh path."""
    app = FastAPI()
    app.include_router(_router())
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/extensions/etf-grid/status": ("get", "200"),
        "/api/v1/extensions/etf-grid/signals/compute": ("post", "200"),
        "/api/v1/extensions/etf-grid/sync": ("post", "200"),
        "/api/v1/extensions/etf-grid/trades": ("get", "200"),
    }

    assert set(paths) == set(expected)
    assert "/api/v1/extensions/etf-grid/refresh" not in paths
    for path, (method, status_code) in expected.items():
        response = paths[path][method]["responses"][status_code]
        assert "schema" in response["content"]["application/json"]
    create_response = paths["/api/v1/extensions/etf-grid/trades"]["post"]["responses"]["201"]
    assert "schema" in create_response["content"]["application/json"]
