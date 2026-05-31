"""Recipe source modules are importable.

Interface-contract and stub assertions are not yet defined.
"""

from __future__ import annotations

import importlib


def test_source_modules_importable() -> None:
    for name in (
        "spectres_runtime.recipe_agent.sources",
        "spectres_runtime.recipe_agent.sources.base",
        "spectres_runtime.recipe_agent.sources.howtocook",
    ):
        assert importlib.import_module(name) is not None
