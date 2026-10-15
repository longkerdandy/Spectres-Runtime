"""Scheduled-task registration.

The AgentOS scheduler polls ``agno_schedules`` and fires each schedule as
one HTTP call to its endpoint. Extensions declare schedules via
``ExtensionContribution.schedules``; core registers them here at startup,
idempotently (``if_exists="update"`` by default), so restarts neither
duplicate nor reset code-registered schedules.
"""

import logging

from agno.db.postgres import PostgresDb
from agno.scheduler import ScheduleManager

from spectres.extensions.base import ExtensionContribution

logger = logging.getLogger(__name__)


def register_schedules(contributions: list[ExtensionContribution], db: PostgresDb) -> None:
    """Register all extension-contributed schedules with the Agno scheduler.

    Fail-loud like the extension loader: a failed registration aborts
    startup naming the schedule (names carry the extension prefix, e.g.
    ``etf_grid_daily_sync``) — a broken schedule never fails silently.
    """
    specs = [spec for contribution in contributions for spec in contribution.schedules]
    if not specs:
        return
    manager = ScheduleManager(db)
    try:
        for spec in specs:
            try:
                schedule = manager.create(
                    name=spec.name,
                    cron=spec.cron,
                    endpoint=spec.endpoint,
                    method=spec.method,
                    payload=spec.payload,
                    timezone=spec.timezone,
                    timeout_seconds=spec.timeout_seconds,
                    max_retries=spec.max_retries,
                    retry_delay_seconds=spec.retry_delay_seconds,
                    if_exists="update",
                )
            except Exception as exc:
                logger.error("schedule %r failed to register", spec.name, exc_info=exc, extra={"event": "schedule_register_failed"})
                raise RuntimeError(f"schedule {spec.name!r} failed to register: {exc}") from exc
            logger.info(
                "schedule %r registered (cron=%s tz=%s -> %s %s, next_run_at=%s)",
                spec.name,
                spec.cron,
                spec.timezone,
                spec.method,
                spec.endpoint,
                schedule.next_run_at,
                extra={"event": "schedule_registered", "schedule": spec.name},
            )
            # Converge the DB row to the configured state in both
            # directions: ``create`` does not touch ``enabled``, so a
            # schedule disabled via config would otherwise stay disabled
            # forever once re-enabled.
            if spec.enabled:
                manager.enable(schedule.id)
            else:
                manager.disable(schedule.id)
                logger.info("schedule %r registered as disabled", spec.name, extra={"event": "schedule_registered_disabled", "schedule": spec.name})
    finally:
        manager.close()
