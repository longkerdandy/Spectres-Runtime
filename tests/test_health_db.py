"""Real-PostgreSQL tests for Core health persistence, isolation, and checkpoints."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from spectres.db.postgres import get_postgres_db
from spectres.health.contracts import BodyMeasurement, DailySummary, ProfileSnapshot, SleepSession, Workout
from spectres.health.ingestion import CheckpointConflictError, HealthIngestionService
from spectres.health.models import HealthBase, HealthIngestionState, HealthProfile, HealthSleepSession, HealthWorkout
from spectres.health.queries import HealthQueryService

pytestmark = [pytest.mark.integration, pytest.mark.db]
_NOW = datetime(2026, 11, 15, 23, 0, tzinfo=UTC)


@pytest.fixture
def services() -> tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]:
    """Build Core health services over migrated tables."""
    session_factory = sessionmaker(bind=get_postgres_db().db_engine)
    return HealthIngestionService(session_factory), HealthQueryService(session_factory), session_factory


def _sleep(source_id: str = "v1:sleep:sid:sleep:1", *, deleted: bool = False, duration: int = 400) -> SleepSession:
    return SleepSession(
        source_record_id=source_id,
        source_device_id="sid",
        started_at=_NOW - timedelta(hours=7),
        ended_at=_NOW,
        duration_minutes=duration,
        deep_minutes=90,
        is_deleted=deleted,
        provider_metadata={"source_epoch": 1},
        raw_payload={"items": [{"state": 99}]},
    )


def _body(provider_id: str = "v1:weight:sid:weight:1", *, status: str = "measured") -> BodyMeasurement:
    return BodyMeasurement(
        source_record_id=provider_id,
        source_device_id="sid",
        measured_at=_NOW,
        weight_kg=Decimal("70.25"),
        bmi=Decimal("22.50"),
        composition_status=status,  # type: ignore[arg-type]
        body_fat_rate=Decimal("20.50") if status == "measured" else None,
        provider_metadata={"source_epoch": 1},
        raw_payload={"body_fat_rate": "20.50" if status == "measured" else "0"},
    )


def _workout(source_id: str = "v1:workout:sid:sport:1", *, deleted: bool = False) -> Workout:
    return Workout(
        source_record_id=source_id,
        started_at=_NOW - timedelta(hours=1),
        ended_at=_NOW,
        duration_seconds=3600,
        provider_activity_code="999",
        is_deleted=deleted,
        raw_payload={"sport_type": 999},
    )


def test_migration_creates_exactly_six_channel_independent_health_tables(services: tuple[object, ...]) -> None:
    """The Core schema has six health tables, expected indexes, and no channel FK."""
    inspector = inspect(get_postgres_db().db_engine)
    health_tables = {name for name in inspector.get_table_names() if name.startswith("health_")}

    assert health_tables == set(HealthBase.metadata.tables)
    assert len(health_tables) == 6
    for table in health_tables:
        assert inspector.get_foreign_keys(table) == []
    assert {index["name"] for index in inspector.get_indexes("health_sleep_sessions")} >= {"ix_health_sleep_sessions_user_started"}
    assert {index["name"] for index in inspector.get_indexes("health_body_measurements")} >= {"ix_health_body_measurements_user_measured"}
    assert {index["name"] for index in inspector.get_indexes("health_workouts")} >= {"ix_health_workouts_user_started"}


def test_profile_and_daily_partial_merges_are_owner_provider_scoped(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """Partial current/daily writes neither erase values nor cross ownership boundaries."""
    ingestion, queries, _ = services
    ingestion.upsert("alice", "mi_fitness", ProfileSnapshot(height_cm=Decimal("175.00"), birth_year=1990))
    ingestion.upsert("alice", "mi_fitness", ProfileSnapshot(daily_step_goal=8000))
    ingestion.upsert("alice", "other", ProfileSnapshot(height_cm=Decimal("160.00")))
    ingestion.upsert("bob", "mi_fitness", ProfileSnapshot(height_cm=Decimal("180.00")))

    alice = queries.profiles("alice", provider="mi_fitness")[0]
    assert alice.height_cm == Decimal("175.00")
    assert alice.birth_year == 1990
    assert alice.daily_step_goal == 8000
    assert len(queries.profiles("alice")) == 2
    assert queries.profiles("bob", provider="mi_fitness")[0].height_cm == Decimal("180.00")

    day = date(2026, 11, 15)
    ingestion.upsert("alice", "mi_fitness", DailySummary(day=day, steps=0, distance_m=0, raw_payload={"steps": {"steps": 0}}))
    ingestion.upsert(
        "alice",
        "mi_fitness",
        DailySummary(day=day, avg_hr_bpm=None, max_hr_bpm=150, provider_metadata={"heart_rate": {"sid": "sid"}}, raw_payload={"heart_rate": {"max_hr": 150}}),
    )
    ingestion.upsert("bob", "mi_fitness", DailySummary(day=day, steps=9000))

    merged = queries.daily_summaries("alice", provider="mi_fitness")[0]
    assert merged.steps == 0
    assert merged.avg_hr_bpm is None
    assert merged.max_hr_bpm == 150
    assert set(merged.raw_payload) == {"steps", "heart_rate"}
    assert set(merged.provider_metadata) == {"heart_rate"}
    assert queries.daily_summaries("bob", provider="mi_fitness")[0].steps == 9000


def test_history_corrections_preserve_identity_creation_and_tombstones(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """Replays/corrections update one row, preserve creation, and hide tombstones."""
    ingestion, queries, session_factory = services
    original = _sleep()
    replay = _sleep()
    ingestion.upsert_many("alice", "mi_fitness", [original, replay])
    with session_factory() as session:
        created_at = session.get(HealthSleepSession, ("alice", "mi_fitness", original.source_record_id)).created_at  # type: ignore[union-attr]

    ingestion.upsert("alice", "mi_fitness", _sleep(duration=420))
    with session_factory() as session:
        corrected = session.get(HealthSleepSession, ("alice", "mi_fitness", original.source_record_id))
        assert corrected is not None
        assert corrected.duration_minutes == 420
        assert corrected.created_at == created_at
        assert corrected.raw_payload["items"][0]["state"] == 99
        assert session.scalar(select(func.count()).select_from(HealthSleepSession)) == 1

    ingestion.upsert("alice", "mi_fitness", _sleep(deleted=True, duration=420))
    assert queries.sleep_sessions("alice") == []
    ingestion.upsert("alice", "mi_fitness", _workout(deleted=True))
    assert queries.workouts("alice") == []


def test_body_numeric_roundtrip_and_latest_queries_do_not_merge_providers(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """Numeric values round-trip exactly and latest values remain provider-distinct."""
    ingestion, queries, _ = services
    ingestion.upsert("alice", "mi_fitness", _body())
    ingestion.upsert("alice", "other", _body(provider_id="v1:weight:other:weight:1", status="unavailable"))
    ingestion.upsert("bob", "mi_fitness", _body(provider_id="v1:weight:sid:weight:2"))

    latest = queries.latest_body_measurements("alice")
    assert {row.provider for row in latest} == {"mi_fitness", "other"}
    mi = next(row for row in latest if row.provider == "mi_fitness")
    assert mi.weight_kg == Decimal("70.25")
    assert mi.body_fat_rate == Decimal("20.50")
    assert [row.provider for row in queries.latest_body_measurements("alice", measured_only=True)] == ["mi_fitness"]
    assert len(queries.body_measurements("bob")) == 1


def test_checkpoint_commit_conflict_and_safe_failure(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """A checkpoint advances atomically once and stale writers cannot commit data."""
    ingestion, queries, session_factory = services
    revision = ingestion.mark_started("alice", "mi_fitness", "sleep_sessions")
    ingestion.complete_window(
        "alice",
        "mi_fitness",
        "sleep_sessions",
        expected_revision=revision,
        window_end=100,
        backfill_completed=True,
        records=[_sleep()],
    )
    with pytest.raises(CheckpointConflictError):
        ingestion.complete_window(
            "alice",
            "mi_fitness",
            "sleep_sessions",
            expected_revision=revision,
            window_end=200,
            backfill_completed=True,
            records=[_sleep("v1:sleep:sid:sleep:2")],
        )
    ingestion.mark_failed("alice", "mi_fitness", "sleep_sessions", error_code="provider_unavailable")

    state = queries.ingestion_states("alice", provider="mi_fitness")[0]
    assert state.last_successful_window_end == 100
    assert state.last_error_code == "provider_unavailable"
    assert state.consecutive_failures == 1
    assert queries.ingestion_states("bob") == []
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(HealthSleepSession)) == 1


def test_provider_cleanup_preserves_other_owners_and_providers(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """Provider-scoped cleanup removes all five data sets and only matching state."""
    ingestion, queries, session_factory = services
    for user_id, provider in (("alice", "mi_fitness"), ("alice", "other"), ("bob", "mi_fitness")):
        ingestion.upsert_many(
            user_id,
            provider,
            [
                ProfileSnapshot(height_cm=Decimal("170")),
                DailySummary(day=date(2026, 11, 15), steps=100),
                _sleep(),
                _body(),
                _workout(),
            ],
        )
        revision = ingestion.mark_started(user_id, provider, "profile")
        ingestion.complete_window(user_id, provider, "profile", expected_revision=revision, window_end=100, backfill_completed=True, records=[])

    ingestion.delete_provider_data("alice", "mi_fitness")

    assert queries.profiles("alice", provider="mi_fitness") == []
    assert queries.daily_summaries("alice", provider="mi_fitness") == []
    assert queries.ingestion_states("alice", provider="mi_fitness") == []
    assert len(queries.profiles("alice", provider="other")) == 1
    assert len(queries.profiles("bob", provider="mi_fitness")) == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(HealthProfile)) == 2
        assert session.scalar(select(func.count()).select_from(HealthIngestionState)) == 2


def test_database_rejects_negative_workout_measurements(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """Reviewed check constraints protect canonical storage outside contracts too."""
    _, _, session_factory = services
    with session_factory() as session, session.begin():
        session.add(
            HealthWorkout(
                user_id="alice",
                provider="mi_fitness",
                source_record_id="v1:workout:sid:sport:negative",
                started_at=_NOW,
                duration_seconds=-1,
                is_deleted=False,
                provider_metadata={},
                raw_payload={},
                synced_at=_NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_daily_summary_date_range_is_inclusive_and_newest_first(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """start_day and end_day bound history inclusively and results stay in reverse day order."""
    ingestion, queries, _ = services
    for day in range(10, 15):
        ingestion.upsert("alice", "mi_fitness", DailySummary(day=date(2026, 11, day), steps=day))

    rows = queries.daily_summaries("alice", start_day=date(2026, 11, 11), end_day=date(2026, 11, 13))

    assert [row.day.day for row in rows] == [13, 12, 11]
    assert queries.daily_summaries("alice", start_day=date(2026, 11, 15)) == []


@pytest.mark.parametrize("limit", [0, 1001])
def test_history_limit_out_of_range_is_rejected(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]], limit: int) -> None:
    """History queries reject limits outside 1..1000 for every history stream."""
    _, queries, _ = services
    for query in (queries.sleep_sessions, queries.body_measurements, queries.workouts):
        with pytest.raises(ValueError, match="between 1 and 1000"):
            query("alice", limit=limit)


def test_history_limit_caps_newest_rows(services: tuple[HealthIngestionService, HealthQueryService, sessionmaker[Session]]) -> None:
    """limit=1 keeps only the most recent non-deleted workout."""
    ingestion, queries, _ = services
    ingestion.upsert("alice", "mi_fitness", _workout("v1:workout:sid:sport:old"))
    newer = _workout("v1:workout:sid:sport:new")
    ingestion.upsert("alice", "mi_fitness", newer.model_copy(update={"started_at": _NOW, "ended_at": _NOW + timedelta(hours=1)}))

    rows = queries.workouts("alice", limit=1)

    assert [row.source_record_id for row in rows] == ["v1:workout:sid:sport:new"]
