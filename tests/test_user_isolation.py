"""Integration tests for per-user data isolation with real AgentOS routes."""

from collections.abc import Iterator
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

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"

pytestmark = pytest.mark.db


def _headers(sub: str, scopes: list[str] | None = None) -> dict[str, str]:
    from agno.os.auth import create_dev_token

    token = create_dev_token(sub, secret=DEV_KEY, audience=DEV_AUDIENCE, scopes=scopes)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def isolated_client() -> Iterator[TestClient]:
    """Build the full application with JWT authentication and user isolation."""
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


def _create_session(client: TestClient, owner: str, session_id: str) -> None:
    response = client.post(
        "/sessions?type=agent",
        headers=_headers(owner),
        json={"session_id": session_id, "agent_id": "team-leader", "user_id": "spoofed-user"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == owner


def test_isolation_is_enabled(isolated_client: TestClient) -> None:
    """The assembled application exposes the effective isolation setting."""
    assert cast(FastAPI, isolated_client.app).state.user_isolation_enabled is True


def test_sessions_are_scoped_to_their_owner(isolated_client: TestClient) -> None:
    """Session list/get/create honor ownership and ignore spoofed user ids."""
    session_id = f"session-{uuid4().hex}"
    _create_session(isolated_client, "alice", session_id)

    alice_list = isolated_client.get("/sessions", headers=_headers("alice"))
    assert alice_list.status_code == 200
    assert session_id in {row["session_id"] for row in alice_list.json()["data"]}

    bob_list = isolated_client.get("/sessions?user_id=alice", headers=_headers("bob"))
    assert bob_list.status_code == 200
    assert session_id not in {row["session_id"] for row in bob_list.json()["data"]}
    assert isolated_client.get(f"/sessions/{session_id}", headers=_headers("bob")).status_code == 404

    collision = isolated_client.post(
        "/sessions?type=agent",
        headers=_headers("bob"),
        json={"session_id": session_id, "agent_id": "team-leader"},
    )
    assert collision.status_code == 409

    assert isolated_client.get(f"/sessions/{session_id}", headers=_headers("alice")).status_code == 200
    admin_response = isolated_client.get(f"/sessions/{session_id}", headers=_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert admin_response.json()["user_id"] == "alice"


def test_runs_are_scoped_to_their_owner(isolated_client: TestClient) -> None:
    """Run list/get endpoints cannot cross the parent session's owner."""
    session_id = f"session-{uuid4().hex}"
    run_id = f"run-{uuid4().hex}"
    _create_session(isolated_client, "alice", session_id)
    run = RunOutput(
        run_id=run_id,
        agent_id="team-leader",
        session_id=session_id,
        user_id="alice",
        content="Alice's private run",
        status=RunStatus.completed,
    )
    get_postgres_db().upsert_run(run, session_id=session_id, user_id="alice", run_index=0)

    alice_runs = isolated_client.get(f"/sessions/{session_id}/runs", headers=_headers("alice"))
    assert alice_runs.status_code == 200
    assert run_id in {row["run_id"] for row in alice_runs.json()}
    assert isolated_client.get(f"/sessions/{session_id}/runs/{run_id}", headers=_headers("alice")).status_code == 200

    assert isolated_client.get(f"/sessions/{session_id}/runs", headers=_headers("bob")).status_code == 404
    assert isolated_client.get(f"/sessions/{session_id}/runs/{run_id}", headers=_headers("bob")).status_code == 404

    admin_response = isolated_client.get(f"/sessions/{session_id}/runs/{run_id}", headers=_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert admin_response.json()["run_id"] == run_id


def test_memories_are_scoped_to_their_owner(isolated_client: TestClient) -> None:
    """Memory list/get/update honor ownership and ignore spoofed user ids."""
    created = isolated_client.post(
        "/memories",
        headers=_headers("alice"),
        json={"memory": "Alice's private memory", "user_id": "bob", "topics": ["private"]},
    )
    assert created.status_code == 200, created.text
    memory_id = created.json()["memory_id"]
    assert created.json()["user_id"] == "alice"

    alice_list = isolated_client.get("/memories", headers=_headers("alice"))
    assert memory_id in {row["memory_id"] for row in alice_list.json()["data"]}
    bob_list = isolated_client.get("/memories?user_id=alice", headers=_headers("bob"))
    assert memory_id not in {row["memory_id"] for row in bob_list.json()["data"]}
    assert isolated_client.get(f"/memories/{memory_id}", headers=_headers("bob")).status_code == 404

    forbidden_update = isolated_client.patch(f"/memories/{memory_id}", headers=_headers("bob"), json={"memory": "Overwritten", "user_id": "bob"})
    assert forbidden_update.status_code == 404
    assert isolated_client.get(f"/memories/{memory_id}", headers=_headers("alice")).json()["memory"] == "Alice's private memory"

    admin_response = isolated_client.get(f"/memories/{memory_id}", headers=_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert admin_response.json()["user_id"] == "alice"


def test_agui_rejects_cross_user_thread_write(isolated_client: TestClient) -> None:
    """A user cannot append a run to another user's AG-UI thread."""
    session_id = f"thread-{uuid4().hex}"
    _create_session(isolated_client, "alice", session_id)
    payload = {
        "thread_id": session_id,
        "run_id": f"run-{uuid4().hex}",
        "state": {},
        "messages": [{"id": f"message-{uuid4().hex}", "role": "user", "content": "cross-user write"}],
        "tools": [],
        "context": [],
        "forwarded_props": {"user_id": "bob"},
    }

    response = isolated_client.post("/agui", headers=_headers("bob"), json=payload)

    assert response.status_code == 404
    stored = get_postgres_db().get_session(session_id=session_id, deserialize=False)
    assert isinstance(stored, dict)
    assert stored["user_id"] == "alice"


def test_unowned_schedule_is_hidden_from_users_but_visible_to_admin(isolated_client: TestClient) -> None:
    """The system ETF schedule remains unowned rather than becoming user-shared."""
    user_response = isolated_client.get("/schedules", headers=_headers("alice"))
    assert user_response.status_code == 200
    assert "etf_grid_daily_sync" not in {row["name"] for row in user_response.json()["data"]}

    admin_response = isolated_client.get("/schedules", headers=_headers("operator", ["agent_os:admin"]))
    assert admin_response.status_code == 200
    assert "etf_grid_daily_sync" in {row["name"] for row in admin_response.json()["data"]}


@pytest.mark.asyncio
async def test_unowned_schedule_still_executes(isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The official Executor records a successful unowned run under isolation."""
    db = get_postgres_db()
    schedule_row = db.get_schedule_by_name("etf_grid_daily_sync")
    assert schedule_row is not None
    schedule = Schedule.from_dict(schedule_row)
    assert schedule.user_id is None
    executor = cast(FastAPI, isolated_client.app).state.scheduler_executor
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
