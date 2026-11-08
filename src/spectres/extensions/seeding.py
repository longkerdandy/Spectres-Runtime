"""Collection-level initialization for database-backed extension configuration."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from spectres.extensions.base import LoadedExtension

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigSeedSpec:
    """Initialize one configuration collection only while its target is empty."""

    id: str
    has_existing_data: Callable[[], bool]
    initialize: Callable[[], int]


def initialize_config_seeds(extensions: list[LoadedExtension]) -> None:
    """Initialize each declared configuration collection unless any data exists."""
    for extension in extensions:
        for spec in extension.contribution.config_seeds:
            try:
                if spec.has_existing_data():
                    logger.info(
                        "configuration seed %r skipped because stored data exists",
                        spec.id,
                        extra={"event": "config_seed_skipped", "extension_id": extension.id, "seed_id": spec.id},
                    )
                    continue
                inserted = spec.initialize()
                logger.info(
                    "configuration seed %r initialized %d records",
                    spec.id,
                    inserted,
                    extra={"event": "config_seed_initialized", "extension_id": extension.id, "seed_id": spec.id, "inserted": inserted},
                )
            except Exception as exc:
                raise RuntimeError(f"configuration seed {spec.id!r} failed to initialize: {exc}") from exc
