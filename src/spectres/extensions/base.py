"""Extension contract: context, contribution, and protocol (runtime-extensions.md §4)."""

from dataclasses import dataclass, field
from typing import Protocol

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
class ExtensionContribution:
    """What an extension gives back to Runtime."""

    toolkits: list[Toolkit] = field(default_factory=list)
    routers: list[APIRouter] = field(default_factory=list)


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
