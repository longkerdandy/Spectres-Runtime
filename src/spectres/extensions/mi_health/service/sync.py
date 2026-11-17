"""Single-process coordination for bounded owner-triggered Mi Fitness synchronization."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.exc import SQLAlchemyError

from spectres.extensions.mi_health.credentials import CredentialProtectionError
from spectres.extensions.mi_health.mapping import (
    PROVIDER,
    MiFitnessMappingError,
    filter_raw_window,
    map_body,
    map_daily,
    map_profile,
    map_sleep,
    map_workout,
)
from spectres.extensions.mi_health.models import MiHealthBinding
from spectres.extensions.mi_health.service.bindings import MiHealthBindingService, NotBoundError
from spectres.extensions.mi_health.service.runs import SyncFailureStage, SyncInProgressError, SyncRun, SyncRunStream
from spectres.extensions.mi_health.service.sessions import MiHealthSessionService
from spectres.extensions.mi_health.xiaomi import (
    AuthenticationRequiredError,
    HealthSession,
    HealthUnauthorizedError,
    ProviderUnavailableError,
    XiaomiClient,
    XiaomiError,
)
from spectres.health.ingestion import CheckpointConflictError, HealthIngestionService, HealthRecord
from spectres.health.models import HealthIngestionState

logger = logging.getLogger(__name__)
_BACKFILL_SECONDS = 366 * 86400
_WINDOW_SECONDS = 7 * 86400
_OVERLAP_SECONDS = 2 * 86400
_MAX_PAGES = 100
_DAILY_STREAMS = {
    "daily_activity": "steps",
    "daily_heart_rate": "heart_rate",
    "daily_spo2": "spo2",
    "daily_sleep": "sleep",
}
_STREAMS = ("profile", *_DAILY_STREAMS, "sleep_sessions", "body_measurements", "workouts")
_SyncTerminalStatus = Literal["succeeded", "partially_failed", "failed"]


@dataclass(frozen=True)
class SyncStreamResult:
    """Safe public outcome containing no health measurements or raw payloads."""

    stream: str
    status: Literal["succeeded", "failed"]
    record_count: int
    error_code: str | None


@dataclass(frozen=True)
class SyncStreamHealth:
    """Current checkpoint health for one owner and stream."""

    stream: str
    status: Literal["never_synced", "succeeded", "failed"]
    last_run_started_at: datetime | None
    last_succeeded_at: datetime | None
    last_failed_at: datetime | None
    last_successful_window_end: datetime | None
    backfill_completed: bool
    last_error_code: str | None


@dataclass(frozen=True)
class SyncStatus:
    """Current-process active/latest runs plus durable stream health."""

    active_run: SyncRun | None
    last_run: SyncRun | None
    streams: list[SyncStreamHealth]


class MiHealthSyncService:
    """Coordinate one event-loop-local synchronization per verified owner."""

    def __init__(
        self,
        *,
        bindings: MiHealthBindingService,
        sessions: MiHealthSessionService,
        xiaomi: XiaomiClient,
        ingestion: HealthIngestionService,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Inject shared binding, transport, Core ingestion, and volatile state."""
        self._bindings = bindings
        self._sessions = sessions
        self._xiaomi = xiaomi
        self._ingestion = ingestion
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_runs: dict[str, SyncRun] = {}
        self._last_runs: dict[str, SyncRun] = {}

    async def start(self, user_id: str) -> SyncRun:
        """Acquire the owner lock without waiting and create a queued snapshot."""
        lock = await self._acquire(user_id)
        try:
            with self._bindings.session_factory() as session, session.begin():
                binding = session.get(MiHealthBinding, user_id, with_for_update=True)
                if binding is None:
                    raise NotBoundError("Mi Health is not bound")
                if binding.status != "authenticated":
                    raise AuthenticationRequiredError("Mi Health requires owner reauthorization")
            now = datetime.now(UTC)
            run = SyncRun(
                id=str(uuid.uuid4()),
                trigger_type="manual",
                status="queued",
                streams=[SyncRunStream(stream, "pending", 0, None, None, None, None) for stream in _STREAMS],
                error_code=None,
                created_at=now,
                started_at=None,
                finished_at=None,
            )
            self._active_runs[user_id] = run
            return _copy_run(run)
        except BaseException:
            lock.release()
            raise

    async def execute(self, user_id: str, run_id: str) -> None:
        """Execute the matching active run and release its owner lock on every path."""
        run = self._active_runs.get(user_id)
        if run is None or run.id != run_id or run.status != "queued":
            return
        lock = self._locks[user_id]
        try:
            now = datetime.now(UTC)
            self._active_runs[user_id] = replace(run, status="running", started_at=now)
            try:
                results = await self.sync(user_id, run_id=run_id)
            except Exception as exc:
                error_code = _error_code(exc)
                self._finish(user_id, run_id, status="failed", error_code=error_code)
                logger.warning(
                    "Mi Health synchronization run failed",
                    extra={"event": "mi_health_sync_run_failed", "run_id": run_id, "error_code": error_code},
                )
            else:
                status: _SyncTerminalStatus
                if results and all(result.status == "succeeded" for result in results):
                    status = "succeeded"
                elif any(result.status == "succeeded" for result in results):
                    status = "partially_failed"
                else:
                    status = "failed"
                self._finish(user_id, run_id, status=status)
        finally:
            self._complete_execution(user_id, run_id)
            lock.release()

    async def unbind(self, user_id: str) -> None:
        """Delete owner state under the execution lock and clear volatile runs."""
        lock = await self._acquire(user_id)
        try:
            self._bindings.unbind(user_id)
            self._active_runs.pop(user_id, None)
            self._last_runs.pop(user_id, None)
        finally:
            lock.release()

    def status(self, user_id: str) -> SyncStatus:
        """Read volatile runs and durable checkpoints without contacting Xiaomi."""
        active_run = self._active_runs.get(user_id)
        last_run = self._last_runs.get(user_id)
        checkpoints = {state.stream: state for state in self._ingestion.checkpoints(user_id, PROVIDER)}
        return SyncStatus(
            active_run=_copy_run(active_run) if active_run is not None else None,
            last_run=_copy_run(last_run) if last_run is not None else None,
            streams=[_stream_health(stream, checkpoints.get(stream)) for stream in _STREAMS],
        )

    async def sync(self, user_id: str, *, run_id: str | None = None) -> list[SyncStreamResult]:
        """Run independent streams with at most one renewal and retry per stream."""
        current = self._health_session(user_id)
        results: list[SyncStreamResult] = []
        for stream in _STREAMS:
            failure_stage: SyncFailureStage | None = None
            if run_id is not None:
                self._start_stream(user_id, run_id, stream)
            try:
                result, current = await self._sync_with_retry(user_id, stream, current)
            except (CredentialProtectionError, NotBoundError) as exc:
                if run_id is not None:
                    self._complete_stream(
                        user_id,
                        run_id,
                        stream,
                        status="failed",
                        record_count=0,
                        failure_stage=_failure_stage(exc),
                        error_code=_error_code(exc),
                    )
                raise
            except Exception as exc:
                failure_stage = _failure_stage(exc)
                error_code = _error_code(exc)
                self._ingestion.mark_failed(user_id, PROVIDER, stream, error_code=error_code)
                result = SyncStreamResult(
                    stream=stream,
                    status="failed",
                    record_count=0,
                    error_code=error_code,
                )
                logger.warning(
                    "Mi Health stream synchronization failed",
                    extra={"event": "mi_health_sync_stream_failed", "user_id": user_id, "provider": PROVIDER, "stream": stream, "error_code": error_code},
                )
            if run_id is not None:
                self._complete_stream(
                    user_id,
                    run_id,
                    stream,
                    status=result.status,
                    record_count=result.record_count,
                    failure_stage=failure_stage,
                    error_code=result.error_code,
                )
            results.append(result)
        if any(result.status == "succeeded" for result in results):
            self._sessions.mark_authenticated(user_id)
        return results

    async def _acquire(self, user_id: str) -> asyncio.Lock:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        if lock.locked():
            raise SyncInProgressError("Mi Health synchronization is active")
        await lock.acquire()
        return lock

    def _start_stream(self, user_id: str, run_id: str, stream: str) -> None:
        run = self._matching_active_run(user_id, run_id)
        if run is None:
            return
        now = datetime.now(UTC)
        streams = [replace(item, status="running", started_at=now) if item.stream == stream else item for item in run.streams]
        if all(item.stream != stream for item in run.streams):
            raise ValueError("run stream is not declared")
        self._active_runs[user_id] = replace(run, streams=streams)

    def _complete_stream(
        self,
        user_id: str,
        run_id: str,
        stream: str,
        *,
        status: Literal["succeeded", "failed", "skipped"],
        record_count: int,
        failure_stage: SyncFailureStage | None,
        error_code: str | None,
    ) -> None:
        run = self._matching_active_run(user_id, run_id)
        if run is None:
            return
        now = datetime.now(UTC)
        streams = [
            replace(item, status=status, record_count=record_count, failure_stage=failure_stage, error_code=error_code, finished_at=now) if item.stream == stream else item for item in run.streams
        ]
        if all(item.stream != stream for item in run.streams):
            raise ValueError("run stream is not declared")
        self._active_runs[user_id] = replace(run, streams=streams)

    def _finish(self, user_id: str, run_id: str, *, status: _SyncTerminalStatus, error_code: str | None = None) -> None:
        run = self._matching_active_run(user_id, run_id)
        if run is None:
            return
        now = datetime.now(UTC)
        streams = []
        for item in run.streams:
            if item.status == "running":
                item = replace(
                    item,
                    status="failed",
                    error_code=error_code or "sync_failed",
                    finished_at=now,
                )
            elif item.status == "pending":
                item = replace(item, status="skipped", error_code=error_code, finished_at=now)
            streams.append(item)
        self._active_runs[user_id] = replace(run, status=status, streams=streams, error_code=error_code, finished_at=now)

    def _matching_active_run(self, user_id: str, run_id: str) -> SyncRun | None:
        run = self._active_runs.get(user_id)
        return run if run is not None and run.id == run_id else None

    def _complete_execution(self, user_id: str, run_id: str) -> None:
        run = self._matching_active_run(user_id, run_id)
        if run is None:
            return
        if run.status not in {"queued", "running"}:
            self._last_runs[user_id] = _copy_run(run)
        self._active_runs.pop(user_id, None)

    async def _sync_with_retry(self, user_id: str, stream: str, current: HealthSession) -> tuple[SyncStreamResult, HealthSession]:
        try:
            return await self._sync_stream(user_id, stream, current), current
        except HealthUnauthorizedError:
            await self._sessions.renew(user_id)
            current = self._health_session(user_id)
            try:
                return await self._sync_stream(user_id, stream, current), current
            except HealthUnauthorizedError:
                self._sessions.mark_reauth_required(user_id)
                raise AuthenticationRequiredError("Xiaomi rejected the health request after one renewal") from None

    async def _sync_stream(self, user_id: str, stream: str, current: HealthSession) -> SyncStreamResult:
        state = self._ingestion.checkpoint(user_id, PROVIDER, stream)
        expected_revision = self._ingestion.mark_started(user_id, PROVIDER, stream)
        now = int(self._clock())
        if stream == "profile":
            payload = await self._xiaomi.read_profile(current)
            records: Sequence[HealthRecord] = [map_profile(payload)]
            self._ingestion.complete_window(
                user_id,
                PROVIDER,
                stream,
                expected_revision=expected_revision,
                window_end=now,
                backfill_completed=True,
                records=records,
            )
            return SyncStreamResult(stream, "succeeded", 1, None)

        windows = _windows(state.backfill_completed if state is not None else False, state.last_successful_window_end if state is not None else None, now)
        total = 0
        for index, (start, end) in enumerate(windows):
            rows = await self._read_window(current, stream, start=start, end=end)
            records = _map_rows(stream, rows)
            final_backfill = index == len(windows) - 1
            self._ingestion.complete_window(
                user_id,
                PROVIDER,
                stream,
                expected_revision=expected_revision,
                window_end=now if final_backfill else end,
                backfill_completed=final_backfill,
                records=records,
            )
            expected_revision += 1
            total += len(records)
        return SyncStreamResult(stream, "succeeded", total, None)

    async def _read_window(self, current: HealthSession, stream: str, *, start: int, end: int) -> list[dict[str, Any]]:
        if stream in _DAILY_STREAMS:
            key = _DAILY_STREAMS[stream]

            async def read(next_key: str | None) -> dict[str, Any]:
                return await self._xiaomi.read_daily(current, key=key, start_time=start, end_time=end, next_key=next_key)

            rows = await _all_pages(read, list_field="data_list")
            return _filter_rows(rows, start=start, end=end)
        if stream in {"sleep_sessions", "body_measurements"}:
            key = "sleep" if stream == "sleep_sessions" else "weight"

            async def read_raw(next_key: str | None) -> dict[str, Any]:
                return await self._xiaomi.read_raw(current, key=key, start_time=start, end_time=end, next_key=next_key)

            rows = await _all_pages(read_raw, list_field="data_list")
            return filter_raw_window(rows, start_time=start, end_time=end)

        async def read_workouts(next_key: str | None) -> dict[str, Any]:
            return await self._xiaomi.read_workouts(current, start_time=start, end_time=end, next_key=next_key)

        rows = await _all_pages(read_workouts, list_field="sport_records")
        return _filter_rows(rows, start=start, end=end)

    def _health_session(self, user_id: str) -> HealthSession:
        with self._bindings.session_factory() as session:
            binding = session.get(MiHealthBinding, user_id)
            if binding is None:
                raise NotBoundError("Mi Health is not bound")
            return self._bindings.health_session(binding)


def _copy_run(run: SyncRun) -> SyncRun:
    return replace(run, streams=list(run.streams))


def _stream_health(stream: str, state: HealthIngestionState | None) -> SyncStreamHealth:
    if state is None:
        return SyncStreamHealth(stream, "never_synced", None, None, None, None, False, None)
    latest_failure = state.last_failed_at is not None and (state.last_succeeded_at is None or state.last_failed_at > state.last_succeeded_at)
    status: Literal["never_synced", "succeeded", "failed"]
    if latest_failure:
        status = "failed"
    elif state.last_succeeded_at is not None:
        status = "succeeded"
    else:
        status = "never_synced"
    return SyncStreamHealth(
        stream=stream,
        status=status,
        last_run_started_at=state.last_run_started_at,
        last_succeeded_at=state.last_succeeded_at,
        last_failed_at=state.last_failed_at,
        last_successful_window_end=(datetime.fromtimestamp(state.last_successful_window_end, UTC) if state.last_successful_window_end is not None else None),
        backfill_completed=state.backfill_completed,
        last_error_code=state.last_error_code,
    )


async def _all_pages(read: Callable[[str | None], Awaitable[dict[str, Any]]], *, list_field: str) -> list[dict[str, Any]]:
    """Read a complete page sequence without persisting opaque cursors."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(_MAX_PAGES):
        result = await read(cursor)
        page_rows = result.get(list_field)
        if not isinstance(page_rows, list) or not all(isinstance(row, dict) for row in page_rows) or not isinstance(result.get("has_more"), bool):
            raise ProviderUnavailableError("Xiaomi returned an invalid paginated result")
        rows.extend(page_rows)
        if not result["has_more"]:
            return rows
        next_cursor = result.get("next_key")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise ProviderUnavailableError("Xiaomi returned an invalid pagination cursor")
        seen.add(next_cursor)
        cursor = next_cursor
    raise ProviderUnavailableError("Xiaomi pagination exceeded its page limit")


def _map_rows(stream: str, rows: list[dict[str, Any]]) -> Sequence[HealthRecord]:
    if stream in _DAILY_STREAMS:
        return [map_daily(row) for row in rows]
    if stream == "sleep_sessions":
        return [map_sleep(row) for row in rows]
    if stream == "body_measurements":
        return [map_body(row) for row in rows]
    return [map_workout(row) for row in rows]


def _filter_rows(rows: list[dict[str, Any]], *, start: int, end: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        timestamp = row.get("time")
        if isinstance(timestamp, bool) or timestamp is None:
            raise ProviderUnavailableError("Xiaomi returned an invalid record timestamp")
        try:
            epoch = int(timestamp)
        except (TypeError, ValueError, OverflowError):
            raise ProviderUnavailableError("Xiaomi returned an invalid record timestamp") from None
        if start <= epoch <= end:
            selected.append(row)
    return selected


def _windows(backfill_completed: bool, last_window_end: int | None, now: int) -> list[tuple[int, int]]:
    if backfill_completed and last_window_end is not None:
        start = max(0, last_window_end - _OVERLAP_SECONDS)
        return [(start, now)]
    earliest = max(0, now - _BACKFILL_SECONDS)
    windows: list[tuple[int, int]] = []
    end = now
    while end > earliest:
        start = max(earliest, end - _WINDOW_SECONDS)
        windows.append((start, end))
        end = start
    return windows


def _error_code(exc: Exception) -> str:
    if isinstance(exc, AuthenticationRequiredError | HealthUnauthorizedError):
        return "authentication_required"
    if isinstance(exc, CheckpointConflictError):
        return "checkpoint_conflict"
    if isinstance(exc, MiFitnessMappingError):
        return "invalid_provider_record"
    if isinstance(exc, XiaomiError):
        return "provider_unavailable"
    if isinstance(exc, CredentialProtectionError):
        return "credential_protection_unavailable"
    if isinstance(exc, SQLAlchemyError):
        return "database_write_failed"
    return "sync_failed"


def _failure_stage(exc: Exception) -> SyncFailureStage | None:
    if isinstance(exc, AuthenticationRequiredError | HealthUnauthorizedError):
        return "authentication"
    if isinstance(exc, CheckpointConflictError):
        return "checkpoint_conflict"
    if isinstance(exc, MiFitnessMappingError):
        return "record_mapping"
    if isinstance(exc, XiaomiError):
        return "provider_read"
    if isinstance(exc, SQLAlchemyError):
        return "database_write"
    return None
