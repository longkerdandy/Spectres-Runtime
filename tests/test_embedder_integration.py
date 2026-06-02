"""Integration check for the hosted embedding provider.

Opt-in: marked ``integration`` (excluded from the default gate) and skipped unless
the runtime config is complete (a real key reachable via the process env or a local
``.env``). When it is, a live call asserts the configured embedder returns a vector
of the configured dimensionality for a Chinese test string — the acceptance bar for
the embedding provider being configured and reachable.

Run with a populated ``.env`` (or env vars): ``uv run pytest -m integration``
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spectres_runtime.config import Settings, get_settings

pytestmark = pytest.mark.integration


def _settings_or_skip() -> Settings:
    """Load Settings, or skip if the config (incl. the API key) is incomplete.

    ``get_settings`` reads the process env and a local ``.env``; a missing required
    field (e.g. no key) raises ``ValidationError``, which we turn into a skip so the
    opt-in tier is a no-op without credentials.
    """
    try:
        return get_settings()
    except ValidationError:
        pytest.skip("Runtime config incomplete (no key via env / .env) — live call skipped.")


def test_embedder_returns_vector_for_chinese_string() -> None:
    settings = _settings_or_skip()
    embedder = settings.build_embedder()

    vector = embedder.get_embedding("番茄炒蛋怎么做")

    assert isinstance(vector, list)
    assert len(vector) == settings.embedder_dimensions
    assert all(isinstance(component, float) for component in vector)
