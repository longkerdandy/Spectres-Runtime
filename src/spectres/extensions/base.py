"""Extension contract: context, contribution, and protocol."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from agno.db.postgres import PostgresDb
from agno.tools.toolkit import Toolkit
from fastapi import APIRouter

from spectres.config import Settings


@dataclass
class ExtensionContext:
    """Runtime infrastructure injected into each extension at load time."""

    settings: Settings
    db: PostgresDb  # Agno db handle; its public ``db_engine`` attribute backs the extension's own tables


@dataclass
class ScheduleSpec:
    """Declarative scheduled-task definition.

    A schedule is ``{cron, endpoint, method, payload}``: the AgentOS
    scheduler fires one HTTP call to ``endpoint`` on the cron cadence, and
    for non-run endpoints a 2xx response is success. All fields are
    required except ``payload``; registration always uses
    ``if_exists="update"`` so restarts converge the DB row to code.
    """

    name: str  # unique, prefixed with the extension id, e.g. "etf_grid_daily_sync"
    cron: str
    endpoint: str
    method: str
    timezone: str
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: int
    enabled: bool  # False: register (idempotently) then disable, so config state converges the DB row
    payload: dict[str, Any] | None = None


@dataclass
class ExtensionContribution:
    """What an extension gives back to Runtime."""

    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    schedules: list[ScheduleSpec] = field(default_factory=list)


class Extension(Protocol):
    """Extension manifest protocol: a unique id plus a register hook.

    Any object with this shape qualifies — in practice each package's own
    ``extension.py`` module, exposed as the package-level ``extension``
    attribute (a module's top-level ``name`` and ``register`` play the
    attribute/method roles at runtime).
    """

    name: str  # unique id, snake_case, e.g. "etf_grid"

    def register(self, ctx: ExtensionContext) -> ExtensionContribution:
        """Build and return the extension's contributions."""
        ...
