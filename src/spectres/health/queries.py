"""Owner-scoped current and longitudinal health query boundary."""

from datetime import date
from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from spectres.health.models import HealthBodyMeasurement, HealthDailySummary, HealthIngestionState, HealthProfile, HealthSleepSession, HealthWorkout

HistoryModel = TypeVar("HistoryModel", HealthSleepSession, HealthBodyMeasurement, HealthWorkout)
RowModel = TypeVar("RowModel")


class HealthQueryService:
    """Read health data only for a verified Runtime owner."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Inject the shared Runtime database session factory."""
        self._session_factory = session_factory

    def profiles(self, user_id: str, *, provider: str | None = None) -> list[HealthProfile]:
        """Return current provider snapshots without merging providers."""
        statement = select(HealthProfile).where(HealthProfile.user_id == user_id)
        if provider is not None:
            statement = statement.where(HealthProfile.provider == provider)
        return self._all(statement)

    def daily_summaries(
        self,
        user_id: str,
        *,
        start_day: date | None = None,
        end_day: date | None = None,
        provider: str | None = None,
    ) -> list[HealthDailySummary]:
        """Return provider-distinct daily history in reverse day order."""
        statement = select(HealthDailySummary).where(HealthDailySummary.user_id == user_id)
        if provider is not None:
            statement = statement.where(HealthDailySummary.provider == provider)
        if start_day is not None:
            statement = statement.where(HealthDailySummary.day >= start_day)
        if end_day is not None:
            statement = statement.where(HealthDailySummary.day <= end_day)
        return self._all(statement.order_by(HealthDailySummary.day.desc(), HealthDailySummary.provider))

    def latest_body_measurements(self, user_id: str, *, provider: str | None = None, measured_only: bool = False) -> list[HealthBodyMeasurement]:
        """Return the latest non-deleted measurement independently per provider."""
        statement = select(HealthBodyMeasurement).where(HealthBodyMeasurement.user_id == user_id, HealthBodyMeasurement.is_deleted.is_(False))
        if provider is not None:
            statement = statement.where(HealthBodyMeasurement.provider == provider)
        if measured_only:
            statement = statement.where(HealthBodyMeasurement.composition_status == "measured")
        rows = self._all(statement.order_by(HealthBodyMeasurement.provider, HealthBodyMeasurement.measured_at.desc()))
        latest: dict[str, HealthBodyMeasurement] = {}
        for row in rows:
            latest.setdefault(row.provider, row)
        return list(latest.values())

    def sleep_sessions(self, user_id: str, *, provider: str | None = None, limit: int = 100) -> list[HealthSleepSession]:
        """Return recent non-deleted sleep history for the verified owner."""
        statement = select(HealthSleepSession).where(HealthSleepSession.user_id == user_id, HealthSleepSession.is_deleted.is_(False))
        if provider is not None:
            statement = statement.where(HealthSleepSession.provider == provider)
        return self._history(statement.order_by(HealthSleepSession.started_at.desc()), limit)

    def body_measurements(self, user_id: str, *, provider: str | None = None, limit: int = 100) -> list[HealthBodyMeasurement]:
        """Return recent non-deleted weight history for the verified owner."""
        statement = select(HealthBodyMeasurement).where(HealthBodyMeasurement.user_id == user_id, HealthBodyMeasurement.is_deleted.is_(False))
        if provider is not None:
            statement = statement.where(HealthBodyMeasurement.provider == provider)
        return self._history(statement.order_by(HealthBodyMeasurement.measured_at.desc()), limit)

    def workouts(self, user_id: str, *, provider: str | None = None, limit: int = 100) -> list[HealthWorkout]:
        """Return recent non-deleted workout summaries for the verified owner."""
        statement = select(HealthWorkout).where(HealthWorkout.user_id == user_id, HealthWorkout.is_deleted.is_(False))
        if provider is not None:
            statement = statement.where(HealthWorkout.provider == provider)
        return self._history(statement.order_by(HealthWorkout.started_at.desc()), limit)

    def ingestion_states(self, user_id: str, *, provider: str | None = None) -> list[HealthIngestionState]:
        """Return safe synchronization state for the verified owner."""
        statement = select(HealthIngestionState).where(HealthIngestionState.user_id == user_id)
        if provider is not None:
            statement = statement.where(HealthIngestionState.provider == provider)
        return self._all(statement.order_by(HealthIngestionState.provider, HealthIngestionState.stream))

    def _history(self, statement: Select[tuple[HistoryModel]], limit: int) -> list[HistoryModel]:
        if not 1 <= limit <= 1000:
            raise ValueError("health history limit must be between 1 and 1000")
        return self._all(statement.limit(limit))

    def _all(self, statement: Select[tuple[RowModel]]) -> list[RowModel]:
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            for row in rows:
                session.expunge(row)
            return list(rows)
