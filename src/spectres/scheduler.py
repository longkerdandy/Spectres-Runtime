"""System Schedule declarations and initialization.

The AgentOS scheduler polls ``agno_schedules`` and fires each Schedule as
one HTTP call to its endpoint. Runtime creates missing system Schedules at
startup and leaves existing rows untouched so administrator changes survive
restarts.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agno.db.postgres import PostgresDb
from agno.scheduler import ScheduleManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleSpec:
    """System Schedule initialized only when no stored Schedule has its name.

    The AgentOS scheduler fires one HTTP call to ``endpoint`` on the cron
    cadence, and for non-run endpoints a 2xx response is success. All fields
    are required except ``payload``. ``enabled`` applies only at initialization;
    later administrator changes survive restarts.
    """

    name: str
    cron: str
    endpoint: str
    method: str
    timezone: str
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: int
    enabled: bool
    payload: dict[str, Any] | None = None


def register_schedules(specs: Sequence[ScheduleSpec], db: PostgresDb) -> None:
    """Create missing system Schedules and preserve every existing stored row."""
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
                        extra={"event": "schedule_exists", "resource_name": spec.name},
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
                    extra={"event": "schedule_registered", "resource_name": spec.name},
                )
                if not spec.enabled:
                    manager.disable(schedule.id)
                    logger.info(
                        "schedule %r registered as disabled",
                        spec.name,
                        extra={"event": "schedule_registered_disabled", "resource_name": spec.name},
                    )
            except Exception as exc:
                raise RuntimeError(f"schedule {spec.name!r} failed to initialize: {exc}") from exc
    finally:
        manager.close()
