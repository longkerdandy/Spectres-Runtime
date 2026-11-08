"""Scheduled-task registration.

The AgentOS scheduler polls ``agno_schedules`` and fires each schedule as
one HTTP call to its endpoint. Extensions declare schedules via
``ExtensionContribution.schedules``; core creates missing schedules here at
startup and leaves existing rows untouched so administrator changes survive
restarts.
"""

import logging

from agno.db.postgres import PostgresDb
from agno.scheduler import ScheduleManager

from spectres.extensions.base import LoadedExtension

logger = logging.getLogger(__name__)


def register_schedules(extensions: list[LoadedExtension], db: PostgresDb) -> None:
    """Register all extension-contributed schedules with the Agno scheduler.

    Fail-loud like the extension loader: a failed registration aborts
    startup naming the schedule — a broken schedule never fails silently.
    """
    specs = [spec for extension in extensions for spec in extension.contribution.schedules]
    if not specs:
        return
    manager = ScheduleManager(db)
    try:
        for spec in specs:
            try:
                existing = db.get_schedule_by_name(spec.name, user_id=None)
                if existing is not None:
                    logger.info(
                        "schedule %r already exists, skipping",
                        spec.name,
                        extra={"event": "schedule_exists", "schedule": spec.name},
                    )
                    continue

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
                    if_exists="skip",
                )
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
                if not spec.enabled:
                    manager.disable(schedule.id)
                    logger.info(
                        "schedule %r registered as disabled",
                        spec.name,
                        extra={"event": "schedule_registered_disabled", "schedule": spec.name},
                    )
            except Exception as exc:
                raise RuntimeError(f"schedule {spec.name!r} failed to register: {exc}") from exc
    finally:
        manager.close()
