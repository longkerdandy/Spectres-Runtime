"""Synthetic bounded-window, pagination, retry, and sync privacy tests."""

import asyncio
import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

import spectres.extensions.mi_health.service.sync as sync_module
from spectres.extensions.mi_health.config import MiHealthConfig
from spectres.extensions.mi_health.service import MiHealthBindingService, MiHealthSessionService, MiHealthSyncService, NotBoundError, SyncInProgressError, SyncStreamResult
from spectres.extensions.mi_health.xiaomi import HealthSession, HealthUnauthorizedError, ProviderUnavailableError, XiaomiClient
from spectres.health.ingestion import CheckpointConflictError, HealthIngestionService
from spectres.health.models import HealthIngestionState

pytestmark = pytest.mark.unit
_SESSION = HealthSession("account", "c-user", "pass", "service", "c2VjcmV0", "device")


def _state(*, completed: bool = True, window_end: int | None = 100) -> HealthIngestionState:
    return HealthIngestionState(user_id="alice", provider="mi_fitness", stream="daily_activity", backfill_completed=completed, last_successful_window_end=window_end, revision=0)


def _service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    streams: tuple[str, ...],
    state: HealthIngestionState | None = None,
) -> tuple[MiHealthSyncService, MagicMock, MagicMock, MagicMock]:
    bindings = MagicMock(spec=MiHealthBindingService)
    sessions = MagicMock(spec=MiHealthSessionService)
    sessions.renew = AsyncMock()
    sessions.mark_reauth_required = MagicMock()
    xiaomi = MagicMock(spec=XiaomiClient)
    xiaomi.read_profile = AsyncMock(return_value={})
    xiaomi.read_daily = AsyncMock(return_value={"data_list": [], "has_more": False, "next_key": None})
    xiaomi.read_raw = AsyncMock(return_value={"data_list": [], "has_more": False, "next_key": None})
    xiaomi.read_workouts = AsyncMock(return_value={"sport_records": [], "has_more": False, "next_key": None})
    ingestion = MagicMock(spec=HealthIngestionService)
    ingestion.checkpoint.return_value = state
    ingestion.mark_started.return_value = 0
    db_session = MagicMock()
    db_session.get.return_value = MagicMock(status="authenticated")
    bindings.session_factory.return_value.__enter__.return_value = db_session
    service = MiHealthSyncService(bindings=bindings, sessions=sessions, xiaomi=xiaomi, ingestion=ingestion, clock=lambda: 200)
    monkeypatch.setattr(service, "_health_session", lambda user_id: _SESSION)
    monkeypatch.setattr(sync_module, "_STREAMS", streams)
    return service, xiaomi, ingestion, sessions


def _daily_page(cursor: str | None = None) -> dict[str, Any]:
    return {
        "data_list": [
            {
                "key": "steps",
                "sid": "sid",
                "time": 150,
                "value": json.dumps({"steps": 100, "distance": 80, "calories": 10}),
            }
        ],
        "has_more": cursor is not None,
        "next_key": cursor,
    }


async def test_complete_pagination_commits_once_with_overlap_and_no_durable_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    """All pages finish before one atomic window commit; overlap catches corrections."""
    monkeypatch.setattr(sync_module, "_OVERLAP_SECONDS", 50)
    service, xiaomi, ingestion, _ = _service(monkeypatch, streams=("daily_activity",), state=_state())
    xiaomi.read_daily.side_effect = [_daily_page("opaque-cursor"), _daily_page()]

    results = await service.sync("alice")

    assert results[0].status == "succeeded"
    assert results[0].record_count == 2
    assert [call.kwargs["next_key"] for call in xiaomi.read_daily.await_args_list] == [None, "opaque-cursor"]
    assert all(call.kwargs["start_time"] == 50 for call in xiaomi.read_daily.await_args_list)
    ingestion.complete_window.assert_called_once()
    kwargs = ingestion.complete_window.call_args.kwargs
    assert kwargs["window_end"] == 200
    assert kwargs["backfill_completed"] is True
    assert all("opaque-cursor" not in repr(record.provider_metadata) for record in kwargs["records"])


@pytest.mark.parametrize(
    "page",
    [
        {"data_list": [], "has_more": True, "next_key": None},
        {"data_list": [], "has_more": True, "next_key": "same"},
    ],
)
async def test_missing_or_repeated_cursor_never_advances_checkpoint(monkeypatch: pytest.MonkeyPatch, page: dict[str, Any]) -> None:
    """Invalid pagination fails closed instead of persisting a truncated window."""
    service, xiaomi, ingestion, _ = _service(monkeypatch, streams=("daily_activity",), state=_state())
    xiaomi.read_daily.return_value = page

    results = await service.sync("alice")

    assert results[0].status == "failed"
    assert results[0].error_code == "provider_unavailable"
    ingestion.complete_window.assert_not_called()
    ingestion.mark_failed.assert_called_once_with("alice", "mi_fitness", "daily_activity", error_code="provider_unavailable")


async def test_stream_failure_does_not_block_an_independent_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """One provider stream can fail while another commits its independent outcome."""
    service, xiaomi, ingestion, _ = _service(monkeypatch, streams=("daily_activity", "daily_heart_rate"), state=_state())

    async def read(session: object, *, key: str, **kwargs: Any) -> dict[str, Any]:
        if key == "steps":
            raise ProviderUnavailableError("synthetic provider failure")
        return {"data_list": [], "has_more": False, "next_key": None}

    xiaomi.read_daily.side_effect = read

    results = await service.sync("alice")

    assert [(result.stream, result.status) for result in results] == [("daily_activity", "failed"), ("daily_heart_rate", "succeeded")]
    ingestion.complete_window.assert_called_once()


async def test_profile_unauthorized_renews_and_retries_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401 causes one renewal and one retry with the fresh current session."""
    service, xiaomi, _, sessions = _service(monkeypatch, streams=("profile",), state=_state())
    xiaomi.read_profile.side_effect = [HealthUnauthorizedError(), {}]

    results = await service.sync("alice")

    assert results[0].status == "succeeded"
    assert xiaomi.read_profile.await_count == 2
    sessions.renew.assert_awaited_once_with("alice")
    sessions.mark_authenticated.assert_called_once_with("alice")


async def test_second_unauthorized_is_a_safe_terminal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second 401 never enters another renewal loop or leaks provider material."""
    service, xiaomi, ingestion, sessions = _service(monkeypatch, streams=("profile",), state=_state())
    xiaomi.read_profile.side_effect = HealthUnauthorizedError("synthetic-token-must-not-leak")

    results = await service.sync("alice")

    assert results[0].status == "failed"
    assert results[0].error_code == "authentication_required"
    assert xiaomi.read_profile.await_count == 2
    sessions.renew.assert_awaited_once_with("alice")
    sessions.mark_reauth_required.assert_called_once_with("alice")
    ingestion.mark_failed.assert_called_once_with("alice", "mi_fitness", "profile", error_code="authentication_required")


async def test_checkpoint_conflict_rolls_back_window_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale checkpoint writer reports failure and cannot claim success."""
    service, _, ingestion, _ = _service(monkeypatch, streams=("daily_activity",), state=_state())
    ingestion.complete_window.side_effect = CheckpointConflictError()

    results = await service.sync("alice")

    assert results[0].status == "failed"
    assert results[0].error_code == "checkpoint_conflict"
    ingestion.mark_failed.assert_called_once_with("alice", "mi_fitness", "daily_activity", error_code="checkpoint_conflict")


def test_initial_backfill_uses_bounded_reverse_windows() -> None:
    """Backfill windows are bounded and newest-first; incremental reads overlap."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_module, "_BACKFILL_SECONDS", 100)
    monkeypatch.setattr(sync_module, "_WINDOW_SECONDS", 40)
    monkeypatch.setattr(sync_module, "_OVERLAP_SECONDS", 10)
    try:
        assert sync_module._windows(False, None, 200) == [(160, 200), (120, 160), (100, 120)]
        assert sync_module._windows(True, 150, 200) == [(140, 200)]
    finally:
        monkeypatch.undo()


async def test_raw_transport_applies_first_bucket_margin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The raw provider request expands only its transport start boundary."""
    client = XiaomiClient(MiHealthConfig(region="cn", credential_key=None, http_timeout_seconds=1, qr_poll_timeout_seconds=1))
    health_get = AsyncMock(return_value={})
    monkeypatch.setattr(client, "_health_get", health_get)

    await client.read_raw(_SESSION, key="weight", start_time=100000, end_time=200000)

    call = health_get.await_args
    assert call is not None
    assert call.kwargs["data"]["start_time"] == 13600
    assert call.kwargs["data"]["end_time"] == 200000
    assert call.kwargs["signature_path"] == "/app/v1/data/get_fitness_data_by_time"


async def test_sync_summary_and_logs_exclude_raw_health_sentinel(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Invalid private values stay out of safe results and operational logs."""
    service, xiaomi, _, _ = _service(monkeypatch, streams=("daily_activity",), state=_state())
    xiaomi.read_daily.return_value = {"data_list": [{"key": "steps", "sid": "sid", "time": 150, "value": "not-json-private-sentinel"}], "has_more": False}

    results = await service.sync("alice")

    assert results[0].status == "failed"
    assert "private-sentinel" not in repr(results)
    assert "private-sentinel" not in caplog.text


async def test_same_owner_start_conflicts_without_queue_and_success_releases_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second start is rejected immediately and a completed run permits another."""
    service, _, _, _ = _service(monkeypatch, streams=("profile",))
    run = await service.start("alice")

    with pytest.raises(SyncInProgressError):
        await service.start("alice")
    assert service.status("alice").active_run is not None

    await service.execute("alice", run.id)
    last = service.status("alice").last_run
    assert last is not None and last.status == "succeeded"
    second = await service.start("alice")
    assert second.id != run.id
    current = service.status("alice")
    assert current.active_run is not None and current.active_run.id == second.id
    assert current.last_run is not None and current.last_run.id == run.id


async def test_different_owners_have_independent_locks_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """One owner's active execution does not block another owner."""
    service, _, _, _ = _service(monkeypatch, streams=("profile",))
    alice = await service.start("alice")
    bob = await service.start("bob")

    await asyncio.gather(service.execute("alice", alice.id), service.execute("bob", bob.id))

    alice_last = service.status("alice").last_run
    bob_last = service.status("bob").last_run
    assert alice_last is not None and alice_last.id == alice.id
    assert bob_last is not None and bob_last.id == bob.id


async def test_execute_records_independent_stream_outcomes_and_partial_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A volatile run records each stream independently before aggregate completion."""
    service, xiaomi, _, _ = _service(monkeypatch, streams=("daily_activity", "daily_heart_rate"), state=_state())

    async def read(session: object, *, key: str, **kwargs: Any) -> dict[str, Any]:
        if key == "steps":
            raise ProviderUnavailableError("synthetic provider failure")
        return {"data_list": [], "has_more": False, "next_key": None}

    xiaomi.read_daily.side_effect = read
    run = await service.start("alice")
    await service.execute("alice", run.id)

    last = service.status("alice").last_run
    assert last is not None and last.status == "partially_failed"
    assert [(item.stream, item.status) for item in last.streams] == [("daily_activity", "failed"), ("daily_heart_rate", "succeeded")]
    assert last.streams[0].failure_stage == "provider_read"
    assert last.streams[0].error_code == "provider_unavailable"


@pytest.mark.parametrize(
    ("error", "error_code"),
    [
        (ProviderUnavailableError("private-sentinel"), "provider_unavailable"),
        (RuntimeError("private-sentinel"), "sync_failed"),
    ],
)
async def test_execute_failure_releases_lock_with_safe_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    error_code: str,
) -> None:
    """Expected and unexpected background failures release the lock without leaks."""
    service, _, _, _ = _service(monkeypatch, streams=("profile",))
    monkeypatch.setattr(service, "sync", AsyncMock(side_effect=error))
    run = await service.start("alice")

    await service.execute("alice", run.id)

    last = service.status("alice").last_run
    assert last is not None and last.status == "failed" and last.error_code == error_code
    assert all(item.status == "skipped" for item in last.streams)
    assert "private-sentinel" not in caplog.text
    await service.start("alice")


async def test_binding_validation_failure_releases_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rejected start does not leave its owner locked."""
    service, _, _, _ = _service(monkeypatch, streams=("profile",))
    bindings = cast(MagicMock, service._bindings)
    db_session = bindings.session_factory.return_value.__enter__.return_value
    db_session.get.return_value = None

    with pytest.raises(NotBoundError):
        await service.start("alice")
    db_session.get.return_value = MagicMock(status="authenticated")
    run = await service.start("alice")

    assert service.status("alice").active_run is not None
    await service.execute("alice", run.id)


async def test_failed_unbind_preserves_runs_and_successful_unbind_clears_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """Volatile presentation changes only after the binding transaction succeeds."""
    service, _, _, _ = _service(monkeypatch, streams=("profile",))
    run = await service.start("alice")
    await service.execute("alice", run.id)
    bindings = cast(MagicMock, service._bindings)
    bindings.unbind.side_effect = RuntimeError("synthetic unbind failure")

    with pytest.raises(RuntimeError, match="synthetic unbind failure"):
        await service.unbind("alice")
    assert service.status("alice").last_run is not None

    bindings.unbind.side_effect = None
    await service.unbind("alice")
    final = service.status("alice")
    assert final.active_run is None and final.last_run is None


async def test_stale_or_mismatched_run_id_performs_no_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the server-created current active id can enter synchronization."""
    service, _, _, _ = _service(monkeypatch, streams=("profile",))
    execute_sync = AsyncMock(return_value=[SyncStreamResult("profile", "succeeded", 1, None)])
    monkeypatch.setattr(service, "sync", execute_sync)
    run = await service.start("alice")

    await service.execute("alice", "stale-run")
    await service.execute("bob", run.id)
    execute_sync.assert_not_awaited()
    assert service.status("alice").active_run is not None

    await service.execute("alice", run.id)
    execute_sync.assert_awaited_once_with("alice", run_id=run.id)


async def test_status_exposes_active_progress_then_latest_terminal_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Status reads observe running stream progress without acquiring the owner lock."""
    service, xiaomi, _, _ = _service(monkeypatch, streams=("profile",))
    provider_started = asyncio.Event()
    finish_provider = asyncio.Event()

    async def read_profile(session: object) -> dict[str, Any]:
        provider_started.set()
        await finish_provider.wait()
        return {}

    xiaomi.read_profile.side_effect = read_profile
    run = await service.start("alice")
    execution = asyncio.create_task(service.execute("alice", run.id))
    await provider_started.wait()

    active = service.status("alice").active_run
    assert active is not None and active.status == "running"
    assert active.streams[0].status == "running"
    finish_provider.set()
    await execution

    final = service.status("alice")
    assert final.active_run is None
    assert final.last_run is not None and final.last_run.status == "succeeded"


async def test_fresh_service_clears_runs_but_retains_durable_checkpoint_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A restarted coordinator has no run history but still exposes Core checkpoints."""
    from datetime import UTC, datetime

    state = _state()
    state.last_succeeded_at = datetime(2026, 11, 17, tzinfo=UTC)
    service, xiaomi, ingestion, sessions = _service(monkeypatch, streams=("profile", "daily_activity"), state=state)
    ingestion.checkpoints.return_value = [state]
    run = await service.start("alice")
    await service.execute("alice", run.id)
    assert service.status("alice").last_run is not None
    xiaomi.read_profile.reset_mock()
    xiaomi.read_daily.reset_mock()

    fresh = MiHealthSyncService(bindings=service._bindings, sessions=sessions, xiaomi=xiaomi, ingestion=ingestion)
    result = fresh.status("alice")

    assert result.active_run is None
    assert result.last_run is None
    assert [(item.stream, item.status) for item in result.streams] == [("profile", "never_synced"), ("daily_activity", "succeeded")]
    assert result.streams[1].last_succeeded_at == state.last_succeeded_at
    assert result.streams[1].last_successful_window_end == datetime.fromtimestamp(100, UTC)
    xiaomi.read_daily.assert_not_awaited()
