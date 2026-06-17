"""Smoke tests for the spectres package."""

import spectres


def test_package_importable() -> None:
    """Verify the spectres package is importable."""
    assert spectres is not None
