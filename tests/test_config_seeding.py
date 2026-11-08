"""Unit tests for collection-level extension configuration initialization."""

import logging
from unittest.mock import MagicMock

import pytest

from spectres.extensions.base import ExtensionContribution, LoadedExtension
from spectres.extensions.seeding import ConfigSeedSpec, initialize_config_seeds

pytestmark = pytest.mark.unit


def _extension(spec: ConfigSeedSpec) -> list[LoadedExtension]:
    return [LoadedExtension(id="sample", name="Sample", description="Sample extension", contribution=ExtensionContribution(config_seeds=[spec]))]


def test_empty_collection_is_initialized() -> None:
    """An empty target receives the complete configured collection."""
    initialize = MagicMock(return_value=3)
    spec = ConfigSeedSpec(id="sample.items", has_existing_data=MagicMock(return_value=False), initialize=initialize)

    initialize_config_seeds(_extension(spec))

    initialize.assert_called_once_with()


def test_nonempty_collection_skips_the_whole_seed() -> None:
    """Existing data prevents both additions and updates from configuration."""
    initialize = MagicMock(return_value=1)
    spec = ConfigSeedSpec(id="sample.items", has_existing_data=MagicMock(return_value=True), initialize=initialize)

    initialize_config_seeds(_extension(spec))

    initialize.assert_not_called()


def test_seed_failure_names_the_collection_and_preserves_the_cause() -> None:
    """Initialization fails loudly instead of leaving partial startup unnoticed."""
    initialize = MagicMock(side_effect=ValueError("invalid collection"))
    spec = ConfigSeedSpec(id="sample.items", has_existing_data=MagicMock(return_value=False), initialize=initialize)

    with pytest.raises(RuntimeError, match=r"sample\.items.*invalid collection") as exc_info:
        initialize_config_seeds(_extension(spec))

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_seed_events_include_extension_and_collection(caplog: pytest.LogCaptureFixture) -> None:
    """Initialization and skip decisions share structured audit metadata."""
    with caplog.at_level(logging.INFO, logger="spectres.extensions.seeding"):
        initialize_config_seeds(_extension(ConfigSeedSpec(id="sample.items", has_existing_data=MagicMock(return_value=False), initialize=MagicMock(return_value=2))))
        initialize_config_seeds(_extension(ConfigSeedSpec(id="sample.items", has_existing_data=MagicMock(return_value=True), initialize=MagicMock())))

    assert [(record.__dict__["event"], record.__dict__["extension_id"], record.__dict__["seed_id"]) for record in caplog.records] == [
        ("config_seed_initialized", "sample", "sample.items"),
        ("config_seed_skipped", "sample", "sample.items"),
    ]
