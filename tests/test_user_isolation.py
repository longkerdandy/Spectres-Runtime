"""Integration tests for per-user data isolation with real AgentOS routes."""

from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agno.db.schemas.scheduler import Schedule
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectres.db.postgres import get_postgres_db
from tests.support import FULL_USER_SCOPES as USER_SCOPES
from tests.support import auth_headers

pytestmark = [pytest.mark.integration, pytest.mark.db]


def _create_session(client: TestClient, owner: str, session_id: str) -> None:
    response = client.post(
        "/sessions?type=agent",
        headers=auth_headers(owner, USER_SCOPES),
        json={"session_id": session_id, "agent_id": "team-leader", "user_id": "spoofed-user"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == owner


def test_isolation_is_enabled(jwt_client: TestClient) -> None:
    """The assembled application exposes the effective isolation setting."""
    assert cast(FastAPI, jwt_client.app).state.user_isolation_enabled is True


def test_sessions_are_scoped_to_their_owner(jwt_client: TestClient) -> None:
    """Session list/get/create honor ownership and ignore spoofed user ids."""
    session_id = f"session-{uuid4().hex}"
    _create_session(jwt_client, "alice", session_id)

    alice_list = jwt_client.get("/sessions", headers=auth_headers("alice", USER_SCOPES))
    assert alice_list.status_code == 200
    assert session_id in {row["session_id"] for row in alice_list.json()["data"]}

    bob_list = jwt_client.get("/sessions?user_id=alice", headers=auth_headers("bob", USER_SCOPES))
    assert bob_list.status_code == 200
    assert session_id not in {row["session_id"] for row in bob_list.json()["data"]}
    assert jwt_client.get(f"/sessions/{session_id}", headers=auth_headers("bob", USER_SCOPES)).status_code == 404

    collision = jwt_client.post(
        "/sessions?type=agent",
        headers=auth_headers("bob", USER_SCOPES),
        json={"session_id": session_id, "agent_id": "team-leader"},
    )
    assert collision.status_code == 409

    assert jwt_client.get(f"/sessions/{session_id}", headers=auth_headers("alice", USER_SCOPES)).status_code == 200
    admin_response = jwt_client.get(f"/sessions/{session_id}", headers=auth_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert admin_response.json()["user_id"] == "alice"


def test_runs_are_scoped_to_their_owner(jwt_client: TestClient) -> None:
    """Run list/get endpoints cannot cross the parent session's owner."""
    session_id = f"session-{uuid4().hex}"
    run_id = f"run-{uuid4().hex}"
    _create_session(jwt_client, "alice", session_id)
    run = RunOutput(
        run_id=run_id,
        agent_id="team-leader",
        session_id=session_id,
        user_id="alice",
        content="Alice's private run",
        status=RunStatus.completed,
    )
    get_postgres_db().upsert_run(run, session_id=session_id, user_id="alice", run_index=0)

    alice_runs = jwt_client.get(f"/sessions/{session_id}/runs", headers=auth_headers("alice", USER_SCOPES))
    assert alice_runs.status_code == 200
    assert run_id in {row["run_id"] for row in alice_runs.json()}
    assert jwt_client.get(f"/sessions/{session_id}/runs/{run_id}", headers=auth_headers("alice", USER_SCOPES)).status_code == 200

    assert jwt_client.get(f"/sessions/{session_id}/runs", headers=auth_headers("bob", USER_SCOPES)).status_code == 404
    assert jwt_client.get(f"/sessions/{session_id}/runs/{run_id}", headers=auth_headers("bob", USER_SCOPES)).status_code == 404

    admin_response = jwt_client.get(f"/sessions/{session_id}/runs/{run_id}", headers=auth_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert admin_response.json()["run_id"] == run_id


def test_memories_are_scoped_to_their_owner(jwt_client: TestClient) -> None:
    """Memory list/get/update honor ownership and ignore spoofed user ids."""
    created = jwt_client.post(
        "/memories",
        headers=auth_headers("alice", USER_SCOPES),
        json={"memory": "Alice's private memory", "user_id": "bob", "topics": ["private"]},
    )
    assert created.status_code == 200, created.text
    memory_id = created.json()["memory_id"]
    assert created.json()["user_id"] == "alice"

    alice_list = jwt_client.get("/memories", headers=auth_headers("alice", USER_SCOPES))
    assert memory_id in {row["memory_id"] for row in alice_list.json()["data"]}
    bob_list = jwt_client.get("/memories?user_id=alice", headers=auth_headers("bob", USER_SCOPES))
    assert memory_id not in {row["memory_id"] for row in bob_list.json()["data"]}
    assert jwt_client.get(f"/memories/{memory_id}", headers=auth_headers("bob", USER_SCOPES)).status_code == 404

    forbidden_update = jwt_client.patch(f"/memories/{memory_id}", headers=auth_headers("bob", USER_SCOPES), json={"memory": "Overwritten", "user_id": "bob"})
    assert forbidden_update.status_code == 404
    assert jwt_client.get(f"/memories/{memory_id}", headers=auth_headers("alice", USER_SCOPES)).json()["memory"] == "Alice's private memory"

    admin_response = jwt_client.get(f"/memories/{memory_id}", headers=auth_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert admin_response.json()["user_id"] == "alice"


def test_agui_rejects_cross_user_thread_write(jwt_client: TestClient) -> None:
    """A user cannot append a run to another user's AG-UI thread."""
    session_id = f"thread-{uuid4().hex}"
    _create_session(jwt_client, "alice", session_id)
    payload = {
        "thread_id": session_id,
        "run_id": f"run-{uuid4().hex}",
        "state": {},
        "messages": [{"id": f"message-{uuid4().hex}", "role": "user", "content": "cross-user write"}],
        "tools": [],
        "context": [],
        "forwarded_props": {"user_id": "bob"},
    }

    response = jwt_client.post("/agui", headers=auth_headers("bob", USER_SCOPES), json=payload)

    assert response.status_code == 404
    stored = get_postgres_db().get_session(session_id=session_id, deserialize=False)
    assert isinstance(stored, dict)
    assert stored["user_id"] == "alice"


def test_unowned_schedule_is_hidden_from_users_but_visible_to_admin(jwt_client: TestClient) -> None:
    """The system ETF schedule remains unowned rather than becoming user-shared."""
    user_response = jwt_client.get("/schedules", headers=auth_headers("alice", USER_SCOPES))
    assert user_response.status_code == 200
    assert "ETF Grid Daily Sync" not in {row["name"] for row in user_response.json()["data"]}

    admin_response = jwt_client.get("/schedules", headers=auth_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert "ETF Grid Daily Sync" in {row["name"] for row in admin_response.json()["data"]}


def test_system_schedule_restart_preserves_stored_configuration(jwt_client: TestClient) -> None:
    """Startup registration does not overwrite administrator-managed schedule fields."""
    from spectres import main as main_module
    from spectres.scheduler import register_schedules

    db = get_postgres_db()
    row = db.get_schedule_by_name("ETF Grid Daily Sync", user_id=None)
    assert row is not None
    fields = (
        "cron_expr",
        "endpoint",
        "method",
        "payload",
        "timezone",
        "timeout_seconds",
        "max_retries",
        "retry_delay_seconds",
        "enabled",
        "next_run_at",
    )
    administrator_changes = {field: row[field] for field in fields} | {
        "cron_expr": "15 4 * * 3",
        "enabled": False,
        "next_run_at": 1760000001,
    }
    assert db.update_schedule(row["id"], **administrator_changes) is not None
    register_schedules([spec for extension in main_module.loaded_extensions for spec in extension.contribution.schedules], db)
    stored = db.get_schedule_by_name("ETF Grid Daily Sync", user_id=None)
    assert stored is not None
    assert {field: stored[field] for field in fields} == administrator_changes
    assert db.get_schedule_by_name("etf_grid_daily_sync", user_id=None) is None


async def test_unowned_schedule_still_executes(jwt_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The official Executor records a successful unowned run under isolation."""
    db = get_postgres_db()
    schedule_row = db.get_schedule_by_name("ETF Grid Daily Sync")
    assert schedule_row is not None
    schedule = Schedule.from_dict(schedule_row)
    assert schedule.user_id is None
    executor = cast(FastAPI, jwt_client.app).state.scheduler_executor
    call_endpoint = AsyncMock(return_value={"status": "success", "status_code": 200})
    monkeypatch.setattr(executor, "_call_endpoint", call_endpoint)

    result = await executor.execute(schedule, db, release_schedule=False)

    assert result["status"] == "success"
    assert result["user_id"] is None
    call_endpoint.assert_awaited_once_with(schedule)
    stored_run = db.get_schedule_run(result["id"])
    assert stored_run is not None
    assert stored_run["status"] == "success"
    assert stored_run["user_id"] is None
