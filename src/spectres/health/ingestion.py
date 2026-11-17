"""Provider-neutral health upsert, checkpoint, and cleanup services."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from spectres.health.contracts import BodyMeasurement, DailySummary, ProfileSnapshot, SleepSession, Workout
from spectres.health.models import (
    HealthBodyMeasurement,
    HealthDailySummary,
    HealthIngestionState,
    HealthProfile,
    HealthSleepSession,
    HealthWorkout,
)

type HealthRecord = ProfileSnapshot | DailySummary | SleepSession | BodyMeasurement | Workout
HEALTH_DATA_MODELS = (HealthProfile, HealthDailySummary, HealthSleepSession, HealthBodyMeasurement, HealthWorkout)


class CheckpointConflictError(RuntimeError):
    """A synchronization checkpoint changed while its provider window was read."""


class HealthRepository:
    """Issue canonical health writes inside a caller-owned SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        """Bind all repository operations to one explicit transaction session."""
        self._session = session

    def upsert_profile(self, user_id: str, provider: str, record: ProfileSnapshot, *, now: datetime) -> None:
        """Merge supplied profile fields without erasing previously learned values."""
        supplied = record.model_fields_set
        values = _contract_values(record, supplied)
        values.update({"user_id": user_id, "provider": provider, "provider_metadata": record.provider_metadata, "synced_at": now})
        statement = pg_insert(HealthProfile).values(**values)
        updates = {key: getattr(statement.excluded, key) for key in values if key not in {"user_id", "provider"}}
        self._session.execute(statement.on_conflict_do_update(index_elements=["user_id", "provider"], set_=updates))

    def upsert_daily(self, user_id: str, provider: str, record: DailySummary, *, now: datetime) -> None:
        """Merge one metric stream into its owner/provider/local-day row."""
        supplied = record.model_fields_set
        values = _contract_values(record, supplied - {"day"})
        values.update(
            {
                "user_id": user_id,
                "provider": provider,
                "day": record.day,
                "provider_metadata": record.provider_metadata,
                "raw_payload": record.raw_payload,
                "synced_at": now,
            }
        )
        statement = pg_insert(HealthDailySummary).values(**values)
        updates = {key: getattr(statement.excluded, key) for key in values if key not in {"user_id", "provider", "day", "provider_metadata", "raw_payload"}}
        updates["provider_metadata"] = HealthDailySummary.provider_metadata.op("||")(statement.excluded.provider_metadata)
        updates["raw_payload"] = HealthDailySummary.raw_payload.op("||")(statement.excluded.raw_payload)
        self._session.execute(statement.on_conflict_do_update(index_elements=["user_id", "provider", "day"], set_=updates))

    def upsert_sleep(self, user_id: str, provider: str, record: SleepSession, *, now: datetime) -> None:
        """Upsert one correctable or deleted raw sleep event."""
        self._upsert_history(HealthSleepSession, user_id, provider, record, now=now)

    def upsert_body(self, user_id: str, provider: str, record: BodyMeasurement, *, now: datetime) -> None:
        """Upsert one weight/body-composition measurement."""
        self._upsert_history(HealthBodyMeasurement, user_id, provider, record, now=now)

    def upsert_workout(self, user_id: str, provider: str, record: Workout, *, now: datetime) -> None:
        """Upsert one workout summary."""
        self._upsert_history(HealthWorkout, user_id, provider, record, now=now)

    def _upsert_history(
        self,
        model: type[HealthSleepSession] | type[HealthBodyMeasurement] | type[HealthWorkout],
        user_id: str,
        provider: str,
        record: SleepSession | BodyMeasurement | Workout,
        *,
        now: datetime,
    ) -> None:
        values = record.model_dump()
        values.update({"user_id": user_id, "provider": provider, "synced_at": now})
        statement = pg_insert(model).values(**values)
        updates = {key: getattr(statement.excluded, key) for key in values if key not in {"user_id", "provider", "source_record_id"}}
        self._session.execute(statement.on_conflict_do_update(index_elements=["user_id", "provider", "source_record_id"], set_=updates))

    def checkpoint(self, user_id: str, provider: str, stream: str) -> HealthIngestionState | None:
        """Read one owner/provider/stream checkpoint."""
        return self._session.get(HealthIngestionState, (user_id, provider, stream))

    def checkpoints(self, user_id: str, provider: str) -> list[HealthIngestionState]:
        """Read all checkpoints for one owner and provider."""
        statement = select(HealthIngestionState).where(
            HealthIngestionState.user_id == user_id,
            HealthIngestionState.provider == provider,
        )
        return list(self._session.scalars(statement))

    def mark_started(self, user_id: str, provider: str, stream: str, *, now: datetime) -> int:
        """Record an attempt and return the revision required for its commit."""
        current = self.checkpoint(user_id, provider, stream)
        if current is None:
            current = HealthIngestionState(user_id=user_id, provider=provider, stream=stream, last_run_started_at=now)
            self._session.add(current)
            self._session.flush()
            return current.revision
        current.last_run_started_at = now
        self._session.flush()
        return current.revision

    def mark_failed(self, user_id: str, provider: str, stream: str, *, error_code: str, now: datetime) -> None:
        """Record a safe stream failure without advancing its successful window."""
        current = self.checkpoint(user_id, provider, stream)
        if current is None:
            current = HealthIngestionState(user_id=user_id, provider=provider, stream=stream)
            self._session.add(current)
        current.last_failed_at = now
        current.consecutive_failures += 1
        current.last_error_code = error_code[:64]
        current.revision += 1

    def complete_window(
        self,
        user_id: str,
        provider: str,
        stream: str,
        *,
        expected_revision: int,
        window_end: int,
        backfill_completed: bool,
        records: Sequence[HealthRecord],
        now: datetime,
    ) -> None:
        """Atomically write one complete window and advance its checkpoint."""
        current = self.checkpoint(user_id, provider, stream)
        if current is None or current.revision != expected_revision:
            raise CheckpointConflictError("Health ingestion checkpoint changed during synchronization")
        for record in records:
            self.upsert(user_id, provider, record, now=now)
        current.last_successful_window_end = window_end
        current.backfill_completed = backfill_completed
        current.last_succeeded_at = now
        current.last_error_code = None
        current.consecutive_failures = 0
        current.revision += 1
        self._session.flush()

    def upsert(self, user_id: str, provider: str, record: HealthRecord, *, now: datetime) -> None:
        """Dispatch a typed canonical record to its declared storage contract."""
        _validate_owner_provider(user_id, provider)
        if isinstance(record, ProfileSnapshot):
            self.upsert_profile(user_id, provider, record, now=now)
        elif isinstance(record, DailySummary):
            self.upsert_daily(user_id, provider, record, now=now)
        elif isinstance(record, SleepSession):
            self.upsert_sleep(user_id, provider, record, now=now)
        elif isinstance(record, BodyMeasurement):
            self.upsert_body(user_id, provider, record, now=now)
        else:
            self.upsert_workout(user_id, provider, record, now=now)

    def delete_provider_data(self, user_id: str, provider: str) -> None:
        """Delete only one owner's contribution from one provider."""
        _validate_owner_provider(user_id, provider)
        self._session.execute(delete(HealthIngestionState).where(HealthIngestionState.user_id == user_id, HealthIngestionState.provider == provider))
        for model in HEALTH_DATA_MODELS:
            self._session.execute(delete(model).where(model.user_id == user_id, model.provider == provider))


class HealthIngestionService:
    """Manage canonical health transactions with an injected session factory."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Use the Runtime composition root's shared database session factory."""
        self._session_factory = session_factory

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Expose the shared factory for adapter transaction orchestration."""
        return self._session_factory

    def repository(self, session: Session) -> HealthRepository:
        """Create a repository participating in an existing transaction."""
        return HealthRepository(session)

    def upsert(self, user_id: str, provider: str, record: HealthRecord) -> None:
        """Upsert one canonical record in its own transaction."""
        with self._session_factory() as session, session.begin():
            self.repository(session).upsert(user_id, provider, record, now=datetime.now(UTC))

    def upsert_many(self, user_id: str, provider: str, records: Iterable[HealthRecord]) -> None:
        """Upsert a complete typed batch atomically."""
        with self._session_factory() as session, session.begin():
            repository = self.repository(session)
            now = datetime.now(UTC)
            for record in records:
                repository.upsert(user_id, provider, record, now=now)

    def checkpoint(self, user_id: str, provider: str, stream: str) -> HealthIngestionState | None:
        """Read one detached checkpoint for sync planning."""
        with self._session_factory() as session:
            state = self.repository(session).checkpoint(user_id, provider, stream)
            if state is not None:
                session.expunge(state)
            return state

    def checkpoints(self, user_id: str, provider: str) -> list[HealthIngestionState]:
        """Read detached checkpoints for one owner's provider status."""
        with self._session_factory() as session:
            states = self.repository(session).checkpoints(user_id, provider)
            for state in states:
                session.expunge(state)
            return states

    def mark_started(self, user_id: str, provider: str, stream: str) -> int:
        """Persist a stream attempt start and return its optimistic revision."""
        with self._session_factory() as session, session.begin():
            return self.repository(session).mark_started(user_id, provider, stream, now=datetime.now(UTC))

    def mark_failed(self, user_id: str, provider: str, stream: str, *, error_code: str) -> None:
        """Persist only a typed error code and failure timestamps."""
        with self._session_factory() as session, session.begin():
            self.repository(session).mark_failed(user_id, provider, stream, error_code=error_code, now=datetime.now(UTC))

    def complete_window(
        self,
        user_id: str,
        provider: str,
        stream: str,
        *,
        expected_revision: int,
        window_end: int,
        backfill_completed: bool,
        records: Sequence[HealthRecord],
    ) -> None:
        """Commit a complete provider window together with its checkpoint."""
        with self._session_factory() as session, session.begin():
            self.repository(session).complete_window(
                user_id,
                provider,
                stream,
                expected_revision=expected_revision,
                window_end=window_end,
                backfill_completed=backfill_completed,
                records=records,
                now=datetime.now(UTC),
            )

    def delete_provider_data(self, user_id: str, provider: str, *, session: Session | None = None) -> None:
        """Delete provider data alone or within an adapter-owned transaction."""
        if session is not None:
            self.repository(session).delete_provider_data(user_id, provider)
            return
        with self._session_factory() as owned_session, owned_session.begin():
            self.repository(owned_session).delete_provider_data(user_id, provider)


def _validate_owner_provider(user_id: str, provider: str) -> None:
    if not user_id or not provider:
        raise ValueError("health owner and provider are required")


def _contract_values(record: HealthRecord, supplied: set[str]) -> dict[str, Any]:
    values = record.model_dump(include=supplied)
    values.pop("provider_metadata", None)
    values.pop("raw_payload", None)
    return values
