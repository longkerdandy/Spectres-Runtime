"""Integration tests for Agno-native schedule writes and Workflow targets."""

from collections.abc import Iterator
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"
ALICE = "schedule-write-alice"
BOB = "schedule-write-bob"
ADMIN = "schedule-write-operator"
RECOMPUTE_ENDPOINT = "/workflows/etf_grid_recompute/runs"
SYNC_ENDPOINT = "/workflows/etf_grid_data_sync/runs"
USER_SCOPES = [
    "schedules:read",
    "schedules:write",
    "schedules:delete",
    "workflows:read",
    "workflows:run",
]
ADMIN_SCOPES = ["agent_os:admin"]

pytestmark = pytest.mark.db


def _headers(sub: str, scopes: list[str] | None = None) -> dict[str, str]:
    from agno.os.auth import create_dev_token

    token = create_dev_token(sub, secret=DEV_KEY, audience=DEV_AUDIENCE, scopes=USER_SCOPES if scopes is None else scopes)
    return {"Authorization": f"Bearer {token}"}


def _schedule_payload(name: str, endpoint: str = RECOMPUTE_ENDPOINT) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Personal ETF Grid recompute",
        "cron_expr": "0 10 * * 1-5",
        "endpoint": endpoint,
        "method": "POST",
        "payload": {"message": "Run scheduled ETF Grid recompute"},
        "timezone": "Asia/Shanghai",
        "timeout_seconds": 3600,
        "max_retries": 1,
        "retry_delay_seconds": 60,
    }


@pytest.fixture
def schedule_write_client() -> Iterator[TestClient]:
    """Build the full application with JWT scopes and user isolation enabled."""
    from spectres import main as main_module
    from spectres.config import settings

    old_key, old_audience, old_algorithm = settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm
    settings.jwt_verification_key = DEV_KEY
    settings.jwt_audience = DEV_AUDIENCE
    settings.jwt_algorithm = "HS256"
    try:
        agent_os, contributions, extension_state = main_module.create_agent_os()
        app = agent_os.get_app()
        main_module.mount_extension_routers(app, contributions, extension_state)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        settings.jwt_verification_key, settings.jwt_audience, settings.jwt_algorithm = old_key, old_audience, old_algorithm


def test_native_write_routes_and_extension_workflows_are_exposed(schedule_write_client: TestClient) -> None:
    """AgentOS supplies schedule writes and both extension Workflow definitions."""
    paths = schedule_write_client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/schedules"]
    assert {"get", "patch", "delete"} <= set(paths["/schedules/{schedule_id}"])
    for operation in ("enable", "disable", "trigger"):
        assert "post" in paths[f"/schedules/{{schedule_id}}/{operation}"]
    assert "/api/v1/workflow-targets" not in paths

    response = schedule_write_client.get("/workflows", headers=_headers(ALICE))
    assert response.status_code == 200
    assert {"etf_grid_data_sync", "etf_grid_recompute"} <= {row["id"] for row in response.json()}


def test_personal_schedule_crud_state_trigger_and_history(schedule_write_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A user manages only their own schedule through the complete native lifecycle."""
    name = f"alice-recompute-{uuid4().hex}"
    schedule_id: str | None = None
    try:
        created = schedule_write_client.post("/schedules", headers=_headers(ALICE), json=_schedule_payload(name) | {"user_id": BOB})
        assert created.status_code == 201, created.text
        schedule_id = created.json()["id"]
        assert created.json()["user_id"] == ALICE
        assert created.json()["endpoint"] == RECOMPUTE_ENDPOINT
        assert created.json()["enabled"] is True

        assert schedule_write_client.get(f"/schedules/{schedule_id}", headers=_headers(BOB)).status_code == 404
        assert schedule_write_client.patch(f"/schedules/{schedule_id}", headers=_headers(BOB), json={"name": "stolen"}).status_code == 404
        assert schedule_id not in {row["id"] for row in schedule_write_client.get("/schedules", headers=_headers(BOB)).json()["data"]}

        updated = schedule_write_client.patch(
            f"/schedules/{schedule_id}",
            headers=_headers(ALICE),
            json={"name": f"{name}-updated", "cron_expr": "30 11 * * 1-5", "timezone": "UTC", "max_retries": 2},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == f"{name}-updated"
        assert updated.json()["cron_expr"] == "30 11 * * 1-5"
        assert updated.json()["timezone"] == "UTC"
        assert updated.json()["max_retries"] == 2

        disabled = schedule_write_client.post(f"/schedules/{schedule_id}/disable", headers=_headers(ALICE))
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False
        assert schedule_write_client.post(f"/schedules/{schedule_id}/trigger", headers=_headers(ALICE)).status_code == 409

        enabled = schedule_write_client.post(f"/schedules/{schedule_id}/enable", headers=_headers(ALICE))
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True
        assert enabled.json()["next_run_at"] is not None

        executor = cast(FastAPI, schedule_write_client.app).state.scheduler_executor
        call_endpoint = AsyncMock(
            return_value={
                "status": "success",
                "status_code": 200,
                "run_id": f"workflow-run-{uuid4().hex}",
                "session_id": f"workflow-session-{uuid4().hex}",
                "output": {"content": {"signals": {}, "skipped": {}}},
            }
        )
        monkeypatch.setattr(executor, "_call_endpoint", call_endpoint)
        triggered = schedule_write_client.post(f"/schedules/{schedule_id}/trigger", headers=_headers(ALICE))
        assert triggered.status_code == 200, triggered.text
        assert triggered.json()["status"] == "success"
        assert triggered.json()["user_id"] == ALICE
        assert triggered.json()["run_id"] is not None
        call_endpoint.assert_awaited_once()

        history = schedule_write_client.get(f"/schedules/{schedule_id}/runs", headers=_headers(ALICE))
        assert history.status_code == 200
        assert triggered.json()["id"] in {row["id"] for row in history.json()["data"]}
        assert schedule_write_client.get(f"/schedules/{schedule_id}/runs", headers=_headers(BOB)).status_code == 404

        admin_read = schedule_write_client.get(f"/schedules/{schedule_id}", headers=_headers(ADMIN, ADMIN_SCOPES))
        assert admin_read.status_code == 200
        assert admin_read.json()["user_id"] == ALICE
        assert schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(BOB)).status_code == 404
        assert schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(ALICE)).status_code == 204
        schedule_id = None
    finally:
        if schedule_id is not None:
            schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(ADMIN, ADMIN_SCOPES))


def test_user_can_schedule_system_sync_but_not_arbitrary_http(schedule_write_client: TestClient) -> None:
    """Global Workflow run permission allows system targets but not arbitrary HTTP endpoints."""
    schedule_id: str | None = None
    try:
        system_sync = schedule_write_client.post(
            "/schedules",
            headers=_headers(ALICE),
            json=_schedule_payload(f"user-sync-{uuid4().hex}", SYNC_ENDPOINT),
        )
        assert system_sync.status_code == 201, system_sync.text
        schedule_id = system_sync.json()["id"]
        assert system_sync.json()["user_id"] == ALICE

        arbitrary_http = schedule_write_client.post(
            "/schedules",
            headers=_headers(ALICE),
            json=_schedule_payload(f"forbidden-http-{uuid4().hex}", "/api/v1/extensions/etf-grid/signals/compute"),
        )
        assert arbitrary_http.status_code == 403
    finally:
        if schedule_id is not None:
            schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(ALICE))


def test_schedule_write_requires_schedule_and_workflow_permissions(schedule_write_client: TestClient) -> None:
    """Schedule write scope alone cannot escalate into a Workflow execution grant."""
    without_write = schedule_write_client.post(
        "/schedules",
        headers=_headers(ALICE, ["schedules:read", "workflows:run"]),
        json=_schedule_payload(f"missing-write-{uuid4().hex}"),
    )
    assert without_write.status_code == 403

    without_run = schedule_write_client.post(
        "/schedules",
        headers=_headers(ALICE, ["schedules:read", "schedules:write"]),
        json=_schedule_payload(f"missing-run-{uuid4().hex}"),
    )
    assert without_run.status_code == 403


def test_admin_can_create_and_delete_system_workflow_target(schedule_write_client: TestClient) -> None:
    """Admin break-glass can manage a system Workflow target."""
    schedule_id: str | None = None
    try:
        created = schedule_write_client.post(
            "/schedules",
            headers=_headers(ADMIN, ADMIN_SCOPES),
            json=_schedule_payload(f"admin-sync-{uuid4().hex}", SYNC_ENDPOINT),
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["id"]
        assert created.json()["user_id"] == ADMIN
        assert schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(ADMIN, ADMIN_SCOPES)).status_code == 204
        schedule_id = None
    finally:
        if schedule_id is not None:
            schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(ADMIN, ADMIN_SCOPES))


def test_recompute_workflow_executes_for_authenticated_owner(schedule_write_client: TestClient) -> None:
    """The real Workflow route executes deterministically under the JWT owner."""
    response = schedule_write_client.post(
        RECOMPUTE_ENDPOINT,
        headers=_headers(ALICE),
        data={"message": "Recompute my signals", "user_id": BOB, "stream": "false", "background": "false"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == ALICE
    assert body["status"] == "COMPLETED"


def test_disabled_extension_schedule_skips_without_retry_or_reconfiguration(
    schedule_write_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled result is successful, non-retryable, and non-destructive."""
    name = f"disabled-extension-{uuid4().hex}"
    schedule_id: str | None = None
    try:
        disabled = schedule_write_client.patch(
            "/api/v1/extensions/etf_grid",
            headers=_headers(ADMIN, ADMIN_SCOPES),
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        created = schedule_write_client.post(
            "/schedules",
            headers=_headers(ALICE),
            json=_schedule_payload(name) | {"max_retries": 3},
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["id"]
        executor = cast(FastAPI, schedule_write_client.app).state.scheduler_executor
        call_endpoint = AsyncMock(
            return_value={
                "status": "success",
                "status_code": 200,
                "run_id": f"workflow-run-{uuid4().hex}",
                "session_id": f"workflow-session-{uuid4().hex}",
                "output": {"content": {"status": "disabled", "extension": "etf_grid"}},
            }
        )
        monkeypatch.setattr(executor, "_call_endpoint", call_endpoint)

        triggered = schedule_write_client.post(f"/schedules/{schedule_id}/trigger", headers=_headers(ALICE))

        assert triggered.status_code == 200, triggered.text
        assert triggered.json()["status"] == "success"
        assert triggered.json()["output"]["content"] == {"status": "disabled", "extension": "etf_grid"}
        history = schedule_write_client.get(f"/schedules/{schedule_id}/runs", headers=_headers(ALICE))
        assert len(history.json()["data"]) == 1
        stored = schedule_write_client.get(f"/schedules/{schedule_id}", headers=_headers(ALICE)).json()
        assert stored["enabled"] is True
        assert stored["max_retries"] == 3
        assert stored["user_id"] == ALICE
        assert stored["endpoint"] == RECOMPUTE_ENDPOINT
    finally:
        if schedule_id is not None:
            schedule_write_client.delete(f"/schedules/{schedule_id}", headers=_headers(ALICE))
