"""Extension contract: context, contribution, and protocol."""

from dataclasses import dataclass, field
from typing import Protocol

from agno.db.postgres import PostgresDb
from agno.tools.toolkit import Toolkit
from agno.workflow import Workflow
from fastapi import APIRouter

from spectres.config import DefaultConfigSpec, Settings
from spectres.scheduler import ScheduleSpec


@dataclass
class ExtensionContext:
    """Runtime infrastructure injected into each extension at load time."""

    settings: Settings
    db: PostgresDb  # Agno db handle; its public ``db_engine`` attribute backs the extension's own tables


@dataclass
class ExtensionContribution:
    """What an extension gives back to Runtime."""

    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)
    workflows: list[Workflow] = field(default_factory=list)
    default_configs: list[DefaultConfigSpec] = field(default_factory=list)
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
