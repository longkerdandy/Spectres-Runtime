"""Unit tests for Mi Health typed REST contracts, identity, and activation."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectres.extensions.activation import include_extension_routers
from spectres.extensions.base import ExtensionContribution, LoadedExtension
from spectres.extensions.mi_health.api import create_router
from spectres.extensions.mi_health.credentials import CredentialProtectionError
from spectres.extensions.mi_health.service import (
    BindingExistsError,
    BindingStatus,
    ChallengeNotFoundError,
    MiHealthBindingService,
    MiHealthSessionService,
    MiHealthSyncService,
    NotBoundError,
    QrAttemptChallenge,
    SyncInProgressError,
    SyncRun,
    SyncRunStatus,
    SyncRunStream,
    SyncStatus,
    SyncStreamHealth,
)
from spectres.extensions.mi_health.xiaomi import AuthenticationRequiredError, ChallengeExpiredError, OwnerActionRequiredError, ProviderUnavailableError

pytestmark = pytest.mark.unit
_NOW = datetime(2026, 11, 10, tzinfo=UTC)


def _status(status: str = "authenticated") -> BindingStatus:
    return BindingStatus(status=status, region="cn", bound_at=_NOW if status != "unbound" else None, last_verified_at=None, last_renewed_at=None)


def _run(status: SyncRunStatus = "queued") -> SyncRun:
    return SyncRun(
        id="run-1",
        trigger_type="manual",
        status=status,
        streams=[SyncRunStream("profile", "pending", 0, None, None, None, None)],
        error_code=None,
        created_at=_NOW,
        started_at=None,
        finished_at=None,
    )


def _sync_status() -> SyncStatus:
    return SyncStatus(
        active_run=_run(),
        last_run=None,
        streams=[SyncStreamHealth("profile", "never_synced", None, None, None, None, False, None)],
    )


def _app(*, enabled: bool = True) -> tuple[TestClient, MagicMock, MagicMock, MagicMock]:
    bindings = MagicMock(spec=MiHealthBindingService)
    sessions = MagicMock(spec=MiHealthSessionService)
    sync = MagicMock(spec=MiHealthSyncService)
    sync.start = AsyncMock(return_value=_run())
    sync.execute = AsyncMock()
    sync.unbind = AsyncMock()
    sync.status.return_value = _sync_status()
    bindings.status.return_value = _status()
    bindings.create_qr_challenge = AsyncMock(return_value=QrAttemptChallenge("challenge", "https://account.xiaomi.com/qr", _NOW, 300))
    bindings.poll_qr_challenge = AsyncMock(return_value=_status())
    bindings.cancel_qr_challenge.return_value = None
    sessions.renew = AsyncMock(return_value=_status())
    sessions.verify = AsyncMock(return_value=_status())
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Any, call_next: Any) -> Any:
        request.state.user_id = request.headers.get("x-test-user", "alice")
        request.state.is_internal_service = request.headers.get("x-test-internal") == "true"
        return await call_next(request)

    router = create_router(bindings=bindings, sessions=sessions, sync=sync)
    extension = LoadedExtension(id="mi_health", name="Mi Health", description="Mi Health", contribution=ExtensionContribution(routers=[router]))
    state = MagicMock()
    state.is_enabled.return_value = enabled
    include_extension_routers(app, [extension], state)
    return TestClient(app), bindings, sessions, sync


def test_status_is_self_scoped() -> None:
    """Status uses verified middleware identity and returns no credentials."""
    client, bindings, _, _ = _app()
    response = client.get("/api/v1/extensions/mi-health/status", headers={"x-test-user": "bob"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "authenticated",
        "region": "cn",
        "bound_at": "2026-11-10T00:00:00Z",
        "last_verified_at": None,
        "last_renewed_at": None,
    }
    bindings.status.assert_called_once_with("bob")


def test_qr_and_session_routes() -> None:
    """All mutation routes call their corresponding service with the run owner."""
    client, bindings, sessions, sync = _app()
    base = "/api/v1/extensions/mi-health"
    challenge = client.post(f"{base}/auth/qr-challenges")
    assert challenge.status_code == 200
    assert challenge.json()["challenge_id"] == "challenge"
    assert "lp" not in challenge.json()
    poll = client.post(f"{base}/auth/qr-challenges/challenge/poll")
    assert poll.status_code == 200
    assert poll.json()["state"] == "authenticated"
    assert client.delete(f"{base}/auth/qr-challenges/challenge").status_code == 204
    assert client.delete(f"{base}/binding").status_code == 204
    assert client.post(f"{base}/session/renew").status_code == 200
    assert client.post(f"{base}/session/verify").status_code == 200
    bindings.create_qr_challenge.assert_awaited_once_with("alice")
    bindings.poll_qr_challenge.assert_awaited_once_with("alice", "challenge")
    bindings.cancel_qr_challenge.assert_called_once_with("alice", "challenge")
    sync.unbind.assert_awaited_once_with("alice")
    sessions.renew.assert_awaited_once_with("alice")
    sessions.verify.assert_awaited_once_with("alice")


def test_sync_start_returns_a_volatile_run_and_schedules_execution() -> None:
    """Manual start returns 202 and background-executes only the server-created run."""
    client, _, _, sync = _app()
    response = client.post("/api/v1/extensions/mi-health/sync", headers={"x-test-user": "bob"})
    assert response.status_code == 202
    assert response.json()["id"] == "run-1"
    assert response.json()["status"] == "queued"
    assert response.json()["streams"][0]["stream"] == "profile"
    assert "bob" not in response.text
    sync.start.assert_awaited_once_with("bob")
    sync.execute.assert_awaited_once_with("bob", "run-1")


def test_sync_status_is_self_scoped_and_contains_no_owner() -> None:
    """The local status response returns typed runs and stream health only."""
    client, _, _, sync = _app()
    response = client.get("/api/v1/extensions/mi-health/sync/status", headers={"x-test-user": "bob"})
    assert response.status_code == 200
    assert response.json()["active_run"]["id"] == "run-1"
    assert response.json()["last_run"] is None
    assert response.json()["streams"] == [
        {
            "stream": "profile",
            "status": "never_synced",
            "last_run_started_at": None,
            "last_succeeded_at": None,
            "last_failed_at": None,
            "last_successful_window_end": None,
            "backfill_completed": False,
            "last_error_code": None,
        }
    ]
    assert "bob" not in response.text
    sync.status.assert_called_once_with("bob")


@pytest.mark.parametrize(
    ("exception", "status_code", "code"),
    [
        (NotBoundError(), 404, "not_bound"),
        (AuthenticationRequiredError(), 409, "authentication_required"),
        (SyncInProgressError(), 409, "sync_in_progress"),
        (CredentialProtectionError(), 503, "credential_protection_unavailable"),
    ],
)
def test_sync_start_maps_safe_errors(exception: Exception, status_code: int, code: str) -> None:
    """A rejected start neither schedules execution nor exposes exception details."""
    client, _, _, sync = _app()
    sync.start.side_effect = exception
    response = client.post("/api/v1/extensions/mi-health/sync")
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    sync.execute.assert_not_awaited()


def test_active_sync_blocks_unbind() -> None:
    """The destructive operation returns the shared safe conflict response."""
    client, _, _, sync = _app()
    sync.unbind.side_effect = SyncInProgressError()
    response = client.delete("/api/v1/extensions/mi-health/binding")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sync_in_progress"


def test_internal_identity_is_rejected() -> None:
    """Internal scheduler identity cannot access private Mi Health routes."""
    client, bindings, _, _ = _app()
    response = client.get("/api/v1/extensions/mi-health/status", headers={"x-test-internal": "true"})
    assert response.status_code == 403
    bindings.status.assert_not_called()


@pytest.mark.parametrize(
    ("exception", "status_code", "code"),
    [
        (ChallengeNotFoundError(), 404, "challenge_not_found"),
        (ChallengeExpiredError(), 410, "challenge_expired"),
        (NotBoundError(), 404, "not_bound"),
        (BindingExistsError(), 409, "binding_exists"),
        (OwnerActionRequiredError(), 409, "owner_action_required"),
        (ProviderUnavailableError(), 502, "provider_unavailable"),
        (CredentialProtectionError(), 503, "credential_protection_unavailable"),
    ],
)
def test_safe_errors(exception: Exception, status_code: int, code: str) -> None:
    """Provider and state failures map to safe machine-readable errors."""
    client, bindings, _, _ = _app()
    bindings.create_qr_challenge = AsyncMock(side_effect=exception)
    response = client.post("/api/v1/extensions/mi-health/auth/qr-challenges")
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/status"),
        ("post", "/auth/qr-challenges"),
        ("post", "/auth/qr-challenges/challenge/poll"),
        ("delete", "/auth/qr-challenges/challenge"),
        ("delete", "/binding"),
        ("post", "/session/renew"),
        ("post", "/session/verify"),
        ("post", "/sync"),
        ("get", "/sync/status"),
    ],
)
def test_disabled_extension_stops_every_route(method: str, path: str) -> None:
    """The shared activation guard prevents all service work while disabled."""
    client, bindings, sessions, sync = _app(enabled=False)
    response = getattr(client, method)(f"/api/v1/extensions/mi-health{path}")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "extension_disabled"
    assert not bindings.mock_calls
    assert not sessions.mock_calls
    assert not sync.mock_calls


def test_openapi_declares_all_response_models() -> None:
    """Every route exposes its typed success schema through OpenAPI."""
    client, _, _, _ = _app()
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    base = "/api/v1/extensions/mi-health"
    assert set(paths) == {
        f"{base}/status",
        f"{base}/auth/qr-challenges",
        f"{base}/auth/qr-challenges/{{challenge_id}}/poll",
        f"{base}/auth/qr-challenges/{{challenge_id}}",
        f"{base}/binding",
        f"{base}/session/renew",
        f"{base}/session/verify",
        f"{base}/sync",
        f"{base}/sync/status",
    }
    assert paths[f"{base}/sync"]["post"]["responses"].keys() == {"202"}
    for name in (
        "BindingStatusResponse",
        "QRChallengeResponse",
        "QRChallengePollResponse",
        "SyncRunResponse",
        "SyncRunStreamResponse",
        "SyncStatusResponse",
        "SyncStreamHealthResponse",
    ):
        assert name in schema["components"]["schemas"]
