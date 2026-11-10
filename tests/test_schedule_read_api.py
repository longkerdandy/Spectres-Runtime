"""Integration tests for Agno-native schedule and schedule-run read APIs."""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from agno.db.schemas.scheduler import Schedule, ScheduleRun
from fastapi.testclient import TestClient

from spectres.db.postgres import get_postgres_db

DEV_KEY = "test-only-verification-key-not-a-secret-0123456789abcdef"
DEV_AUDIENCE = "https://spectres.runtime/api"
ALICE = "schedule-read-alice"
BOB = "schedule-read-bob"
ADMIN = "schedule-read-operator"
USER_SCOPES = ["schedules:read"]
ADMIN_SCOPES = ["agent_os:admin"]

pytestmark = pytest.mark.db


@dataclass(frozen=True)
class ScheduleFixtures:
    """Owned and unowned schedule/read-history ids used by the contract tests."""

    public_schedule_id: str
    alice_schedule_ids: tuple[str, str]
    bob_schedule_id: str
    public_run_id: str
    alice_run_ids: tuple[str, str]
    bob_run_id: str


def _headers(sub: str, scopes: list[str] | None = None) -> dict[str, str]:
    from agno.os.auth import create_dev_token

    token = create_dev_token(sub, secret=DEV_KEY, audience=DEV_AUDIENCE, scopes=USER_SCOPES if scopes is None else scopes)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def schedule_client() -> Iterator[TestClient]:
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


@pytest.fixture
def schedule_fixtures(schedule_client: TestClient) -> Iterator[ScheduleFixtures]:
    """Seed and clean public/personal data without using production write routes."""
    del schedule_client
    db = get_postgres_db()
    now = int(time.time())
    suffix = uuid4().hex
    public_schedule_id = f"schedule-{uuid4().hex}"
    alice_schedule_ids = (f"schedule-{uuid4().hex}", f"schedule-{uuid4().hex}")
    bob_schedule_id = f"schedule-{uuid4().hex}"
    schedules = [
        Schedule(
            id=public_schedule_id,
            name=f"public-system-{suffix}",
            description="Unowned public system schedule",
            endpoint="/agents/team-leader/runs",
            cron_expr="0 8 * * 1",
            timezone="UTC",
            next_run_at=4102444800,
            enabled=True,
            user_id=None,
            created_at=now,
        ),
        Schedule(
            id=alice_schedule_ids[0],
            name=f"alice-enabled-{suffix}",
            description="Alice enabled personal schedule",
            endpoint="/agents/team-leader/runs",
            payload={"owner": "fixture"},
            cron_expr="0 9 * * 1",
            timezone="Asia/Shanghai",
            next_run_at=4102444800,
            enabled=True,
            user_id=ALICE,
            created_at=now,
        ),
        Schedule(
            id=alice_schedule_ids[1],
            name=f"alice-disabled-{suffix}",
            description="Alice disabled personal schedule",
            endpoint="/agents/team-leader/runs",
            cron_expr="0 10 * * 1",
            timezone="UTC",
            next_run_at=None,
            enabled=False,
            user_id=ALICE,
            created_at=now + 1,
        ),
        Schedule(
            id=bob_schedule_id,
            name=f"bob-personal-{suffix}",
            description="Bob personal schedule",
            endpoint="/agents/team-leader/runs",
            cron_expr="0 11 * * 1",
            timezone="UTC",
            next_run_at=4102444800,
            enabled=True,
            user_id=BOB,
            created_at=now + 2,
        ),
    ]
    for schedule in schedules:
        db.create_schedule(schedule.to_dict())

    public_run_id = f"schedule-run-{uuid4().hex}"
    alice_run_ids = (f"schedule-run-{uuid4().hex}", f"schedule-run-{uuid4().hex}")
    bob_run_id = f"schedule-run-{uuid4().hex}"
    runs = [
        ScheduleRun(
            id=public_run_id,
            schedule_id=public_schedule_id,
            status="success",
            status_code=200,
            triggered_at=now,
            completed_at=now + 1,
            user_id=None,
            created_at=now,
        ),
        ScheduleRun(
            id=alice_run_ids[0],
            schedule_id=alice_schedule_ids[0],
            status="success",
            status_code=200,
            input={"fixture": "alice-first"},
            output={"result": "ok"},
            requirements=[],
            triggered_at=now + 2,
            completed_at=now + 3,
            user_id=ALICE,
            created_at=now + 2,
        ),
        ScheduleRun(
            id=alice_run_ids[1],
            schedule_id=alice_schedule_ids[0],
            attempt=2,
            status="failed",
            status_code=500,
            error="fixture failure",
            triggered_at=now + 4,
            completed_at=now + 5,
            user_id=ALICE,
            created_at=now + 4,
        ),
        ScheduleRun(
            id=bob_run_id,
            schedule_id=bob_schedule_id,
            status="success",
            status_code=200,
            triggered_at=now + 6,
            completed_at=now + 7,
            user_id=BOB,
            created_at=now + 6,
        ),
    ]
    for run in runs:
        db.create_schedule_run(run.to_dict())

    try:
        yield ScheduleFixtures(
            public_schedule_id=public_schedule_id,
            alice_schedule_ids=alice_schedule_ids,
            bob_schedule_id=bob_schedule_id,
            public_run_id=public_run_id,
            alice_run_ids=alice_run_ids,
            bob_run_id=bob_run_id,
        )
    finally:
        for schedule_id in (public_schedule_id, *alice_schedule_ids, bob_schedule_id):
            db.delete_schedule(schedule_id)


def test_openapi_exposes_native_read_routes(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """The four read routes are supplied by AgentOS with their native paths."""
    del schedule_fixtures
    paths = schedule_client.get("/openapi.json").json()["paths"]
    for path in ("/schedules", "/schedules/{schedule_id}", "/schedules/{schedule_id}/runs", "/schedules/{schedule_id}/runs/{run_id}"):
        assert "get" in paths[path]


def test_schedule_list_enforces_agno_visibility(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Users receive only their own tasks; admin receives public and all personal tasks."""
    alice_response = schedule_client.get("/schedules?user_id=schedule-read-bob&scope=all", headers=_headers(ALICE))
    assert alice_response.status_code == 200
    assert {row["id"] for row in alice_response.json()["data"]} == set(schedule_fixtures.alice_schedule_ids)
    assert alice_response.json()["meta"]["total_count"] == 2

    bob_response = schedule_client.get("/schedules", headers=_headers(BOB))
    assert bob_response.status_code == 200
    assert {row["id"] for row in bob_response.json()["data"]} == {schedule_fixtures.bob_schedule_id}

    admin_response = schedule_client.get("/schedules?limit=1000", headers=_headers(ADMIN, ADMIN_SCOPES))
    assert admin_response.status_code == 200
    admin_ids = {row["id"] for row in admin_response.json()["data"]}
    assert {
        schedule_fixtures.public_schedule_id,
        *schedule_fixtures.alice_schedule_ids,
        schedule_fixtures.bob_schedule_id,
    } <= admin_ids


def test_schedule_list_filters_and_paginates(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Enabled filtering and page totals apply inside the caller's owner scope."""
    enabled = schedule_client.get("/schedules?enabled=true", headers=_headers(ALICE))
    disabled = schedule_client.get("/schedules?enabled=false", headers=_headers(ALICE))
    assert {row["id"] for row in enabled.json()["data"]} == {schedule_fixtures.alice_schedule_ids[0]}
    assert {row["id"] for row in disabled.json()["data"]} == {schedule_fixtures.alice_schedule_ids[1]}

    first = schedule_client.get("/schedules?limit=1&page=1", headers=_headers(ALICE))
    second = schedule_client.get("/schedules?limit=1&page=2", headers=_headers(ALICE))
    empty = schedule_client.get("/schedules?limit=1&page=3", headers=_headers(ALICE))
    assert first.status_code == second.status_code == empty.status_code == 200
    assert first.json()["meta"] == {"page": 1, "limit": 1, "total_pages": 2, "total_count": 2, "search_time_ms": 0.0}
    assert second.json()["meta"] == {"page": 2, "limit": 1, "total_pages": 2, "total_count": 2, "search_time_ms": 0.0}
    assert empty.json()["meta"] == {"page": 3, "limit": 1, "total_pages": 2, "total_count": 2, "search_time_ms": 0.0}
    first_ids = {row["id"] for row in first.json()["data"]}
    second_ids = {row["id"] for row in second.json()["data"]}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == set(schedule_fixtures.alice_schedule_ids)
    assert empty.json()["data"] == []

    no_tasks = schedule_client.get("/schedules", headers=_headers("schedule-read-carol"))
    assert no_tasks.status_code == 200
    assert no_tasks.json() == {"data": [], "meta": {"page": 1, "limit": 100, "total_pages": 0, "total_count": 0, "search_time_ms": 0.0}}


def test_schedule_detail_enforces_visibility_and_schema(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Direct schedule reads hide public and cross-user rows and preserve Agno's schema."""
    own_id = schedule_fixtures.alice_schedule_ids[0]
    own = schedule_client.get(f"/schedules/{own_id}", headers=_headers(ALICE))
    assert own.status_code == 200
    assert own.json()["user_id"] == ALICE
    assert own.json()["payload"] == {"owner": "fixture"}
    assert set(own.json()) == {
        "id",
        "user_id",
        "name",
        "description",
        "method",
        "endpoint",
        "payload",
        "cron_expr",
        "timezone",
        "timeout_seconds",
        "max_retries",
        "retry_delay_seconds",
        "enabled",
        "next_run_at",
        "managed_by",
        "target_type",
        "target_id",
        "disabled_reason",
        "created_at",
        "updated_at",
    }

    for schedule_id in (schedule_fixtures.public_schedule_id, schedule_fixtures.bob_schedule_id, "missing-schedule"):
        assert schedule_client.get(f"/schedules/{schedule_id}", headers=_headers(ALICE)).status_code == 404

    for schedule_id in (schedule_fixtures.public_schedule_id, own_id, schedule_fixtures.bob_schedule_id):
        response = schedule_client.get(f"/schedules/{schedule_id}", headers=_headers(ADMIN, ADMIN_SCOPES))
        assert response.status_code == 200
        assert response.json()["id"] == schedule_id


def test_schedule_run_list_enforces_visibility_and_paginates(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Run history follows the parent schedule owner for both list and detail reads."""
    alice_schedule_id = schedule_fixtures.alice_schedule_ids[0]
    first = schedule_client.get(f"/schedules/{alice_schedule_id}/runs?limit=1&page=1", headers=_headers(ALICE))
    second = schedule_client.get(f"/schedules/{alice_schedule_id}/runs?limit=1&page=2", headers=_headers(ALICE))
    assert first.status_code == second.status_code == 200
    assert first.json()["meta"]["total_count"] == second.json()["meta"]["total_count"] == 2
    assert first.json()["meta"]["total_pages"] == second.json()["meta"]["total_pages"] == 2
    listed_ids = {row["id"] for response in (first, second) for row in response.json()["data"]}
    assert listed_ids == set(schedule_fixtures.alice_run_ids)

    for schedule_id in (schedule_fixtures.public_schedule_id, schedule_fixtures.bob_schedule_id, "missing-schedule"):
        assert schedule_client.get(f"/schedules/{schedule_id}/runs", headers=_headers(ALICE)).status_code == 404

    for schedule_id, run_id in (
        (schedule_fixtures.public_schedule_id, schedule_fixtures.public_run_id),
        (alice_schedule_id, schedule_fixtures.alice_run_ids[0]),
        (schedule_fixtures.bob_schedule_id, schedule_fixtures.bob_run_id),
    ):
        response = schedule_client.get(f"/schedules/{schedule_id}/runs", headers=_headers(ADMIN, ADMIN_SCOPES))
        assert response.status_code == 200
        assert run_id in {row["id"] for row in response.json()["data"]}


def test_schedule_run_detail_enforces_visibility_schema_and_parent(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """A run id cannot be read across owners or paired with a different schedule."""
    alice_schedule_id = schedule_fixtures.alice_schedule_ids[0]
    alice_run_id = schedule_fixtures.alice_run_ids[0]
    own = schedule_client.get(f"/schedules/{alice_schedule_id}/runs/{alice_run_id}", headers=_headers(ALICE))
    assert own.status_code == 200
    assert own.json()["user_id"] == ALICE
    assert own.json()["output"] == {"result": "ok"}
    assert set(own.json()) == {
        "id",
        "schedule_id",
        "user_id",
        "attempt",
        "triggered_at",
        "completed_at",
        "status",
        "status_code",
        "run_id",
        "session_id",
        "error",
        "input",
        "output",
        "requirements",
        "created_at",
    }

    inaccessible = (
        (schedule_fixtures.public_schedule_id, schedule_fixtures.public_run_id),
        (schedule_fixtures.bob_schedule_id, schedule_fixtures.bob_run_id),
        (alice_schedule_id, schedule_fixtures.bob_run_id),
        (schedule_fixtures.bob_schedule_id, alice_run_id),
        (alice_schedule_id, "missing-schedule-run"),
    )
    for schedule_id, run_id in inaccessible:
        assert schedule_client.get(f"/schedules/{schedule_id}/runs/{run_id}", headers=_headers(ALICE)).status_code == 404
    assert schedule_client.get(f"/schedules/{alice_schedule_id}/runs/{schedule_fixtures.bob_run_id}", headers=_headers(ADMIN, ADMIN_SCOPES)).status_code == 404

    for schedule_id, run_id in (
        (schedule_fixtures.public_schedule_id, schedule_fixtures.public_run_id),
        (alice_schedule_id, alice_run_id),
        (schedule_fixtures.bob_schedule_id, schedule_fixtures.bob_run_id),
    ):
        response = schedule_client.get(f"/schedules/{schedule_id}/runs/{run_id}", headers=_headers(ADMIN, ADMIN_SCOPES))
        assert response.status_code == 200
        assert response.json()["id"] == run_id


def test_read_routes_require_authentication_and_read_scope(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """All read routes reject missing/invalid JWTs and tokens without schedule read permission."""
    paths = (
        "/schedules",
        f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}",
        f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}/runs",
        f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}/runs/{schedule_fixtures.alice_run_ids[0]}",
    )
    for path in paths:
        assert schedule_client.get(path).status_code == 401
        assert schedule_client.get(path, headers={"Authorization": "Bearer invalid-jwt"}).status_code == 401
        assert schedule_client.get(path, headers=_headers(ALICE, [])).status_code == 403


@pytest.mark.parametrize("query", ["limit=0", "limit=1001", "page=0"])
def test_list_routes_validate_pagination(schedule_client: TestClient, schedule_fixtures: ScheduleFixtures, query: str) -> None:
    """Native list parameter bounds apply to schedules and their run history."""
    assert schedule_client.get(f"/schedules?{query}", headers=_headers(ALICE)).status_code == 422
    runs_path = f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}/runs?{query}"
    assert schedule_client.get(runs_path, headers=_headers(ALICE)).status_code == 422
