"""Synthetic bounded-window, pagination, retry, and sync privacy tests."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import spectres.extensions.mi_health.service.sync as sync_module
from spectres.extensions.mi_health.config import MiHealthConfig
from spectres.extensions.mi_health.service import MiHealthBindingService, MiHealthSessionService, MiHealthSyncService
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
