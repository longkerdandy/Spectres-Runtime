"""Integration tests for Agno-native schedule and schedule-run read APIs."""

import time
from dataclasses import dataclass
from uuid import uuid4

import pytest
from agno.db.schemas.scheduler import Schedule, ScheduleRun
from fastapi.testclient import TestClient

from spectres.db.postgres import get_postgres_db
from tests.support import ADMIN_SCOPES, auth_headers

ALICE = "schedule-read-alice"
BOB = "schedule-read-bob"
ADMIN = "schedule-read-operator"
USER_SCOPES = ["schedules:read"]

pytestmark = [pytest.mark.integration, pytest.mark.db]


@dataclass(frozen=True)
class ScheduleFixtures:
    """Owned and unowned schedule/read-history ids used by the contract tests."""

    public_schedule_id: str
    alice_schedule_ids: tuple[str, str]
    bob_schedule_id: str
    public_run_id: str
    alice_run_ids: tuple[str, str]
    bob_run_id: str


@pytest.fixture
def schedule_fixtures(jwt_client: TestClient) -> ScheduleFixtures:
    """Seed public/personal data without using production write routes."""
    del jwt_client
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

    return ScheduleFixtures(
        public_schedule_id=public_schedule_id,
        alice_schedule_ids=alice_schedule_ids,
        bob_schedule_id=bob_schedule_id,
        public_run_id=public_run_id,
        alice_run_ids=alice_run_ids,
        bob_run_id=bob_run_id,
    )


def test_schedule_list_enforces_agno_visibility(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Users receive only their own tasks; admin receives public and all personal tasks."""
    alice_response = jwt_client.get("/schedules?user_id=schedule-read-bob&scope=all", headers=auth_headers(ALICE, USER_SCOPES))
    assert alice_response.status_code == 200
    assert {row["id"] for row in alice_response.json()["data"]} == set(schedule_fixtures.alice_schedule_ids)
    assert alice_response.json()["meta"]["total_count"] == 2

    bob_response = jwt_client.get("/schedules", headers=auth_headers(BOB, USER_SCOPES))
    assert bob_response.status_code == 200
    assert {row["id"] for row in bob_response.json()["data"]} == {schedule_fixtures.bob_schedule_id}

    admin_response = jwt_client.get("/schedules?limit=1000", headers=auth_headers(ADMIN, ADMIN_SCOPES))
    assert admin_response.status_code == 200
    admin_ids = {row["id"] for row in admin_response.json()["data"]}
    assert {
        schedule_fixtures.public_schedule_id,
        *schedule_fixtures.alice_schedule_ids,
        schedule_fixtures.bob_schedule_id,
    } <= admin_ids


def test_schedule_list_filters_and_paginates(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Enabled filtering and page totals apply inside the caller's owner scope."""
    enabled = jwt_client.get("/schedules?enabled=true", headers=auth_headers(ALICE, USER_SCOPES))
    disabled = jwt_client.get("/schedules?enabled=false", headers=auth_headers(ALICE, USER_SCOPES))
    assert {row["id"] for row in enabled.json()["data"]} == {schedule_fixtures.alice_schedule_ids[0]}
    assert {row["id"] for row in disabled.json()["data"]} == {schedule_fixtures.alice_schedule_ids[1]}

    first = jwt_client.get("/schedules?limit=1&page=1", headers=auth_headers(ALICE, USER_SCOPES))
    second = jwt_client.get("/schedules?limit=1&page=2", headers=auth_headers(ALICE, USER_SCOPES))
    empty = jwt_client.get("/schedules?limit=1&page=3", headers=auth_headers(ALICE, USER_SCOPES))
    assert first.status_code == second.status_code == empty.status_code == 200
    assert first.json()["meta"] == {"page": 1, "limit": 1, "total_pages": 2, "total_count": 2, "search_time_ms": 0.0}
    assert second.json()["meta"] == {"page": 2, "limit": 1, "total_pages": 2, "total_count": 2, "search_time_ms": 0.0}
    assert empty.json()["meta"] == {"page": 3, "limit": 1, "total_pages": 2, "total_count": 2, "search_time_ms": 0.0}
    first_ids = {row["id"] for row in first.json()["data"]}
    second_ids = {row["id"] for row in second.json()["data"]}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == set(schedule_fixtures.alice_schedule_ids)
    assert empty.json()["data"] == []

    no_tasks = jwt_client.get("/schedules", headers=auth_headers("schedule-read-carol", USER_SCOPES))
    assert no_tasks.status_code == 200
    assert no_tasks.json() == {"data": [], "meta": {"page": 1, "limit": 100, "total_pages": 0, "total_count": 0, "search_time_ms": 0.0}}


def test_schedule_detail_enforces_visibility_and_schema(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Direct schedule reads hide public and cross-user rows and preserve Agno's schema."""
    own_id = schedule_fixtures.alice_schedule_ids[0]
    own = jwt_client.get(f"/schedules/{own_id}", headers=auth_headers(ALICE, USER_SCOPES))
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
        assert jwt_client.get(f"/schedules/{schedule_id}", headers=auth_headers(ALICE, USER_SCOPES)).status_code == 404

    for schedule_id in (schedule_fixtures.public_schedule_id, own_id, schedule_fixtures.bob_schedule_id):
        response = jwt_client.get(f"/schedules/{schedule_id}", headers=auth_headers(ADMIN, ADMIN_SCOPES))
        assert response.status_code == 200
        assert response.json()["id"] == schedule_id


def test_schedule_run_list_enforces_visibility_and_paginates(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """Run history follows the parent schedule owner for both list and detail reads."""
    alice_schedule_id = schedule_fixtures.alice_schedule_ids[0]
    first = jwt_client.get(f"/schedules/{alice_schedule_id}/runs?limit=1&page=1", headers=auth_headers(ALICE, USER_SCOPES))
    second = jwt_client.get(f"/schedules/{alice_schedule_id}/runs?limit=1&page=2", headers=auth_headers(ALICE, USER_SCOPES))
    assert first.status_code == second.status_code == 200
    assert first.json()["meta"]["total_count"] == second.json()["meta"]["total_count"] == 2
    assert first.json()["meta"]["total_pages"] == second.json()["meta"]["total_pages"] == 2
    listed_ids = {row["id"] for response in (first, second) for row in response.json()["data"]}
    assert listed_ids == set(schedule_fixtures.alice_run_ids)

    for schedule_id in (schedule_fixtures.public_schedule_id, schedule_fixtures.bob_schedule_id, "missing-schedule"):
        assert jwt_client.get(f"/schedules/{schedule_id}/runs", headers=auth_headers(ALICE, USER_SCOPES)).status_code == 404

    for schedule_id, run_id in (
        (schedule_fixtures.public_schedule_id, schedule_fixtures.public_run_id),
        (alice_schedule_id, schedule_fixtures.alice_run_ids[0]),
        (schedule_fixtures.bob_schedule_id, schedule_fixtures.bob_run_id),
    ):
        response = jwt_client.get(f"/schedules/{schedule_id}/runs", headers=auth_headers(ADMIN, ADMIN_SCOPES))
        assert response.status_code == 200
        assert run_id in {row["id"] for row in response.json()["data"]}


def test_schedule_run_detail_enforces_visibility_schema_and_parent(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """A run id cannot be read across owners or paired with a different schedule."""
    alice_schedule_id = schedule_fixtures.alice_schedule_ids[0]
    alice_run_id = schedule_fixtures.alice_run_ids[0]
    own = jwt_client.get(f"/schedules/{alice_schedule_id}/runs/{alice_run_id}", headers=auth_headers(ALICE, USER_SCOPES))
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
        assert jwt_client.get(f"/schedules/{schedule_id}/runs/{run_id}", headers=auth_headers(ALICE, USER_SCOPES)).status_code == 404
    assert jwt_client.get(f"/schedules/{alice_schedule_id}/runs/{schedule_fixtures.bob_run_id}", headers=auth_headers(ADMIN, ADMIN_SCOPES)).status_code == 404

    for schedule_id, run_id in (
        (schedule_fixtures.public_schedule_id, schedule_fixtures.public_run_id),
        (alice_schedule_id, alice_run_id),
        (schedule_fixtures.bob_schedule_id, schedule_fixtures.bob_run_id),
    ):
        response = jwt_client.get(f"/schedules/{schedule_id}/runs/{run_id}", headers=auth_headers(ADMIN, ADMIN_SCOPES))
        assert response.status_code == 200
        assert response.json()["id"] == run_id


def test_read_routes_require_authentication_and_read_scope(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures) -> None:
    """All read routes reject missing/invalid JWTs and tokens without schedule read permission."""
    paths = (
        "/schedules",
        f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}",
        f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}/runs",
        f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}/runs/{schedule_fixtures.alice_run_ids[0]}",
    )
    for path in paths:
        assert jwt_client.get(path).status_code == 401
        assert jwt_client.get(path, headers={"Authorization": "Bearer invalid-jwt"}).status_code == 401
        assert jwt_client.get(path, headers=auth_headers(ALICE, [])).status_code == 403


@pytest.mark.parametrize("query", ["limit=0", "limit=1001", "page=0"])
def test_list_routes_validate_pagination(jwt_client: TestClient, schedule_fixtures: ScheduleFixtures, query: str) -> None:
    """Native list parameter bounds apply to schedules and their run history."""
    assert jwt_client.get(f"/schedules?{query}", headers=auth_headers(ALICE, USER_SCOPES)).status_code == 422
    runs_path = f"/schedules/{schedule_fixtures.alice_schedule_ids[0]}/runs?{query}"
    assert jwt_client.get(runs_path, headers=auth_headers(ALICE, USER_SCOPES)).status_code == 422
