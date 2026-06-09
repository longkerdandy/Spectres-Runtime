"""Unit tests for ``spectres_runtime.config`` — pure, no DB, no network.

Scoped to the *shared* infrastructure config (database, embedder, chat) and how
``get_settings`` composes the per-module sub-configs. Each agent's private
settings are tested next to that agent (e.g.
``tests/recipe_agent/test_config.py``). The live embed / chat calls live in the
``integration`` tier (see ``test_embedder_integration``).
"""

from __future__ import annotations

import pytest
from agno.knowledge.embedder.openai import OpenAIEmbedder
from pydantic import SecretStr

from spectres_runtime.config import Settings, get_settings
from tests.conftest import make_settings

_ENV = {
    "DATABASE_URL": "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime",
    "EMBEDDER_MODEL": "Qwen/Qwen3-Embedding-0.6B",
    "EMBEDDER_BASE_URL": "https://api.siliconflow.cn/v1",
    "EMBEDDER_DIMENSIONS": "1024",
    "EMBEDDER_API_KEY": "sk-secret",
    # Required for `get_settings()` to compose the recipe-agent sub-config; the
    # prefix / field mapping itself is covered in tests/recipe_agent/test_config.py.
    "RECIPE_AGENT_INSTRUCTIONS": "Search recipes before answering.",
    "RECIPE_AGENT_NUM_HISTORY_RUNS": "5",
}


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime"
    assert settings.embedder_model == "Qwen/Qwen3-Embedding-0.6B"
    assert settings.embedder_base_url == "https://api.siliconflow.cn/v1"
    assert settings.embedder_dimensions == 1024
    # Secret stays wrapped; not exposed by repr.
    assert settings.embedder_api_key.get_secret_value() == "sk-secret"
    # `get_settings()` wired the per-module sub-config (values asserted in its own suite).
    assert settings.recipe_agent.num_history_runs == 5


def test_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_build_embedder_maps_every_field() -> None:
    settings = make_settings(
        embedder_model="custom/model",
        embedder_base_url="https://example.test/v1",
        embedder_dimensions=512,
        embedder_api_key=SecretStr("sk-secret"),
    )

    embedder = settings.build_embedder()

    assert isinstance(embedder, OpenAIEmbedder)
    assert embedder.id == "custom/model"
    assert embedder.base_url == "https://example.test/v1"
    assert embedder.dimensions == 512
    # SecretStr is unwrapped to a plain string for the OpenAI client.
    assert embedder.api_key == "sk-secret"
