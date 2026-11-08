"""Unit tests for scheduled-task registration (spectres/scheduler.py)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spectres.extensions.base import ExtensionContribution, LoadedExtension, ScheduleSpec
from spectres.scheduler import register_schedules


def _loaded(contribution: ExtensionContribution) -> list[LoadedExtension]:
    return [LoadedExtension(id="test_extension", name="Test Extension", description="Test extension", contribution=contribution)]


@pytest.mark.unit
class TestRegisterSchedules:
    """register_schedules creates missing rows and preserves existing rows."""

    def _spec(self, **overrides: Any) -> ScheduleSpec:
        defaults: dict[str, Any] = {
            "name": "ETF Grid Daily Sync",
            "cron": "0 9 * * 1,5",
            "endpoint": "/workflows/etf_grid_data_sync/runs",
            "method": "POST",
            "timezone": "Asia/Shanghai",
            "timeout_seconds": 3600,
            "max_retries": 0,
            "retry_delay_seconds": 60,
            "enabled": True,
        }
        return ScheduleSpec(**(defaults | overrides))

    def _missing_db(self) -> MagicMock:
        db = MagicMock()
        db.get_schedule_by_name.return_value = None
        return db

    def test_no_schedules_skips_manager(self) -> None:
        """An empty contribution set never constructs a ScheduleManager."""
        with patch("spectres.scheduler.ScheduleManager") as manager_cls:
            register_schedules(_loaded(ExtensionContribution()), db=MagicMock())
        manager_cls.assert_not_called()

    def test_spec_maps_to_manager_create(self) -> None:
        """Every spec field lands on ScheduleManager.create with the same name."""
        manager = MagicMock()
        manager.create.return_value = MagicMock(id="sched-1", next_run_at=1760000000)
        with patch("spectres.scheduler.ScheduleManager", return_value=manager):
            register_schedules(
                _loaded(ExtensionContribution(schedules=[self._spec(max_retries=2, retry_delay_seconds=300)])),
                db=self._missing_db(),
            )
        manager.create.assert_called_once_with(
            name="ETF Grid Daily Sync",
            cron="0 9 * * 1,5",
            endpoint="/workflows/etf_grid_data_sync/runs",
            method="POST",
            payload=None,
            timezone="Asia/Shanghai",
            timeout_seconds=3600,
            max_retries=2,
            retry_delay_seconds=300,
            if_exists="skip",
        )
        manager.enable.assert_not_called()
        manager.disable.assert_not_called()
        manager.close.assert_called_once()

    def test_existing_schedule_is_left_untouched(self) -> None:
        """An existing row keeps its stored cron, enabled state, and next run time."""
        manager = MagicMock()
        db = MagicMock()
        db.get_schedule_by_name.return_value = MagicMock(
            id="sched-1",
            cron_expr="0 18 * * *",
            enabled=False,
            next_run_at=1760000000,
        )
        with patch("spectres.scheduler.ScheduleManager", return_value=manager):
            register_schedules(
                _loaded(ExtensionContribution(schedules=[self._spec(cron="0 9 * * 1,5", enabled=True)])),
                db=db,
            )
        db.get_schedule_by_name.assert_called_once_with("ETF Grid Daily Sync", user_id=None)
        manager.create.assert_not_called()
        manager.update.assert_not_called()
        manager.enable.assert_not_called()
        manager.disable.assert_not_called()
        manager.close.assert_called_once()

    def test_disabled_spec_disables_only_a_new_row(self) -> None:
        """enabled=False sets the initial state without enabling the new row first."""
        manager = MagicMock()
        manager.create.return_value = MagicMock(id="sched-1", next_run_at=1760000000)
        with patch("spectres.scheduler.ScheduleManager", return_value=manager):
            register_schedules(
                _loaded(ExtensionContribution(schedules=[self._spec(enabled=False)])),
                db=self._missing_db(),
            )
        manager.disable.assert_called_once_with("sched-1")
        manager.enable.assert_not_called()

    def test_failure_aborts_naming_the_schedule(self, caplog: pytest.LogCaptureFixture) -> None:
        """A failed registration propagates with its cause and is not logged a second time."""
        manager = MagicMock()
        manager.create.side_effect = ValueError("invalid cron")
        with (
            patch("spectres.scheduler.ScheduleManager", return_value=manager),
            pytest.raises(RuntimeError, match="ETF Grid Daily Sync") as exc_info,
        ):
            register_schedules(_loaded(ExtensionContribution(schedules=[self._spec()])), db=self._missing_db())
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert not caplog.records
        manager.close.assert_called_once()
