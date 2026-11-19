"""Integration tests for Agno-native schedule writes and Workflow targets."""

from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support import ADMIN_SCOPES, auth_headers

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

pytestmark = [pytest.mark.integration, pytest.mark.db]


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


def test_native_write_routes_and_extension_workflows_are_exposed(jwt_client: TestClient) -> None:
    """AgentOS supplies native schedule read/write routes and both extension Workflow definitions."""
    paths = jwt_client.get("/openapi.json").json()["paths"]
    assert {"get", "post"} <= set(paths["/schedules"])
    assert {"get", "patch", "delete"} <= set(paths["/schedules/{schedule_id}"])
    assert "get" in paths["/schedules/{schedule_id}/runs"]
    assert "get" in paths["/schedules/{schedule_id}/runs/{run_id}"]
    for operation in ("enable", "disable", "trigger"):
        assert "post" in paths[f"/schedules/{{schedule_id}}/{operation}"]
    assert "/api/v1/workflow-targets" not in paths

    response = jwt_client.get("/workflows", headers=auth_headers(ALICE, USER_SCOPES))
    assert response.status_code == 200
    assert {"etf_grid_data_sync", "etf_grid_recompute"} <= {row["id"] for row in response.json()}


def test_personal_schedule_crud_state_trigger_and_history(jwt_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A user manages only their own schedule through the complete native lifecycle."""
    name = f"alice-recompute-{uuid4().hex}"
    created = jwt_client.post("/schedules", headers=auth_headers(ALICE, USER_SCOPES), json=_schedule_payload(name) | {"user_id": BOB})
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    assert created.json()["user_id"] == ALICE
    assert created.json()["endpoint"] == RECOMPUTE_ENDPOINT
    assert created.json()["enabled"] is True

    assert jwt_client.get(f"/schedules/{schedule_id}", headers=auth_headers(BOB, USER_SCOPES)).status_code == 404
    assert jwt_client.patch(f"/schedules/{schedule_id}", headers=auth_headers(BOB, USER_SCOPES), json={"name": "stolen"}).status_code == 404
    assert schedule_id not in {row["id"] for row in jwt_client.get("/schedules", headers=auth_headers(BOB, USER_SCOPES)).json()["data"]}

    updated = jwt_client.patch(
        f"/schedules/{schedule_id}",
        headers=auth_headers(ALICE, USER_SCOPES),
        json={"name": f"{name}-updated", "cron_expr": "30 11 * * 1-5", "timezone": "UTC", "max_retries": 2},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == f"{name}-updated"
    assert updated.json()["cron_expr"] == "30 11 * * 1-5"
    assert updated.json()["timezone"] == "UTC"
    assert updated.json()["max_retries"] == 2

    disabled = jwt_client.post(f"/schedules/{schedule_id}/disable", headers=auth_headers(ALICE, USER_SCOPES))
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert jwt_client.post(f"/schedules/{schedule_id}/trigger", headers=auth_headers(ALICE, USER_SCOPES)).status_code == 409

    enabled = jwt_client.post(f"/schedules/{schedule_id}/enable", headers=auth_headers(ALICE, USER_SCOPES))
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["next_run_at"] is not None

    executor = cast(FastAPI, jwt_client.app).state.scheduler_executor
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
    triggered = jwt_client.post(f"/schedules/{schedule_id}/trigger", headers=auth_headers(ALICE, USER_SCOPES))
    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["status"] == "success"
    assert triggered.json()["user_id"] == ALICE
    assert triggered.json()["run_id"] is not None
    call_endpoint.assert_awaited_once()

    history = jwt_client.get(f"/schedules/{schedule_id}/runs", headers=auth_headers(ALICE, USER_SCOPES))
    assert history.status_code == 200
    assert triggered.json()["id"] in {row["id"] for row in history.json()["data"]}
    assert jwt_client.get(f"/schedules/{schedule_id}/runs", headers=auth_headers(BOB, USER_SCOPES)).status_code == 404

    admin_read = jwt_client.get(f"/schedules/{schedule_id}", headers=auth_headers(ADMIN, ADMIN_SCOPES))
    assert admin_read.status_code == 200
    assert admin_read.json()["user_id"] == ALICE
    assert jwt_client.delete(f"/schedules/{schedule_id}", headers=auth_headers(BOB, USER_SCOPES)).status_code == 404
    assert jwt_client.delete(f"/schedules/{schedule_id}", headers=auth_headers(ALICE, USER_SCOPES)).status_code == 204


def test_user_can_schedule_system_sync_but_not_arbitrary_http(jwt_client: TestClient) -> None:
    """Global Workflow run permission allows system targets but not arbitrary HTTP endpoints."""
    system_sync = jwt_client.post(
        "/schedules",
        headers=auth_headers(ALICE, USER_SCOPES),
        json=_schedule_payload(f"user-sync-{uuid4().hex}", SYNC_ENDPOINT),
    )
    assert system_sync.status_code == 201, system_sync.text
    assert system_sync.json()["user_id"] == ALICE

    arbitrary_http = jwt_client.post(
        "/schedules",
        headers=auth_headers(ALICE, USER_SCOPES),
        json=_schedule_payload(f"forbidden-http-{uuid4().hex}", "/api/v1/extensions/etf-grid/signals/compute"),
    )
    assert arbitrary_http.status_code == 403


def test_schedule_write_requires_schedule_and_workflow_permissions(jwt_client: TestClient) -> None:
    """Schedule write scope alone cannot escalate into a Workflow execution grant."""
    without_write = jwt_client.post(
        "/schedules",
        headers=auth_headers(ALICE, ["schedules:read", "workflows:run"]),
        json=_schedule_payload(f"missing-write-{uuid4().hex}"),
    )
    assert without_write.status_code == 403

    without_run = jwt_client.post(
        "/schedules",
        headers=auth_headers(ALICE, ["schedules:read", "schedules:write"]),
        json=_schedule_payload(f"missing-run-{uuid4().hex}"),
    )
    assert without_run.status_code == 403


def test_admin_can_create_and_delete_system_workflow_target(jwt_client: TestClient) -> None:
    """Admin break-glass can manage a system Workflow target."""
    created = jwt_client.post(
        "/schedules",
        headers=auth_headers(ADMIN, ADMIN_SCOPES),
        json=_schedule_payload(f"admin-sync-{uuid4().hex}", SYNC_ENDPOINT),
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    assert created.json()["user_id"] == ADMIN
    assert jwt_client.delete(f"/schedules/{schedule_id}", headers=auth_headers(ADMIN, ADMIN_SCOPES)).status_code == 204


def test_recompute_workflow_executes_for_authenticated_owner(jwt_client: TestClient) -> None:
    """The real Workflow route executes deterministically under the JWT owner."""
    response = jwt_client.post(
        RECOMPUTE_ENDPOINT,
        headers=auth_headers(ALICE, USER_SCOPES),
        data={"message": "Recompute my signals", "user_id": BOB, "stream": "false", "background": "false"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == ALICE
    assert body["status"] == "COMPLETED"


def test_disabled_extension_schedule_skips_without_retry_or_reconfiguration(
    jwt_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled result is successful, non-retryable, and non-destructive."""
    name = f"disabled-extension-{uuid4().hex}"
    disabled = jwt_client.patch(
        "/api/v1/extensions/etf_grid",
        headers=auth_headers(ADMIN, ADMIN_SCOPES),
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    created = jwt_client.post(
        "/schedules",
        headers=auth_headers(ALICE, USER_SCOPES),
        json=_schedule_payload(name) | {"max_retries": 3},
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    executor = cast(FastAPI, jwt_client.app).state.scheduler_executor
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

    triggered = jwt_client.post(f"/schedules/{schedule_id}/trigger", headers=auth_headers(ALICE, USER_SCOPES))

    assert triggered.status_code == 200, triggered.text
    assert triggered.json()["status"] == "success"
    assert triggered.json()["output"]["content"] == {"status": "disabled", "extension": "etf_grid"}
    history = jwt_client.get(f"/schedules/{schedule_id}/runs", headers=auth_headers(ALICE, USER_SCOPES))
    assert len(history.json()["data"]) == 1
    stored = jwt_client.get(f"/schedules/{schedule_id}", headers=auth_headers(ALICE, USER_SCOPES)).json()
    assert stored["enabled"] is True
    assert stored["max_retries"] == 3
    assert stored["user_id"] == ALICE
    assert stored["endpoint"] == RECOMPUTE_ENDPOINT
