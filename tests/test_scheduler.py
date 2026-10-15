"""Unit tests for scheduled-task registration (spectres/scheduler.py)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spectres.extensions.base import ExtensionContribution, ScheduleSpec
from spectres.scheduler import register_schedules


@pytest.mark.unit
class TestRegisterSchedules:
    """register_schedules maps ScheduleSpec onto ScheduleManager.create, fail-loud."""

    def _spec(self, **overrides: Any) -> ScheduleSpec:
        defaults: dict[str, Any] = {
            "name": "etf_grid_daily_sync",
            "cron": "0 9 * * 1,5",
            "endpoint": "/api/v1/extensions/etf-grid/refresh",
            "method": "POST",
            "timezone": "Asia/Shanghai",
            "timeout_seconds": 3600,
            "max_retries": 0,
            "retry_delay_seconds": 60,
            "enabled": True,
        }
        return ScheduleSpec(**(defaults | overrides))

    def test_no_schedules_skips_manager(self) -> None:
        """An empty contribution set never constructs a ScheduleManager."""
        with patch("spectres.scheduler.ScheduleManager") as manager_cls:
            register_schedules([ExtensionContribution()], db=MagicMock())
        manager_cls.assert_not_called()

    def test_spec_maps_to_manager_create(self) -> None:
        """Every spec field lands on ScheduleManager.create with the same name."""
        manager = MagicMock()
        manager.create.return_value = MagicMock(id="sched-1", next_run_at=1760000000)
        with patch("spectres.scheduler.ScheduleManager", return_value=manager):
            register_schedules([ExtensionContribution(schedules=[self._spec(max_retries=2, retry_delay_seconds=300)])], db=MagicMock())
        manager.create.assert_called_once_with(
            name="etf_grid_daily_sync",
            cron="0 9 * * 1,5",
            endpoint="/api/v1/extensions/etf-grid/refresh",
            method="POST",
            payload=None,
            timezone="Asia/Shanghai",
            timeout_seconds=3600,
            max_retries=2,
            retry_delay_seconds=300,
            if_exists="update",
        )
        # create() does not touch `enabled`; an enabled spec converges the row explicitly.
        manager.enable.assert_called_once_with("sched-1")
        manager.disable.assert_not_called()
        manager.close.assert_called_once()

    def test_disabled_spec_disables_the_row(self) -> None:
        """enabled=False registers idempotently, then disables — config converges DB state."""
        manager = MagicMock()
        manager.create.return_value = MagicMock(id="sched-1", next_run_at=1760000000)
        with patch("spectres.scheduler.ScheduleManager", return_value=manager):
            register_schedules([ExtensionContribution(schedules=[self._spec(enabled=False)])], db=MagicMock())
        manager.disable.assert_called_once_with("sched-1")
        manager.enable.assert_not_called()

    def test_failure_aborts_naming_the_schedule(self) -> None:
        """A failed registration raises RuntimeError naming the schedule (fail-loud like the loader)."""
        manager = MagicMock()
        manager.create.side_effect = ValueError("invalid cron")
        with patch("spectres.scheduler.ScheduleManager", return_value=manager), pytest.raises(RuntimeError, match="etf_grid_daily_sync"):
            register_schedules([ExtensionContribution(schedules=[self._spec()])], db=MagicMock())
        manager.close.assert_called_once()
