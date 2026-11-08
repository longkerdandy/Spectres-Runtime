"""Extension contract: context, contribution, and protocol."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from agno.db.postgres import PostgresDb
from agno.tools.toolkit import Toolkit
from agno.workflow import Workflow
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
    for non-run endpoints a 2xx response is success. All fields are required
    except ``payload``. Startup creates missing rows and preserves existing
    configuration.
    """

    name: str  # unique per owner; system schedules may use a human-readable display name
    cron: str
    endpoint: str
    method: str
    timezone: str
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: int
    enabled: bool  # Applied only when creating the row; later administrator changes survive restarts
    payload: dict[str, Any] | None = None


@dataclass
class ExtensionContribution:
    """What an extension gives back to Runtime."""

    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    workflows: list[Workflow] = field(default_factory=list)
    schedules: list[ScheduleSpec] = field(default_factory=list)


@dataclass
class LoadedExtension:
    """A discovered extension's metadata and registered surfaces."""

    id: str
    name: str
    description: str
    contribution: ExtensionContribution


class Extension(Protocol):
    """Extension manifest protocol: stable metadata plus a register hook.

    Any object with this shape qualifies — in practice each package's own
    ``extension.py`` module, exposed as the package-level ``extension``
    attribute.
    """

    id: str  # unique stable id, snake_case, e.g. "etf_grid"
    name: str  # human-readable display name
    description: str  # human-readable capability summary

    def register(self, ctx: ExtensionContext) -> ExtensionContribution:
        """Build and return the extension's contributions."""
        ...
