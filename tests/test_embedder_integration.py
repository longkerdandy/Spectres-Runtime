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

from tests.conftest import settings_or_skip

pytestmark = pytest.mark.integration


def test_embedder_returns_vector_for_chinese_string() -> None:
    settings = settings_or_skip()
    embedder = settings.build_embedder()

    vector = embedder.get_embedding("番茄炒蛋怎么做")

    assert isinstance(vector, list)
    assert len(vector) == settings.embedder_dimensions
    assert all(isinstance(component, float) for component in vector)
