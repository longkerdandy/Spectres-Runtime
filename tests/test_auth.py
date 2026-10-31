"""Tests for JWT authentication wiring (spectres/config.py + spectres/main.py).

The committed test env (.env.test) carries no JWT settings, so the module-level
app runs open. These tests build a second application instance with a dev
verification key to exercise the authenticated plane end to end.
"""

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from spectres.config import Settings

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"
TEST_ROUTE = "/api/v1/extensions/etf-grid/status"
USER_SCOPES = ["agents:read", "agents:*:run"]


def _dev_token(sub: str, scopes: list[str] | None = None) -> str:
    from agno.os.auth import create_dev_token

    return create_dev_token(
        sub,
        secret=DEV_KEY,
        audience=DEV_AUDIENCE,
        email=f"{sub}@example.com",
        name=sub.title(),
        scopes=USER_SCOPES if scopes is None else scopes,
    )


@pytest.mark.unit
class TestJwtSettings:
    """Settings-level validation for the JWT configuration."""

    def test_audience_without_verification_material_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An audience configured without key material fails validation."""
        monkeypatch.setenv("JWT_AUDIENCE", DEV_AUDIENCE)
        monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
        monkeypatch.delenv("JWT_JWKS_FILE", raising=False)
        with pytest.raises(ValidationError, match="JWT_AUDIENCE"):
            Settings()  # type: ignore[call-arg]

    def test_auth_enabled_only_with_verification_material(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """jwt_auth_enabled flips only when key material appears."""
        monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
        monkeypatch.delenv("JWT_JWKS_FILE", raising=False)
        assert Settings().jwt_auth_enabled is False  # type: ignore[call-arg]
        monkeypatch.setenv("JWT_VERIFICATION_KEY", DEV_KEY)
        assert Settings().jwt_auth_enabled is True  # type: ignore[call-arg]


@pytest.fixture(scope="module")
def authed_client() -> Iterator[TestClient]:
    """A full application instance with JWT authentication enabled.

    Module-scoped: the app is built once because schedule registration and
    table creation happen at build time. Marked tests use the ``db`` marker
    (not ``integration``) so the shared test database is not dropped between
    tests of this module.
    """
    from spectres import main as main_module
    from spectres.config import settings

    old_key, old_audience, old_algorithm = settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm
    settings.jwt_verification_key = DEV_KEY
    settings.jwt_audience = DEV_AUDIENCE
    settings.jwt_algorithm = "HS256"
    try:
        agent_os, contributions = main_module.create_agent_os()
        app = agent_os.get_app()
        for contribution in contributions:
            for router in contribution.routers:
                app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm = old_key, old_audience, old_algorithm


@pytest.mark.db
class TestAuthMatrix:
    """The 401/200 matrix across route families under JWT mode."""

    def test_health_stays_open(self, authed_client: TestClient) -> None:
        """The health endpoint is excluded from authentication."""
        assert authed_client.get("/health").status_code == 200

    def test_agentos_route_requires_token(self, authed_client: TestClient) -> None:
        """An AgentOS route rejects requests without a token."""
        assert authed_client.get("/agents").status_code == 401

    def test_garbage_token_rejected(self, authed_client: TestClient) -> None:
        """A malformed bearer token is rejected."""
        response = authed_client.get("/agents", headers={"Authorization": "Bearer not-a-token"})
        assert response.status_code == 401

    def test_wrong_key_token_rejected(self, authed_client: TestClient) -> None:
        """A token signed with a different key is rejected."""
        from agno.os.auth import create_dev_token

        token = create_dev_token("mallory", secret="a-different-key-0123456789abcdef0123456789", audience=DEV_AUDIENCE)
        response = authed_client.get("/agents", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_valid_token_accepted(self, authed_client: TestClient) -> None:
        """A correctly signed token with the right audience passes."""
        response = authed_client.get("/agents", headers={"Authorization": f"Bearer {_dev_token('alice')}"})
        assert response.status_code == 200

    def test_wrong_audience_rejected(self, authed_client: TestClient) -> None:
        """A token minted for another audience is rejected."""
        from agno.os.auth import create_dev_token

        token = create_dev_token("alice", secret=DEV_KEY, audience="https://other.example/api")
        response = authed_client.get("/agents", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_extension_route_requires_token(self, authed_client: TestClient) -> None:
        """Extension routers sit behind the same auth middleware."""
        assert authed_client.get(TEST_ROUTE).status_code == 401
        response = authed_client.get(TEST_ROUTE, headers={"Authorization": f"Bearer {_dev_token('alice')}"})
        assert response.status_code != 401

    def test_agui_route_requires_token(self, authed_client: TestClient) -> None:
        """The AG-UI endpoint requires a token."""
        assert authed_client.post("/agui", json={}).status_code == 401
        response = authed_client.post("/agui", json={}, headers={"Authorization": f"Bearer {_dev_token('alice')}"})
        assert response.status_code != 401


@pytest.mark.db
class TestUserDirectory:
    """JIT provisioning and the disabled kill-switch."""

    def test_first_request_provisions_user(self, authed_client: TestClient) -> None:
        """A new subject is JIT-provisioned with claims mapped."""
        store = cast(FastAPI, authed_client.app).state.user_store
        if store.get("alice") is not None:
            store.remove("alice")
        headers = {"Authorization": f"Bearer {_dev_token('alice')}"}
        assert authed_client.get("/agents", headers=headers).status_code == 200
        user = store.get("alice")
        assert user is not None
        assert user["email"] == "alice@example.com"

    def test_disabled_user_denied_with_valid_token(self, authed_client: TestClient) -> None:
        """Disabling a user denies their still-valid token."""
        store = cast(FastAPI, authed_client.app).state.user_store
        headers = {"Authorization": f"Bearer {_dev_token('bob')}"}
        assert authed_client.get("/agents", headers=headers).status_code == 200
        store.set_disabled("bob", True)
        try:
            assert authed_client.get("/agents", headers=headers).status_code in (401, 403)
        finally:
            store.set_disabled("bob", False)


@pytest.mark.db
class TestInternalServiceToken:
    """The scheduler executor's internal token still authenticates under JWT mode."""

    def test_internal_token_reads_schedules(self, authed_client: TestClient) -> None:
        """The scheduler's internal service token keeps schedule read access."""
        internal_token = cast(FastAPI, authed_client.app).state.internal_service_token
        assert internal_token
        response = authed_client.get("/schedules", headers={"Authorization": f"Bearer {internal_token}"})
        assert response.status_code == 200
        names = [row.get("name") for row in response.json().get("data", [])]
        assert "etf_grid_daily_sync" in names
