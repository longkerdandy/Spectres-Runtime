"""Ingestion layer — shape and stub assertions.

Origin-specific ingesters materialize recipes; a sink persists the stream. Tests
assert wiring shape and that the stubs raise — no files, network, DB, or LLM.
"""

from __future__ import annotations

import pytest

from spectres_runtime.recipe_agent.ingestion import (
    HowToCookIngester,
    RecipeIngester,
    RecipeSink,
    WriteResult,
)


def test_howtocook_is_a_recipe_ingester() -> None:
    assert issubclass(HowToCookIngester, RecipeIngester)
    assert HowToCookIngester.name == "howtocook"


def test_howtocook_ingest_is_unimplemented() -> None:
    with pytest.raises(NotImplementedError):
        HowToCookIngester().ingest()


def test_write_result_defaults_to_zero() -> None:
    result = WriteResult()
    assert (result.written, result.skipped, result.failed) == (0, 0, 0)


def test_recipe_sink_is_unimplemented() -> None:
    with pytest.raises(NotImplementedError):
        RecipeSink().write([])
