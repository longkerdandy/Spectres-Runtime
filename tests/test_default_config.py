"""Unit tests for core default configuration initialization."""

import logging
from unittest.mock import MagicMock

import pytest

from spectres.config import DefaultConfigSpec, initialize_default_configs

pytestmark = pytest.mark.unit


def test_empty_collection_is_initialized() -> None:
    """An empty target receives the complete configured collection."""
    initialize = MagicMock(return_value=3)
    spec = DefaultConfigSpec(name="sample.items", has_existing_data=MagicMock(return_value=False), initialize=initialize)

    initialize_default_configs([spec])

    initialize.assert_called_once_with()


def test_nonempty_collection_skips_the_whole_default() -> None:
    """Existing data prevents both additions and updates from configuration."""
    initialize = MagicMock(return_value=1)
    spec = DefaultConfigSpec(name="sample.items", has_existing_data=MagicMock(return_value=True), initialize=initialize)

    initialize_default_configs([spec])

    initialize.assert_not_called()


def test_initialization_failure_names_the_collection_and_preserves_the_cause() -> None:
    """Initialization fails loudly instead of leaving partial startup unnoticed."""
    initialize = MagicMock(side_effect=ValueError("invalid collection"))
    spec = DefaultConfigSpec(name="sample.items", has_existing_data=MagicMock(return_value=False), initialize=initialize)

    with pytest.raises(RuntimeError, match=r"sample\.items.*invalid collection") as exc_info:
        initialize_default_configs([spec])

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_default_config_events_include_resource_name(caplog: pytest.LogCaptureFixture) -> None:
    """Initialization and skip decisions use the same structured resource name."""
    with caplog.at_level(logging.INFO, logger="spectres.config"):
        initialize_default_configs([DefaultConfigSpec(name="sample.items", has_existing_data=MagicMock(return_value=False), initialize=MagicMock(return_value=2))])
        initialize_default_configs([DefaultConfigSpec(name="sample.items", has_existing_data=MagicMock(return_value=True), initialize=MagicMock())])

    assert [(record.__dict__["event"], record.__dict__["resource_name"]) for record in caplog.records] == [
        ("default_config_initialized", "sample.items"),
        ("default_config_skipped", "sample.items"),
    ]
