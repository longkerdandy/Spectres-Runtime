"""Owner-triggered Mi Fitness mapping, bounded sync, and checkpoint orchestration."""

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

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


@dataclass(frozen=True)
class SyncStreamResult:
    """Safe public outcome containing no health measurements or raw payloads."""

    stream: str
    status: Literal["succeeded", "failed"]
    record_count: int
    backfill_completed: bool
    last_successful_window_end: int | None
    error_code: str | None


class MiHealthSyncService:
    """Synchronize only the verified owner's current Xiaomi binding."""

    def __init__(
        self,
        *,
        bindings: MiHealthBindingService,
        sessions: MiHealthSessionService,
        xiaomi: XiaomiClient,
        ingestion: HealthIngestionService,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Inject shared binding, transport, Core ingestion, and a bounded clock."""
        self._bindings = bindings
        self._sessions = sessions
        self._xiaomi = xiaomi
        self._ingestion = ingestion
        self._clock = clock

    async def sync(self, user_id: str) -> list[SyncStreamResult]:
        """Run independent streams with at most one renewal and retry per stream."""
        current = self._health_session(user_id)
        results: list[SyncStreamResult] = []
        for stream in _STREAMS:
            try:
                result, current = await self._sync_with_retry(user_id, stream, current)
            except (CredentialProtectionError, NotBoundError):
                raise
            except Exception as exc:
                error_code = _error_code(exc)
                self._ingestion.mark_failed(user_id, PROVIDER, stream, error_code=error_code)
                state = self._ingestion.checkpoint(user_id, PROVIDER, stream)
                result = SyncStreamResult(
                    stream=stream,
                    status="failed",
                    record_count=0,
                    backfill_completed=state.backfill_completed if state is not None else False,
                    last_successful_window_end=state.last_successful_window_end if state is not None else None,
                    error_code=error_code,
                )
                logger.warning(
                    "Mi Health stream synchronization failed",
                    extra={"event": "mi_health_sync_stream_failed", "user_id": user_id, "provider": PROVIDER, "stream": stream, "error_code": error_code},
                )
            results.append(result)
        if any(result.status == "succeeded" for result in results):
            self._sessions.mark_authenticated(user_id)
        return results

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
            return SyncStreamResult(stream, "succeeded", 1, True, now, None)

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
        return SyncStreamResult(stream, "succeeded", total, True, now, None)

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
    return "sync_failed"
