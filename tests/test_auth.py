"""Tests for JWT authentication wiring on the full application.

The committed test env (.env.test) carries no JWT settings, so the module-level
app runs open. These tests use the ``jwt_client`` fixture, which builds a second
application instance with a dev verification key, to exercise the authenticated
plane end to end.
"""

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import ADMIN_SCOPES, auth_headers, dev_token

TEST_ROUTE = "/api/v1/extensions/etf-grid/status"
USER_SCOPES = ["agents:read", "agents:*:run"]

pytestmark = [pytest.mark.integration, pytest.mark.db]


class TestAuthMatrix:
    """The 401/200 matrix across route families under JWT mode."""

    def test_health_stays_open(self, jwt_client: TestClient) -> None:
        """The health endpoint is excluded from authentication."""
        assert jwt_client.get("/health").status_code == 200

    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param({}, id="missing"),
            pytest.param({"Authorization": "Bearer not-a-token"}, id="garbage"),
            pytest.param({"Authorization": "alice"}, id="not-bearer"),
            pytest.param({"Authorization": f"Bearer {dev_token('mallory', USER_SCOPES, secret='a-different-key-0123456789abcdef0123456789')}"}, id="wrong-key"),
            pytest.param({"Authorization": f"Bearer {dev_token('alice', USER_SCOPES, audience='https://other.example/api')}"}, id="wrong-audience"),
        ],
    )
    def test_invalid_credentials_rejected(self, jwt_client: TestClient, headers: dict[str, str]) -> None:
        """Missing, malformed, foreign-key, and foreign-audience tokens are all rejected."""
        assert jwt_client.get("/agents", headers=headers).status_code == 401

    def test_valid_token_accepted(self, jwt_client: TestClient) -> None:
        """A correctly signed token with the right audience passes."""
        assert jwt_client.get("/agents", headers=auth_headers("alice", USER_SCOPES)).status_code == 200

    @pytest.mark.parametrize(("method", "path"), [("GET", TEST_ROUTE), ("POST", "/agui")])
    def test_non_agentos_routes_require_token(self, jwt_client: TestClient, method: str, path: str) -> None:
        """Extension routers and the AG-UI endpoint sit behind the same auth middleware."""
        assert jwt_client.request(method, path, json={}).status_code == 401
        assert jwt_client.request(method, path, json={}, headers=auth_headers("alice", USER_SCOPES)).status_code != 401


class TestUserDirectory:
    """JIT provisioning of the user directory from JWT claims."""

    def test_first_request_provisions_user(self, jwt_client: TestClient) -> None:
        """A new subject is JIT-provisioned with claims mapped."""
        store = cast(FastAPI, jwt_client.app).state.user_store
        assert store.get("alice") is None
        assert jwt_client.get("/agents", headers=auth_headers("alice", USER_SCOPES)).status_code == 200
        user = store.get("alice")
        assert user is not None
        assert user["email"] == "alice@example.com"
        assert user["name"] == "Alice"

    def test_existing_user_name_is_refreshed_in_admin_api(self, jwt_client: TestClient) -> None:
        """A later JWT updates an existing directory name returned by /users."""
        store = cast(FastAPI, jwt_client.app).state.user_store
        store.upsert("profile-user", name="Old Name")
        assert jwt_client.get("/agents", headers=auth_headers("profile-user", USER_SCOPES, name="Old Name")).status_code == 200
        assert jwt_client.get("/agents", headers=auth_headers("profile-user", USER_SCOPES, name="New Name")).status_code == 200

        response = jwt_client.get("/users?search=profile-user", headers=auth_headers("operator", ADMIN_SCOPES))
        assert response.status_code == 200
        user = next(row for row in response.json()["data"] if row["id"] == "profile-user")
        assert user["name"] == "New Name"

    def test_missing_name_claim_keeps_existing_name(self, jwt_client: TestClient) -> None:
        """A JWT without a usable name claim never blanks the stored directory name."""
        store = cast(FastAPI, jwt_client.app).state.user_store
        store.upsert("profile-user", name="Kept Name")
        assert jwt_client.get("/agents", headers=auth_headers("profile-user", USER_SCOPES, name="")).status_code == 200
        assert store.get("profile-user")["name"] == "Kept Name"


class TestInternalServiceToken:
    """The scheduler executor's internal token still authenticates under JWT mode."""

    def test_internal_token_reads_schedules(self, jwt_client: TestClient) -> None:
        """The scheduler's internal service token keeps schedule read access."""
        internal_token = cast(FastAPI, jwt_client.app).state.internal_service_token
        assert internal_token
        response = jwt_client.get("/schedules", headers={"Authorization": f"Bearer {internal_token}"})
        assert response.status_code == 200
        names = [row.get("name") for row in response.json().get("data", [])]
        assert "ETF Grid Daily Sync" in names
