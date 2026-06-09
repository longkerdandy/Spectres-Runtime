"""Unit tests for ``spectres_runtime.recipe_agent.config`` — pure, no DB, no network.

Mirrors the source split: ``RecipeAgentSettings`` lives in the ``recipe_agent``
package, so its tests live alongside the package's other tests rather than in the
top-level config suite. Covers the ``RECIPE_AGENT_`` prefix mapping and the
no-defaults contract.
"""

from __future__ import annotations

import pytest

from spectres_runtime.recipe_agent.config import RecipeAgentSettings


def test_recipe_agent_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The `RECIPE_AGENT_` prefix maps `RECIPE_AGENT_<FIELD>` -> `<field>`.
    monkeypatch.setenv("RECIPE_AGENT_INSTRUCTIONS", "Search recipes before answering.")
    monkeypatch.setenv("RECIPE_AGENT_NUM_HISTORY_RUNS", "5")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_MODEL", "model-id")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_API_KEY", "sk-secret")

    settings = RecipeAgentSettings()

    assert settings.instructions == "Search recipes before answering."
    assert settings.num_history_runs == 5
    assert settings.chat_model == "model-id"
    assert settings.chat_base_url == "https://chat.example/v1"
    assert settings.chat_api_key.get_secret_value() == "sk-secret"


def test_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECIPE_AGENT_INSTRUCTIONS", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_NUM_HISTORY_RUNS", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_CHAT_MODEL", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_CHAT_API_KEY", raising=False)

    # No defaults: with nothing in the env (and `.env` bypassed) construction fails.
    with pytest.raises(ValueError):
        RecipeAgentSettings(_env_file=None)
