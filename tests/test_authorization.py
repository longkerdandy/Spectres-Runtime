"""Integration tests for Logto-style JWT scope authorization."""

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import ADMIN_SCOPES, auth_headers
from tests.support import FULL_USER_SCOPES as USER_SCOPES

pytestmark = [pytest.mark.integration, pytest.mark.db]


def test_token_without_required_scope_is_forbidden(jwt_client: TestClient) -> None:
    """A valid identity without the route's scope is not enough."""
    response = jwt_client.get("/agents", headers=auth_headers("alice", []))
    assert response.status_code == 403


def test_user_scopes_preserve_daily_routes(jwt_client: TestClient) -> None:
    """The ordinary role can read config/registry and run the agent family."""
    assert jwt_client.get("/config", headers=auth_headers("alice", USER_SCOPES)).status_code == 200
    assert jwt_client.get("/registry", headers=auth_headers("alice", USER_SCOPES)).status_code == 200
    assert jwt_client.get("/agents", headers=auth_headers("alice", USER_SCOPES)).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/users"),
        ("GET", "/components"),
        ("GET", "/service-accounts"),
        ("POST", "/databases/all/migrate"),
        ("POST", "/metrics/refresh"),
    ],
)
def test_admin_only_routes_reject_user(jwt_client: TestClient, method: str, path: str) -> None:
    """Administrative configuration and governance are denied to user."""
    response = jwt_client.request(method, path, headers=auth_headers("alice", USER_SCOPES))
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/users", "/components", "/service-accounts"])
def test_admin_scope_allows_management_routes(jwt_client: TestClient, path: str) -> None:
    """Agno's admin super-scope opens framework management surfaces."""
    response = jwt_client.get(path, headers=auth_headers("operator", ADMIN_SCOPES))
    assert response.status_code == 200


def test_admin_can_disable_and_restore_directory_user(jwt_client: TestClient) -> None:
    """The /users API administers the immediate disabled-user kill-switch."""
    subject = f"disposable-{uuid4().hex}"
    user_headers = auth_headers(subject, USER_SCOPES)
    admin_headers = auth_headers("operator", ADMIN_SCOPES)
    assert jwt_client.get("/agents", headers=user_headers).status_code == 200

    disabled = jwt_client.patch(f"/users/{subject}", headers=admin_headers, json={"disabled": True})
    assert disabled.status_code == 200
    assert jwt_client.get("/agents", headers=user_headers).status_code in (401, 403)

    restored = jwt_client.patch(f"/users/{subject}", headers=admin_headers, json={"disabled": False})
    assert restored.status_code == 200
    assert jwt_client.get("/agents", headers=user_headers).status_code == 200


def test_user_cannot_manage_directory_users(jwt_client: TestClient) -> None:
    """A non-admin cannot change another user's disabled state."""
    store = cast(FastAPI, jwt_client.app).state.user_store
    store.provision_from_claims("victim", {"email": "victim@example.com"})
    response = jwt_client.patch("/users/victim", headers=auth_headers("mallory", USER_SCOPES), json={"disabled": True})
    assert response.status_code == 403
    assert store.get("victim")["disabled"] is False


def test_extension_scopes_portfolios_independently_between_roles(jwt_client: TestClient) -> None:
    """Normal portfolio routes self-scope both user and admin identities."""
    path = "/api/v1/extensions/etf-grid/status"
    user_headers = auth_headers("alice", USER_SCOPES)
    admin_headers = auth_headers("operator", ADMIN_SCOPES)
    payload = {
        "symbol": "513330.XSHG",
        "trade_date": "2026-09-09",
        "side": "buy",
        "price": "0.3590",
        "quantity": 100,
        "commission_rate": "0.001",
    }
    assert jwt_client.post("/api/v1/extensions/etf-grid/trades", headers=user_headers, json=payload).status_code == 201

    user_response = jwt_client.get(path, headers=user_headers)
    admin_response = jwt_client.get(path, headers=admin_headers)
    assert user_response.status_code == 200
    assert admin_response.status_code == 200
    user_row = next(row for row in user_response.json() if row["symbol"] == "513330.XSHG")
    admin_row = next(row for row in admin_response.json() if row["symbol"] == "513330.XSHG")
    assert user_row["shares"] == 100
    assert admin_row["shares"] == 0
